package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.sync.internal.client.Documents
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream

/** /api/peer/state, as the phone reads it. */
data class PeerState(val format: Int, val server: String?, val caracole: String, val name: String, val now: String?,
                     val units: Map<String, SyncUnit>, val base: Base?, val token: String,
                     val indexes: Map<String, String> = emptyMap(), val settings: JsonObject? = null) {
    companion object {
        /** A state document, read as [PeerClient.state] reads the computer's (read_state_document): its `settings`
         * the computer's settings, none for a member that isn't an object. A [PeerError] for one that can't be read. */
        fun read(document: JsonElement): PeerState = try {
            Documents.state(document)
        } catch (e: Documents.Unreadable) {
            throw PeerError("The computer's state can't be read: ${e.message}.", cause = e)
        }
    }
}

/** What the computer answered that the phone can't go on with, said as one sentence ([message]); [status], the
 * HTTP status it answered with, when it answered one. Nothing answering at all is mirror's SyncError.NoAnswer. */
class PeerError(message: String, val status: Int? = null, cause: Throwable? = null) : Exception(message, cause)

/**
 * The computer's peer routes, from the phone (peer_sync.Peer's reads, and the push the phone sends because it serves
 * nothing to the network): one request at a time, through mirror's [Http] (no redirect followed, no cookie).
 *
 * - **Reads** (`Accept: application/json`): [state], with a 60 s read timeout (a library's every song is read to
 *   answer); [unit], its document checked to be of format 2 and of the id asked; [file], its bytes checked against
 *   the SHA-256 the unit gives; [job], the computer's request as `GET /api/jobs/<id>` gives it.
 * - **The push**: [pushNew], [pushFile] and [push], each with the form token in the header `X-Caracole-Form-Token`
 *   (caracole serve's `json` and `bytes` routes) and no Origin or Sec-Fetch-Site, which a non-browser never sends. A
 *   403 whose JSON says `reload` (a token older than the server: it restarted since the state was read) reads the
 *   state again, once, for its fresh token, and sends the call again with it; the calls after it that give the old
 *   token send the fresh one.
 * - **The index**: [index] streams `GET /api/peer/index` to a file, with a read timeout of [INDEX_TIMEOUT_MS]
 *   between two reads (the file is as large as the computer's indexes, and made before its first byte comes: a
 *   connection that goes quiet for longer is a lost one, so a sync job never waits on it for ever); [pushIndex]
 *   streams the pages the phone's lookups read to `POST /peer/index`, a `bytes` route of the push's kind.
 *
 * Every answer that says no is a [PeerError] in the words peer_sync.Peer says it; a document that can't be read, too.
 */
class PeerClient(val address: ServerAddress, http: Http = Http()) : UnitSource {
    private val http = http
    private var asking: String? = null
    private val renewed = HashMap<String, String>()

    /** GET /api/peer/state, a 60 s read timeout: the computer's state, with its base for [asking] (the phone's id). */
    fun state(asking: String?): PeerState {
        this.asking = asking
        val answer = get(STATE_PATH + (asking?.let { "?peer=" + Documents.quote(it) } ?: ""), STATE_TIMEOUT_MS)
        if (answer.status == 404) {
            throw PeerError("$address answered, but not as a caracole that shares. An older caracole, or " +
                            "something else?", 404)
        }
        if (answer.status != 200) throw refused(answer)
        return try {
            Documents.state(answer.json())
        } catch (e: Documents.Unreadable) {
            throw PeerError("$address answered ${e.message}.", 200, e)
        }
    }

    /** POST /peer/push/new: the push's id, and the shas the computer needs. */
    fun pushNew(token: String, from: String, files: List<String>): Pair<String, List<String>> {
        val doc = JsonObject(linkedMapOf(
            "format" to JsonPrimitive(Units.FORMAT), "from" to JsonPrimitive(from),
            "files" to JsonArray(files.distinct().map(::JsonPrimitive)),
        ))
        val answer = posting(token) { use -> postJson(PUSH_NEW_PATH, use, doc) }
        if (answer.status != 200) throw refused(answer)
        val data = answer.json() as? JsonObject
        val push = Documents.text(data?.get("push"))
        val need = (data?.get("need") as? JsonArray)?.map { Documents.text(it) }
        if (push == null || !PUSH_ID.matches(push) || need == null || need.any { it == null || it !in files }) {
            throw PeerError("$address answered our changes with something we can't read.", 200)
        }
        return push to need.map { it!! }
    }

    /** POST /peer/push/file: a file the push needs, its bytes. */
    fun pushFile(token: String, push: String, sha256: String, bytes: ByteArray) {
        val path = PUSH_FILE_PATH + "?push=" + Documents.quote(push) + "&sha256=" + Documents.quote(sha256)
        val answer = posting(token) { use -> post(path, use, OCTETS, bytes) }
        if (answer.status != 200) throw refused(answer)
    }

