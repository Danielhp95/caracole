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

/** /api/peer/state, as the phone reads it: [kept], the answers the computer's imports of the phone's files
 * remembered for it, as it keeps them (`here` the computer's), its odd entries left out; [schema], the schema the
 * computer's database is at (null: it says none, an older caracole's state, or a value that is no integer);
 * [keyVersion], the rules its songs are keyed by as it says them (`key_version`; null: it says none, a computer older
 * than the member). Of the two, [keyVersion] refuses the whole comparison (Units.otherKeys), before the schema's
 * refusal of the indexes alone (SyncEngine.indexesSkipped) is ever reached. */
data class PeerState(val format: Int, val server: String?, val caracole: String, val name: String, val now: String?,
                     val units: Map<String, SyncUnit>, val base: Base?, val token: String,
                     val indexes: Map<String, String> = emptyMap(), val settings: JsonObject? = null,
                     val kept: Kept = emptyMap(), val schema: Long? = null, val keyVersion: JsonElement? = null) {
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

/** A site's index as `GET /api/sync/indexes` counts it: its newest read (null: never) and the tabs it tracks, the
 * rows of its first table (index_transfer.tab_counts). */
data class IndexCount(val read: String?, val tabs: Long)

/** What the computer answered that the phone can't go on with, said as one sentence ([message]); [status], the
 * HTTP status it answered with, when it answered one. Nothing answering at all is mirror's SyncError.NoAnswer. */
open class PeerError(message: String, val status: Int? = null, cause: Throwable? = null) : Exception(message, cause)

/** peer_sync.OtherKeys: the computer keys its songs by other rules than the phone (its state's `key_version`,
 * Units.otherKeys): the two never compare nor take from each other until both are updated to one version, said in
 * Units.OTHER_KEYS. */
class OtherKeys(message: String) : PeerError(message, 200)

/**
 * The computer's peer routes, from the phone (peer_sync.Peer's reads, and the push the phone sends because it serves
 * nothing to the network): one request at a time, through mirror's [Http] (no redirect followed, no cookie).
 *
 * - **Reads** (`Accept: application/json`): [state], with a 60 s read timeout (a library's every song is read to
 *   answer); [unit], its document checked to be of [Units.FORMAT] and of the id asked; [file], its bytes checked against
 *   the SHA-256 the unit gives; [job], the computer's request as `GET /api/jobs/<id>` gives it.
 * - **The push**: [pushNew], [pushFile] and [push] ([pushDrop] once it fails after it is opened), each with the form
 *   token in the header `X-Caracole-Form-Token` (caracole serve's `json` and `bytes` routes) and no Origin or
 *   Sec-Fetch-Site, which a non-browser never sends. A 403 whose JSON says `reload` (a token older than the server:
 *   it restarted since the state was read) reads the state again, once, for its fresh token, and sends the call again
 *   with it; the calls after it that give the old token send the fresh one.
 * - **The index**: [index] streams `GET /api/peer/index` to a file, with a read timeout of [INDEX_TIMEOUT_MS]
 *   between two reads (the file is as large as the computer's indexes, and made before its first byte comes: a
 *   connection that goes quiet for longer is a lost one, so a sync job never waits on it for ever); [indexNewer]
 *   streams the part the phone doesn't hold alike, `POST /peer/index/newer` (a `json` route: the form token), false
 *   for a computer older than it; [pushIndex] streams the pages the phone's lookups read to `POST /peer/index`, a
 *   `bytes` route of the push's kind.
 *
 * Every answer that says no is a [PeerError] in the words peer_sync.Peer says it; a document that can't be read, too.
 */
class PeerClient(val address: ServerAddress, http: Http = Http()) : UnitSource {
    private val http = http
    private var asking: String? = null
    private val renewed = HashMap<String, String>()

    /** GET /api/peer/state, a 60 s read timeout: the computer's state, with its base for [asking] (the phone's id);
     * [OtherKeys] for one whose songs are keyed by other rules than the phone's, so that no comparison, take or push
     * follows it (peer_sync.Peer.state). */
    fun state(asking: String?): PeerState {
        this.asking = asking
        val answer = get(STATE_PATH + (asking?.let { "?peer=" + Documents.quote(it) } ?: ""), STATE_TIMEOUT_MS)
        if (answer.status == 404) {
            throw PeerError("$address answered, but not as a caracole that shares. An older caracole, or " +
                            "something else?", 404)
        }
        if (answer.status != 200) throw refused(answer)
        val state = try {
            Documents.state(answer.json())
        } catch (e: Documents.Unreadable) {
            throw PeerError("$address answered ${e.message}.", 200, e)
        }
        if (Units.otherKeys(state.keyVersion)) throw OtherKeys(Units.OTHER_KEYS)
        return state
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

    /** POST /peer/push/drop: the push [push] there, never sent, let go of, asked as the caracole that opened it
     * ([from]); whether it was (peer_push.Pusher.push_drop). An error, or its refusal (409 once its document was
     * taken), is no more than that: the phone's next push lets go of it there, or it is swept within the hour. */
    fun pushDrop(token: String, push: String, from: String): Boolean = try {
        // Asked once, within [DROP_TIMEOUT_MS] of a read and with the token held (no state read again on a 403): a
        // drop is the last thing a failure or a cancelled job does, and a server that doesn't answer it at once is
        // let be (peer_push.Pusher.push_drop).
        val doc = JsonObject(linkedMapOf("push" to JsonPrimitive(push), "from" to JsonPrimitive(from)))
        val body = PyJson.dumps(doc, compact = true).toByteArray(Charsets.UTF_8)
        http.post(address, address.resolve(PUSH_DROP_PATH), JSON,
                  mapOf(TOKEN_HEADER to (renewed[token] ?: token), "Accept" to JSON), body, DROP_TIMEOUT_MS) {
            it.status
        } == 200
    } catch (e: Exception) {
        false
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
     * most between two reads; [onBytes] told the bytes come so far and the answer's Content-Length (-1: it gives none)
     * once the answer begins (the computer exports the whole index before its first byte), then after each read. */
    fun index(to: File, sites: List<String>? = null, onBytes: ((got: Long, total: Long) -> Unit)? = null) {
        val path = INDEX_PATH + (sites?.let { "?sites=" + Documents.quote(it.joinToString(",")) } ?: "")
        http.get(address, address.resolve(path), emptyMap(), readTimeoutMs = INDEX_TIMEOUT_MS) { answer ->
            if (answer.status != 200) throw refused(Answered(answer.status, readAtMost(answer.body, MAX_JSON)))
            streamTo(answer, to, onBytes)
        }
    }

    /** POST /peer/index/newer: the part of the computer's indexes the phone doesn't hold ([have], its document:
     * core.index.Have), streamed into [to] as [index] streams the whole, with the form token in its header (a 403 that
     * says reload asks once more with a fresh one); false, nothing written, for a computer that doesn't know the route
     * (404 or 405: older than the app) or refuses the document as too large (413), which the caller asks for the whole
     * instead ([WHOLE_INSTEAD]); a [PeerError] for any other refusal, in the computer's words (a 400 a bug, which must
     * show), never taken for an older computer. */
    fun indexNewer(token: String, to: File, have: JsonObject,
                   onBytes: ((got: Long, total: Long) -> Unit)? = null): Boolean {
        val body = PyJson.dumps(have, compact = true).toByteArray(Charsets.UTF_8)
        var use = renewed[token] ?: token
        repeat(2) { asked ->
            val refusal = http.post(address, address.resolve(INDEX_NEWER_PATH), JSON,
                                    mapOf(TOKEN_HEADER to use, "Accept" to JSON), body,
                                    readTimeoutMs = INDEX_TIMEOUT_MS) { answer ->
                if (answer.status == 200) {
                    streamTo(answer, to, onBytes)
                    null
                } else {
                    Answered(answer.status, readAtMost(answer.body, MAX_JSON))
                }
            } ?: return true
            if (refusal.status in WHOLE_INSTEAD) return false
            if (refusal.status != 403 || !saysReload(refusal) || asked > 0) throw refused(refusal)
            val fresh = state(asking).token
            renewed[token] = fresh
            renewed[use] = fresh
            use = fresh
        }
        error("unreachable")
    }

    /** An index answer's bytes into [to] as they come, [onBytes] told the bytes so far and its Content-Length; a write
     * that fails is the phone's storage, never the connection. */
    private fun streamTo(answer: Http.Answer, to: File, onBytes: ((got: Long, total: Long) -> Unit)?) {
        var got = 0L
        onBytes?.invoke(got, answer.contentLength)
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
                got += n
                onBytes?.invoke(got, answer.contentLength)
            }
            out.fd.sync()
        }
    }

    /** GET /api/sync/indexes: each of the computer's site indexes, its newest read and its tabs, by site; a PeerError
     * for a computer that doesn't count them (404: older than the app) or an answer the phone can't read. */
    fun indexes(): Map<String, IndexCount> {
        val answer = get(SYNC_INDEXES_PATH)
        if (answer.status == 404) {
            throw PeerError("The caracole at $address doesn't count its indexes: it may be older than the app.", 404)
        }
        if (answer.status != 200) throw refused(answer)
        val sites = ((answer.json() as? JsonObject)?.get("indexes") as? JsonObject)
            ?: throw PeerError("The caracole at $address answered its indexes with something the phone can't read.", 200)
        return sites.entries.associateTo(LinkedHashMap()) { (site, value) ->
            val counted = value as? JsonObject
            val tabs = (counted?.get("tabs") as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toLongOrNull()
            if (counted == null || tabs == null) {
                throw PeerError("The caracole at $address answered its indexes with something the phone can't read.", 200)
            }
            site to IndexCount(Documents.text(counted["read"]), tabs)
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
            throw PeerError("$address sent $id in a form we can't read.", 200)
        }
        return unit
    }

    /** GET /api/peer/file: a kept file of its song of [songKey], checked against [sha256]. One past [MAX_FILE] is
     * never taken, a [PeerError] in [TOO_BIG]'s words: refused by its Content-Length before a byte of it is read, or,
     * an answer that gives none, once its bytes pass it. An answer whose Content-Length says less than it sends is read
     * no further than it says (HttpURLConnection's), so those bytes aren't the file of that SHA-256: "sent … changed
     * since compared", the song left as it was here. */
    override fun file(songKey: String, name: String, sha256: String): ByteArray {
        val path = FILE_PATH + "?song=" + Documents.quote(songKey) + "&name=" + Documents.quote(name)
        val answer = http.get(address, address.resolve(path)) {
            if (it.status == 200 && it.contentLength > MAX_FILE) Answered(it.status, null)
            else Answered(it.status, readAtMost(it.body, MAX_FILE))
        }
        if (answer.status != 200) throw refused(answer)
        val bytes = answer.bytes ?: throw PeerError("$name $TOO_BIG. The song stays as it was here.", 200)
        if (Canonical.sha256Hex(bytes) != sha256) {
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
        const val PUSH_DROP_PATH = "/peer/push/drop"
        const val INDEX_PUSH_PATH = "/peer/index"
        const val INDEX_NEWER_PATH = "/peer/index/newer"

        /** The statuses of `POST /peer/index/newer` after which the whole export is asked for: a computer older than
         * the route (404, 405) and a document past its limit (413). Any other is the index stage's failure. */
        val WHOLE_INSTEAD = setOf(404, 405, 413)
        const val JOBS_PATH = "/api/jobs/"
        const val SYNC_INDEXES_PATH = "/api/sync/indexes"
        const val TOKEN_HEADER = "X-Caracole-Form-Token"

        /** peer_sync.PEER_TIMEOUT: a caracole reads every song of its library to answer its state. */
        const val STATE_TIMEOUT_MS = 60_000

        /** peer_push.DROP_TIMEOUT: a push's drop waited for at most, in ms. */
        const val DROP_TIMEOUT_MS = 5_000

        /** The index's export, at most between two reads: the computer makes it whole before it sends a byte. */
        const val INDEX_TIMEOUT_MS = 10 * 60_000

        /** A JSON answer read at most (a state of every unit is a few megabytes). */
        const val MAX_JSON = 64 * 1024 * 1024

        /** A kept file read at most: peer_push.FILE_MAX, what a push may send of one (`POST /peer/push/file`'s
         * limit); the phone takes no file past it ([TOO_BIG]) and gives none (FileError.TOO_BIG). */
        const val MAX_FILE = 64 * 1024 * 1024

        /** Why a file past [MAX_FILE] is never taken, after its name. */
        const val TOO_BIG = "is over 64 MiB: the phone takes no file that big"

        /** peer_push.NEW_MAX: `POST /peer/push/new`'s document at most. */
        const val PUSH_NEW_MAX = 1024L * 1024

        /** peer_push.DOCUMENT_MAX: `POST /peer/push`'s document at most. */
        const val PUSH_DOCUMENT_MAX = 16L * 1024 * 1024

        /** peer_push.PUSH_MAX: a push's files' bytes at most. */
        const val PUSH_MAX = 2L * 1024 * 1024 * 1024

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
