package io.github.danielhp95.caracole.core.testing.sync

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.Applied
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.UnitSource
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.URLDecoder
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors

/**
 * The computer, for the phone's sync tests (:core's and :server's): caracole serve's peer routes on 127.0.0.1 over a
 * library of its own, [database] and [libraryDir] (caracole's schema, made by [Database] as the phone's is, so its
 * units are those caracole's peer_sync gives a library of the same rows: lane sync-units holds the two to the vectors),
 * answering with the documents Python's routes answer (web/peer_routes.py, peer_push.py; the plan's §5.3):
 *
 * - `GET /api/peer/state?peer=`: its id, version, [name], clock ([now]), [indexes], units in peer_sync._order, the base
 *   it agreed on with the phone that asks, and the form token ([token]).
 * - `GET /api/peer/unit?id=` and `GET /api/peer/file?song=&name=`: a unit's document, a kept file's bytes (404 else).
 * - `POST /peer/push/new`, `/peer/push/file`, `/peer/push`: each with the token in its header, else 403 with
 *   `reload`; a push's files staged in memory, checked by their SHA-256; the push document checked (each digest its
 *   document's) and taken as `caracole peer take` takes it: Take.applyUnits from what was staged, each unit left that
 *   changed here since the comparison, then the agreement at the push's `at`. Its request ([takeFails]: failed
 *   instead, saying why) answers "running" to [runningPolls] polls of `GET /api/jobs/<id>` first.
 * - `GET /api/peer/index?sites=`: [index]'s bytes for the sites asked, recorded in [indexAsked].
 *
 * [answers] replaces what a route answers ("GET /api/peer/state" → a handler); [requests] records each request as
 * "METHOD path?query"; [onUnit] and [onPoll] run before a unit or a poll is answered (a test changes the library
 * there, or looks at the phone's lock). A failure in a route is a 500, kept in [errors].
 */
class FakeComputer(dir: File, val name: String = "Desk") : AutoCloseable {
    val database: Database = Database(File(dir, "caracole.sqlite"))
    val libraryDir: File = File(dir, "library").apply { mkdirs() }
    val store = LibraryStore(libraryDir)

    @Volatile var token: String = "computer-token-1"
    @Volatile var now: String = "2026-11-03T12:00:00Z"
    @Volatile var indexes: Map<String, String> = emptyMap()
    @Volatile var index: (List<String>?) -> ByteArray = { ByteArray(0) }
    @Volatile var takeFails: String? = null
    @Volatile var runningPolls: Int = 0
    @Volatile var onUnit: ((String) -> Unit)? = null
    @Volatile var onPoll: ((Int) -> Unit)? = null

    val requests = CopyOnWriteArrayList<String>()
    val answers = ConcurrentHashMap<String, (HttpExchange) -> Unit>()
    val errors = CopyOnWriteArrayList<Throwable>()
    val pushes = CopyOnWriteArrayList<JsonObject>()
    val taken = CopyOnWriteArrayList<Applied>()
    val indexAsked = CopyOnWriteArrayList<List<String>?>()