    /** POST /peer/push: the push document, and the computer's job that takes it (its id). */
    fun push(token: String, push: String, payload: JsonObject): Int {
        val answer = posting(token) { use -> postJson(PUSH_PATH + "?push=" + Documents.quote(push), use, payload) }
        if (answer.status != 200 && answer.status != 202) throw refused(answer)
        val job = (answer.json() as? JsonObject)?.get("job")
        val id = when (job) {
            is JsonObject -> (job["id"] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toIntOrNull()
            is JsonPrimitive -> job.takeIf { !it.isString }?.contentOrNull?.toIntOrNull()
            else -> null
        }
        return id ?: throw PeerError("$address took the push but named no Journal entry for it.",
                                     answer.status)
    }

    /** GET /api/jobs/<id>: the computer's request, as its Job.as_json gives it, its `state` a text
     * (peer_push.Pusher.job). */
    fun job(id: Int): JsonObject {
        val answer = get("$JOBS_PATH$id")
        if (answer.status != 200) throw refused(answer)
        val job = try {
            answer.json()
        } catch (e: PeerError) {
            null
        } as? JsonObject
        if (job == null || Documents.text(job["state"]) == null) {
            throw PeerError("$address answered about entry $id in a form we can't read.", 200)
        }
        return job
    }

    /** POST /peer/index: the index export at [file] (the pages the phone's lookups stored, IndexExport's), its bytes
     * streamed with the form token, staged by the computer and merged by a queued `caracole index merge --delete
     * --progress`: the computer's job id, once it answers 202. A [PeerError] for a file past [INDEX_MAX] (sent
     * nothing), for a computer that takes no index pages (404: older than the app), and for each refusal in the
     * computer's words (400 an export it can't take, 409 one of another version or two waiting there already, 413,
     * 503), so that the caller keeps what it would have forgotten. */
    fun pushIndex(token: String, file: File): Int {
        val length = file.length()
        if (length > INDEX_MAX) {
            throw PeerError("The pages read here make ${(length + MIB - 1) / MIB} MiB; the computer takes " +
                            "${INDEX_MAX / MIB} MiB at most. They stay here.")
        }
        val answer = posting(token) { use ->
            http.post(address, address.resolve(INDEX_PUSH_PATH), OCTETS, mapOf(TOKEN_HEADER to use, "Accept" to JSON),
                      length, { out -> file.inputStream().use { it.copyTo(out, 64 * 1024) } }) {
                Answered(it.status, readAtMost(it.body, MAX_JSON))
            }
        }
        if (answer.status == 404) {
            throw PeerError("$address takes no index pages: its caracole may be older than the app.", 404)
        }
        if (answer.status != 202 && answer.status != 200) throw refused(answer)
        val job = (answer.json() as? JsonObject)?.get("job")
        return (job as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toIntOrNull()
            ?: throw PeerError("$address took the index pages but named no request to merge them.", answer.status)
    }

    /** GET /api/peer/index ([sites]: those alone, every one when null), streamed into [to], [INDEX_TIMEOUT_MS] at
     * most between two reads. */
    fun index(to: File, sites: List<String>? = null) {
        val path = INDEX_PATH + (sites?.let { "?sites=" + Documents.quote(it.joinToString(",")) } ?: "")
        http.get(address, address.resolve(path), emptyMap(), readTimeoutMs = INDEX_TIMEOUT_MS) { answer ->
            if (answer.status != 200) throw refused(Answered(answer.status, readAtMost(answer.body, MAX_JSON)))
            // The answer's bytes as they come; a write that fails is the phone's storage, never the connection.
            val out = try {
                to.outputStream()
            } catch (e: IOException) {
                throw PeerError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", cause = e)
            }
            out.use {
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = answer.body.read(buffer)
                    if (n < 0) break
                    try {
                        out.write(buffer, 0, n)
                    } catch (e: IOException) {
                        to.delete()
                        throw PeerError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", cause = e)
                    }
                }
                out.fd.sync()
            }
        }
    }

    /** GET /api/peer/unit: the unit's document (its `unit_document`'s `"unit"`), null for a unit it hasn't got. */
    override fun unit(id: String): JsonObject? {
        val answer = get(UNIT_PATH + "?id=" + Documents.quote(id))
        if (answer.status == 404) return null
        if (answer.status != 200) throw refused(answer)
        val doc = try {
            answer.json()
        } catch (e: PeerError) {
            null
        } as? JsonObject
        val unit = doc?.get("unit")
        if (doc == null || !Documents.isNumber(doc["format"], Units.FORMAT) || Documents.text(doc["id"]) != id ||
            Documents.text(doc["digest"]) == null || unit !is JsonObject) {
            throw PeerError("$address answered $id with something we can't read.", 200)
        }
        return unit
    }

    /** GET /api/peer/file: a kept file of its song of [songKey], checked against [sha256]. */
    override fun file(songKey: String, name: String, sha256: String): ByteArray {
        val path = FILE_PATH + "?song=" + Documents.quote(songKey) + "&name=" + Documents.quote(name)
        val answer = http.get(address, address.resolve(path)) { Answered(it.status, readAtMost(it.body, MAX_FILE)) }
        if (answer.status != 200) throw refused(answer)
        val bytes = answer.bytes
        if (bytes == null || Canonical.sha256Hex(bytes) != sha256) {
            throw PeerError("$address sent $name changed since compared. The song stays as it was here.", 200)
        }
        return bytes
    }

    // --- asking --------------------------------------------------------------------------------------------------

    /** An answer read whole: its status and its bytes (null when longer than allowed). */
    private class Answered(val status: Int, val bytes: ByteArray?)

    private fun Answered.json(): JsonElement {
        val text = bytes?.toString(Charsets.UTF_8)
            ?: throw PeerError("$address answered with more than we read.", status)
        return try {
            Canonical.parse(text)
        } catch (e: CanonicalError) {
            throw PeerError("$address answered with something that isn't JSON.", status, e)
        }
    }

    private fun get(path: String, readTimeoutMs: Int? = null): Answered {
        val uri = address.resolve(path)
        val headers = mapOf("Accept" to JSON)
        val read: (Http.Answer) -> Answered = { Answered(it.status, readAtMost(it.body, MAX_JSON)) }
        return if (readTimeoutMs == null) http.get(address, uri, headers, read = read)
        else http.get(address, uri, headers, readTimeoutMs, read)
    }

    private fun postJson(path: String, token: String, doc: JsonObject): Answered =
        post(path, token, JSON, PyJson.dumps(doc, compact = true).toByteArray(Charsets.UTF_8))

    private fun post(path: String, token: String, type: String, body: ByteArray): Answered =
        http.post(address, address.resolve(path), type, mapOf(TOKEN_HEADER to token, "Accept" to JSON), body) {
            Answered(it.status, readAtMost(it.body, MAX_JSON))
        }

    /** [send] with [token] (or the one a reload gave in its place); a 403 that says reload, once more with the token
     * of the state read again. */
    private fun posting(token: String, send: (String) -> Answered): Answered {
        val use = renewed[token] ?: token
        val first = send(use)
        if (first.status != 403 || !saysReload(first)) return first
        val fresh = state(asking).token
        renewed[token] = fresh
        renewed[use] = fresh
        return send(fresh)
    }

    private fun saysReload(answer: Answered): Boolean = try {
        ((answer.json() as? JsonObject)?.get("reload") as? JsonPrimitive)?.contentOrNull == "true"
    } catch (e: PeerError) {
        false
    }

    /** peer_sync.Peer._refused: the status, and the computer's own sentence when it gave one. */
    private fun refused(answer: Answered): PeerError {
        val said = try {
            Documents.text((answer.json() as? JsonObject)?.get("error"))
        } catch (e: PeerError) {
            null
        }
        return PeerError("$address answered ${answer.status}" + (said?.let { ": $it" } ?: "."),
                         answer.status)
    }

    companion object {
        const val STATE_PATH = "/api/peer/state"
        const val UNIT_PATH = "/api/peer/unit"
        const val FILE_PATH = "/api/peer/file"
        const val INDEX_PATH = "/api/peer/index"
        const val PUSH_NEW_PATH = "/peer/push/new"
        const val PUSH_FILE_PATH = "/peer/push/file"
        const val PUSH_PATH = "/peer/push"
        const val INDEX_PUSH_PATH = "/peer/index"
        const val JOBS_PATH = "/api/jobs/"
        const val TOKEN_HEADER = "X-Caracole-Form-Token"

        /** peer_sync.PEER_TIMEOUT: a caracole reads every song of its library to answer its state. */
        const val STATE_TIMEOUT_MS = 60_000

        /** The index's export, at most between two reads: the computer makes it whole before it sends a byte. */
        const val INDEX_TIMEOUT_MS = 10 * 60_000

        /** A JSON answer read at most (a state of every unit is a few megabytes). */
        const val MAX_JSON = 64 * 1024 * 1024

        /** A kept file read at most: peer_push.FILE_MAX, what a push may send of one. */
        const val MAX_FILE = 64 * 1024 * 1024

        /** An index export sent at most: peer_push.INDEX_MAX, POST /peer/index's limit. */
        const val INDEX_MAX = 64L * 1024 * 1024
        private const val MIB = 1024L * 1024

        private const val JSON = "application/json"
        private const val OCTETS = "application/octet-stream"
        private val PUSH_ID = Regex("[0-9a-f]{16}")

        /** The whole of [input] if it holds at most [limit] bytes, else null. */
        private fun readAtMost(input: InputStream, limit: Int): ByteArray? {
            val out = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val n = input.read(buffer)
                if (n < 0) return out.toByteArray()
                total += n
                if (total > limit) return null
                out.write(buffer, 0, n)
            }
        }
    }
}