    private val random = SecureRandom()
    private val open = ConcurrentHashMap<String, Push>()
    private val jobs = ConcurrentHashMap<Int, Job>()
    private var nextJob = 1
    private val executor = Executors.newFixedThreadPool(4) { r -> Thread(r, "fake-computer").apply { isDaemon = true } }
    private val server = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)

    private class Push(val from: String, val need: Set<String>) {
        val staged = ConcurrentHashMap<String, ByteArray>()
    }

    private class Job(val id: Int, val state: String, val detail: String) {
        @Volatile var polls = 0
    }

    init {
        server.executor = executor
        server.createContext("/") { exchange ->
            try {
                val path = exchange.requestURI.rawPath
                val raw = path + (exchange.requestURI.rawQuery?.let { "?$it" } ?: "")
                requests.add("${exchange.requestMethod} $raw")
                val replaced = answers["${exchange.requestMethod} $path"]
                if (replaced != null) replaced(exchange) else route(exchange, exchange.requestMethod, path)
            } catch (e: Throwable) {
                errors.add(e)
                runCatching { json(exchange, 500, obj("error" to JsonPrimitive("${e.javaClass.simpleName}: ${e.message}"))) }
            } finally {
                exchange.close()
            }
        }
        server.start()
    }

    val address: ServerAddress get() = ServerAddress.parse("127.0.0.1:${server.address.port}")

    /** Its caracole's id: kv sync:id. */
    val id: String get() = database.read { Compare.ownId(it) }

    /** Its units now, as its state lists them. */
    fun state(): Map<String, SyncUnit> = database.read { Units.libraryState(it) }

    /** A fixture of the corpus (vectors/sync/fixtures/<name>.jsonl, say) loaded into its library. */
    fun load(fixture: String) = database.writeBlocking { Fixtures.load(it, fixture, libraryDir) }

    /** The requests made to [path] (no query), in order. */
    fun asked(method: String, path: String): List<String> =
        requests.filter { it == "$method $path" || it.startsWith("$method $path?") }

    private val closed = java.util.concurrent.atomic.AtomicBoolean(false)

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        server.stop(0)
        executor.shutdownNow()
        database.close()
    }

    // --- the routes -----------------------------------------------------------------------------------------------

    private fun route(exchange: HttpExchange, method: String, path: String) {
        val query = query(exchange.requestURI.rawQuery)
        when ("$method $path") {
            "GET /api/peer/state" -> json(exchange, 200, stateDocument(query["peer"]))
            "GET /api/peer/unit" -> unit(exchange, query["id"].orEmpty())
            "GET /api/peer/file" -> file(exchange, query["song"].orEmpty(), query["name"].orEmpty())
            "GET /api/peer/index" -> index(exchange, query["sites"])
            "POST /peer/push/new" -> if (tokenOk(exchange)) pushNew(exchange)
            "POST /peer/push/file" -> if (tokenOk(exchange)) pushFile(exchange, query["push"].orEmpty(), query["sha256"].orEmpty())
            "POST /peer/push" -> if (tokenOk(exchange)) push(exchange, query["push"].orEmpty())
            else -> if (method == "GET" && path.startsWith("/api/jobs/")) job(exchange, path.removePrefix("/api/jobs/"))
                    else json(exchange, 404, obj("error" to JsonPrimitive("no such route")))
        }
    }

    /** peer_sync.state_document, with the form token. */
    fun stateDocument(peer: String?): JsonObject {
        val (units, base) = database.read { db -> Units.libraryState(db) to peer?.let { Compare.baseOf(db, it) } }
        return JsonObject(linkedMapOf(
            "format" to JsonPrimitive(Units.FORMAT),
            "server" to JsonPrimitive(id),
            "caracole" to JsonPrimitive("0.1.0"),
            "name" to JsonPrimitive(name),
            "now" to JsonPrimitive(now),
            "indexes" to JsonObject(indexes.toSortedMap(Py.CODE_POINT_ORDER).mapValues { JsonPrimitive(it.value) }),
            "units" to JsonObject(ordered(units.values).associate { u ->
                u.id to obj("label" to JsonPrimitive(u.label), "digest" to JsonPrimitive(u.digest))
            }),
            "base" to (base?.let { b ->
                JsonObject(b.toSortedMap(Py.CODE_POINT_ORDER).mapValues { (_, entry) ->
                    JsonArray(listOf(entry.first?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(entry.second)))
                })
            } ?: JsonNull),
            "token" to JsonPrimitive(token),
        ))
    }

    private fun unit(exchange: HttpExchange, unitId: String) {
        onUnit?.invoke(unitId)
        val doc = database.read { db ->
            val value = Units.value(db, unitId) ?: return@read null
            val unit = Units.document(db, libraryDir, unitId) ?: return@read null
            obj("format" to JsonPrimitive(Units.FORMAT), "id" to JsonPrimitive(unitId),
                "digest" to JsonPrimitive(Canonical.digest(value)), "unit" to unit)
        }
        if (doc == null) json(exchange, 404, obj("error" to JsonPrimitive("no unit '${unitId.take(200)}' here")))
        else json(exchange, 200, doc)
    }

    private fun file(exchange: HttpExchange, key: String, fileName: String) {
        val bytes = database.read { db ->
            db.one("SELECT f.path, f.sha256 FROM files f JOIN songs s ON s.id = f.song_id WHERE s.key = ? AND f.name = ?",
                   key, fileName) { it.text(0) to it.text(1) }
        }?.let { (path, sha) -> File(libraryDir, path!!).takeIf { it.isFile }?.readBytes()?.takeIf { Canonical.sha256Hex(it) == sha } }
        if (bytes == null) {
            json(exchange, 404, obj("error" to JsonPrimitive("no such file kept, or it changed since caracole kept it")))
        } else {
            send(exchange, 200, bytes, "application/octet-stream")
        }
    }

    private fun index(exchange: HttpExchange, sites: String?) {
        val asked = sites?.split(',')?.map { Py.strip(it) }?.filter { it.isNotEmpty() }
        indexAsked.add(asked)
        send(exchange, 200, index(asked), "application/vnd.sqlite3")
    }

    private fun tokenOk(exchange: HttpExchange): Boolean {
        if (exchange.requestHeaders.getFirst("X-Caracole-Form-Token") == token) return true
        json(exchange, 403, obj("error" to JsonPrimitive("This is older than the server, or not from it: read its " +
                                                        "form token again and try again."),
                                "reload" to JsonPrimitive(true)))
        return false
    }

    private fun pushNew(exchange: HttpExchange) {
        val doc = Canonical.parse(exchange.requestBody.readBytes().toString(Charsets.UTF_8)) as JsonObject
        val from = text(doc["from"])
        if (doc["format"]?.toString() != Units.FORMAT.toString() || from == null || !ID.matches(from)) {
            return json(exchange, 400, obj("error" to JsonPrimitive("That isn't a push of format ${Units.FORMAT}.")))
        }
        val files = (doc["files"] as JsonArray).map { text(it)!! }.distinct()
        val need = files.filter { kept(it) == null }
        val push = hex(8)
        open[push] = Push(from, need.toSet())
        json(exchange, 200, obj("push" to JsonPrimitive(push), "need" to JsonArray(need.map(::JsonPrimitive))))
    }

    private fun pushFile(exchange: HttpExchange, pushId: String, sha256: String) {
        val push = open[pushId]
        val bytes = exchange.requestBody.readBytes()
        when {
            push == null -> json(exchange, 400, obj("error" to JsonPrimitive("Which push? Its id is 16 hex.")))
            sha256 !in push.need -> json(exchange, 400, obj("error" to JsonPrimitive("That file isn't one the push needs.")))
            Canonical.sha256Hex(bytes) != sha256 -> json(exchange, 400, obj("error" to JsonPrimitive("Its bytes aren't its SHA-256's.")))
            else -> {
                push.staged[sha256] = bytes
                json(exchange, 200, obj("ok" to JsonPrimitive(true)))
            }
        }
    }

    private fun push(exchange: HttpExchange, pushId: String) {
        val push = open.remove(pushId)
            ?: return json(exchange, 400, obj("error" to JsonPrimitive("Which push? Its id is 16 hex.")))
        val doc = Canonical.parse(exchange.requestBody.readBytes().toString(Charsets.UTF_8)) as JsonObject
        pushes.add(doc)
        val from = text(doc["from"])!!
        val at = text(doc["at"])!!
        val units = (doc["units"] as JsonObject).mapValues { (id, u) ->
            SyncUnit(id, text((u as JsonObject)["label"])!!, text(u["digest"])!!)
        }
        val take = (doc["take"] as JsonArray).map { it as JsonObject }
        for (entry in take) {
            val unitId = text(entry["id"])!!
            val unit = entry["unit"] as? JsonObject
            val digest = text(entry["digest"])
            val own = unit?.let { Units.valueOfDocument(unitId, it) }?.let(Canonical::digest)
            if (from == id || digest != own || digest != units[unitId]?.digest) {
                return json(exchange, 400, obj("error" to JsonPrimitive("$unitId: given other than its state says.")))
            }
        }
        val failing = takeFails
        val job = synchronized(jobs) {
            val n = nextJob++
            val job = if (failing != null) {
                Job(n, "failed", failing)
            } else {
                val source = Staged(take.associate { text(it["id"])!! to (it["unit"] as? JsonObject) }, push.staged)
                val applied = database.writeBlocking { db ->
                    Take.applyUnits(db, store, source, take.map { text(it["id"])!! to text(it["digest"]) },
                                    take.associate { text(it["id"])!! to text(it["expected"]) }, now)
                }
                taken.add(applied)
                database.writeBlocking { db -> Compare.recordAgreement(db, from, Units.libraryState(db), units, at) }
                Job(n, "done", "")
            }
            jobs[n] = job
            job
        }
        json(exchange, 200, obj("job" to view(job, "queued")))
    }

    private fun job(exchange: HttpExchange, number: String) {
        val job = number.toIntOrNull()?.let { jobs[it] }
            ?: return json(exchange, 404, obj("error" to JsonPrimitive("no such request")))
        onPoll?.invoke(job.id)
        job.polls++
        json(exchange, 200, view(job, if (job.polls <= runningPolls) "running" else job.state))
    }

    /** A request as Job.as_json gives it, its steps those of `caracole peer take`. */
    private fun view(job: Job, state: String): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(job.id), "title" to JsonPrimitive("Changes from the phone"),
        "display" to JsonPrimitive("Changes from Phone"), "state" to JsonPrimitive(state),
        "active" to JsonPrimitive(state == "queued" || state == "running"), "note" to JsonPrimitive(""),
        "queued_at" to JsonPrimitive(now), "started_at" to JsonNull, "finished_at" to JsonNull,
        "steps" to JsonArray(listOf("check", "take", "render", "agree").map { step ->
            val stepState = when (state) {
                "done" -> "done"
                "failed" -> if (step == "take") "failed" else if (step == "check") "done" else "skipped"
                else -> "waiting"
            }
            obj("name" to JsonPrimitive(step), "label" to JsonPrimitive(step),
                "state" to JsonPrimitive(stepState),
                "detail" to JsonPrimitive(if (stepState == "failed") job.detail else ""))
        }),
        "commands" to JsonArray(emptyList()), "song" to JsonNull, "files" to JsonObject(emptyMap()),
        "seconds_to_sheet" to JsonNull,
    ))

    /** A push's units and files, as `caracole peer take` reads them (peer_push.StagedSource). */
    private inner class Staged(private val units: Map<String, JsonObject?>, private val staged: Map<String, ByteArray>) :
        UnitSource {
        override fun unit(id: String): JsonObject? = units[id]
        override fun file(songKey: String, name: String, sha256: String): ByteArray =
            staged[sha256] ?: kept(sha256) ?: error("$name ($sha256) was neither sent nor kept here")
    }

    /** A kept file here whose bytes have [sha256] (peer_push.kept_copy). */
    private fun kept(sha256: String): ByteArray? = database.read { db ->
        db.query("SELECT path FROM files WHERE sha256 = ?", sha256) { it.text(0) }
    }.firstNotNullOfOrNull { path ->
        File(libraryDir, path!!).takeIf { it.isFile }?.readBytes()?.takeIf { Canonical.sha256Hex(it) == sha256 }
    }

    // --- helpers ------------------------------------------------------------------------------------------------

    private fun ordered(units: Collection<SyncUnit>): List<SyncUnit> = units.sortedWith(
        compareBy<SyncUnit> { KINDS.indexOf(it.kind).let { i -> if (i < 0) KINDS.size else i } }
            .thenBy(Py.CODE_POINT_ORDER) { PyUnicode.casefold(it.label) }
            .thenBy(Py.CODE_POINT_ORDER) { it.id },
    )

    private fun hex(bytes: Int) = ByteArray(bytes).also(random::nextBytes).joinToString("") { "%02x".format(it) }

    companion object {
        private val KINDS = listOf("song", "removed", "songbook", "alias", "artist_url", "block")
        private val ID = Regex("[0-9a-f]{16}")

        fun obj(vararg members: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*members))

        fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** JSON as caracole serve answers it: compact, ensure_ascii=False. */
        fun json(exchange: HttpExchange, status: Int, data: JsonElement) =
            send(exchange, status, PyJson.dumps(data, compact = true).toByteArray(), "application/json; charset=utf-8")

        fun send(exchange: HttpExchange, status: Int, body: ByteArray, type: String) {
            exchange.responseHeaders.add("Content-Type", type)
            exchange.sendResponseHeaders(status, if (body.isEmpty()) -1 else body.size.toLong())
            if (body.isNotEmpty()) exchange.responseBody.write(body)
        }

        /** A query's fields, each name's first value, percent-decoded as UTF-8. */
        fun query(raw: String?): Map<String, String> {
            if (raw.isNullOrEmpty()) return emptyMap()
            val found = LinkedHashMap<String, String>()
            for (part in raw.split('&')) {
                if (part.isEmpty()) continue
                val name = URLDecoder.decode(part.substringBefore('='), Charsets.UTF_8)
                val value = URLDecoder.decode(part.substringAfter('=', ""), Charsets.UTF_8)
                found.putIfAbsent(name, value)
            }
            return found
        }
    }
}
