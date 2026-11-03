package io.github.danielhp95.caracole.core.testing.sync

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.Applied
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.PeerError
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
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * The computer, for the phone's sync tests (:core's and :server's): caracole serve's peer routes on 127.0.0.1 over a
 * library of its own, [database] and [libraryDir] (caracole's schema, made by [Database] as the phone's is, so its
 * units are those caracole's peer_sync gives a library of the same rows: lane sync-units holds the two to the vectors),
 * answering as Python's routes answer (web/peer_routes.py, peer_push.py; the plan's §5.3), in their words:
 *
 * - `GET /api/peer/state?peer=`: its id, version, [name], clock ([now]), [indexes], units in peer_sync._order, the base
 *   it agreed on with the phone that asks, and the form token ([token]).
 * - `GET /api/peer/unit?id=` and `GET /api/peer/file?song=&name=`: a unit's document, a kept file's bytes (404 else).
 * - `POST /peer/push/new`, `/peer/push/file`, `/peer/push`: each with the token in its header, else 403 with
 *   `reload`; each checked as peer_push.py checks it (read_new, new_push: at most [OPEN] pushes here, open or sent
 *   and not taken yet, 409 else; stage_file; read_push_document, check_digests and send: each file a song document
 *   keeps staged or kept here, 400 else), each refusal `{error}` with its status. The push's take is queued as
 *   `caracole peer take` is, under `peer-push:<from>` (a take of that caracole's that waits or runs refuses the push,
 *   409 "Taking already", which leaves it open), and runs after the answer on the fake's one worker: its stages check,
 *   take, render, agree (jobs.PEER_TAKE_STAGES), each unit taken or left said as its `units` (Job.as_json), the take
 *   Take.applyUnits from what was staged (a unit changed here since the comparison left), then the agreement at the
 *   push's `at`; the push gone once its take is over. [takeFails]: the take fails instead, its stage saying so, the
 *   request "failed". [holdTakes]: each take waits for it to count down first.
 * - `GET /api/jobs/<id>`: the request as Job.as_json gives it; it answers "running" to [runningPolls] polls first,
 *   then (without [holdTakes]) as it is once over.
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
    @Volatile var holdTakes: CountDownLatch? = null
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
    private val lock = Any()
    private val open = LinkedHashMap<String, Push>()  // the pushes here, open or sent and not taken yet
    private val jobs = LinkedHashMap<Int, Job>()
    private var nextJob = 1
    private val executor = Executors.newFixedThreadPool(4) { r -> Thread(r, "fake-computer").apply { isDaemon = true } }
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "fake-computer-jobs").apply { isDaemon = true } }
    private val server = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)

    /** A push here (peer_push's folder): who opened it, the files it named and needed, those staged, once sent its
     * document. */
    private class Push(val from: String, val need: List<String>) {
        val staged = ConcurrentHashMap<String, ByteArray>()
        @Volatile var sent: JsonObject? = null
    }

    /** A request of caracole serve's queue: a push's take. */
    private inner class Job(val id: Int, val key: String, val title: String, val count: Int) {
        @Volatile var state = "queued"
        val stages = linkedMapOf("check" to Stage("What changed since the comparison"),
                                 "take" to Stage("Taking what changed there"),
                                 "render" to Stage("Rendering what was taken"),
                                 "agree" to Stage("What the two agree on"))
        val units = CopyOnWriteArrayList<Triple<String, String, String>>()
        val over = CountDownLatch(1)
        @Volatile var polls = 0
        val queuedAt: String = STAMP.format(Instant.now())

        val active: Boolean get() = state == "queued" || state == "running"

        /** Job.as_json, its steps its stages and its command the take. */
        fun asJson(shownState: String = state): JsonObject = JsonObject(linkedMapOf(
            "id" to JsonPrimitive(id), "title" to JsonPrimitive(title), "display" to JsonPrimitive(title),
            "state" to JsonPrimitive(shownState),
            "active" to JsonPrimitive(shownState == "queued" || shownState == "running"), "note" to JsonPrimitive(""),
            "queued_at" to JsonPrimitive(queuedAt), "started_at" to JsonNull, "finished_at" to JsonNull,
            "steps" to JsonArray(stages.map { (name, stage) ->
                obj("name" to JsonPrimitive(name), "label" to JsonPrimitive(stage.label),
                    "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail))
            }),
            "commands" to JsonArray(listOf(obj(
                "label" to JsonPrimitive("Taking $count ${if (count == 1) "change" else "changes"}"),
                "args" to JsonArray(listOf("peer", "take", "--progress", "--", "push").map(::JsonPrimitive)),
                "state" to JsonPrimitive(shownState), "code" to JsonNull,
            ))),
            "song" to JsonNull, "files" to JsonObject(emptyMap()), "seconds_to_sheet" to JsonNull,
            "units" to JsonArray(units.map { (id, outcome, why) ->
                JsonArray(listOf(JsonPrimitive(id), JsonPrimitive(outcome), JsonPrimitive(why)))
            }),
        ))
    }

    private class Stage(val label: String) {
        @Volatile var state = "waiting"
        @Volatile var detail = ""
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
            } catch (e: Refusal) {
                json(exchange, e.status, obj("error" to JsonPrimitive(e.message!!)))
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

    /** How many pushes are here, open or sent and not taken yet (peer_push._pushes). */
    val pushesHere: Int get() = synchronized(lock) { open.size }

    /** Once every take queued is over (10 s at most): what a test waits for after it lets a held take go. */
    fun awaitTakes() {
        for (job in synchronized(lock) { jobs.values.toList() }) job.over.await(10, TimeUnit.SECONDS)
    }

    /** Each request of its queue as `GET /api/jobs/<id>` gives it, oldest first. */
    fun jobs(): List<JsonObject> = synchronized(lock) { jobs.values.toList() }.map { it.asJson() }

    private val closed = java.util.concurrent.atomic.AtomicBoolean(false)

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        server.stop(0)
        holdTakes?.let { latch -> repeat(latch.count.toInt()) { latch.countDown() } }
        executor.shutdownNow()
        worker.shutdownNow()
        worker.awaitTermination(10, TimeUnit.SECONDS)
        database.close()
    }

    // --- the routes -----------------------------------------------------------------------------------------------

    /** A route's refusal: its status and its words, answered `{error}` (peer_push.PushError, pages.Refused). */
    private class Refusal(val status: Int, message: String) : Exception(message)

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

    private fun body(exchange: HttpExchange): JsonElement = try {
        Canonical.parse(exchange.requestBody.readBytes().toString(Charsets.UTF_8))
    } catch (e: CanonicalError) {
        throw Refusal(400, "That isn't JSON.")
    }

    /** peer_push.read_new, needed and new_push. */
    private fun pushNew(exchange: HttpExchange) {
        val doc = body(exchange) as? JsonObject
        if (doc == null || doc["format"] != JsonPrimitive(Units.FORMAT)) {
            throw Refusal(400, "That isn't a push of format ${Units.FORMAT} (the other caracole may be of another version).")
        }
        val from = text(doc["from"])
        if (from == null || !ID.matches(from)) throw Refusal(400, "Who pushes? Its caracole's id is 16 hex.")
        val files = (doc["files"] as? JsonArray ?: throw Refusal(400, "Which files? A push lists them, by their SHA-256."))
            .map { checkSha256(text(it)) }.distinct()
        notFromHere(from)
        val need = files.filter { kept(it) == null }
        val push = synchronized(lock) {
            if (open.size >= OPEN) {
                throw Refusal(409, "Two pushes are here already, waiting to be taken: try again once one is, or in an hour.")
            }
            generateSequence { hex(8) }.first { it !in open }.also { open[it] = Push(from, need) }
        }
        json(exchange, 200, obj("push" to JsonPrimitive(push), "need" to JsonArray(need.map(::JsonPrimitive))))
    }

    /** peer_push.stage_file. */
    private fun pushFile(exchange: HttpExchange, pushId: String, sha256: String) {
        checkId(pushId)
        checkSha256(sha256)
        val bytes = exchange.requestBody.readBytes()
        if (Canonical.sha256Hex(bytes) != sha256) throw Refusal(400, "Those bytes aren't the file of that SHA-256.")
        synchronized(lock) {
            val push = open[pushId] ?: throw Refusal(400, "No such push is open here: open another (POST /peer/push/new).")
            if (push.sent != null) throw Refusal(400, "That push is sent already: it takes no more files.")
            if (sha256 !in push.need) {
                throw Refusal(400, "That push doesn't need that file: this side has it, or the push never named it.")
            }
            push.staged.putIfAbsent(sha256, bytes)
        }
        json(exchange, 200, obj("ok" to JsonPrimitive(true)))
    }

    /** peer_routes.push: read_push_document, check_digests and send, then the take queued (peer-push:<from>). */
    private fun push(exchange: HttpExchange, pushId: String) {
        checkId(pushId)
        val doc = body(exchange) as? JsonObject
        val sent = readPushDocument(doc)
        val files = songFiles(sent.take)
        val job = synchronized(lock) {
            notFromHere(sent.from)
            for (entry in sent.take) checkDigest(entry)
            val push = open[pushId] ?: throw Refusal(400, "No such push is open here: open another (POST /peer/push/new).")
            if (push.sent != null) throw Refusal(400, "That push is sent already.")
            if (push.from != sent.from) throw Refusal(400, "That push was opened by another caracole.")
            val missing = files.filter { !push.staged.containsKey(it) && kept(it) == null }.sorted()
            if (missing.isNotEmpty()) {
                val one = missing.size == 1
                throw Refusal(400, "${missing.size} ${if (one) "file" else "files"} the push keeps " +
                                   "${if (one) "was" else "were"} never sent, nor kept here: " +
                                   missing.take(3).joinToString(", ") + (if (missing.size > 3) "…" else "") + ".")
            }
            val shown = "Changes from ${Py.slice(Py.strip(sent.name).ifEmpty { "another caracole" }, null, 120)}"
            val key = PEER_PUSH + sent.from
            val busy = jobs.values.firstOrNull { it.active && it.key == key }
            if (busy != null) {  // the push stays open, to send again once that is over
                throw Refusal(409, "$shown are being taken already (request ${busy.id}): send them again once that is over.")
            }
            push.sent = doc
            pushes.add(doc!!)
            Job(nextJob++, key, shown, sent.take.size).also { jobs[it.id] = it }
        }
        worker.execute { take(job, pushId, sent) }
        json(exchange, 200, obj("job" to job.asJson()))
    }

    /** `caracole peer take`: check, take, render, agree, each unit said as it is taken or left; the push gone after. */
    private fun take(job: Job, pushId: String, sent: Sent) {
        try {
            holdTakes?.await()
            job.state = "running"
            job.stages.getValue("check").apply { state = "done"; detail = "${sent.take.size} changes from ${sent.name}" }
            val fails = takeFails
            if (fails != null) {
                job.stages.getValue("take").apply { state = "failed"; detail = fails }
                for (stage in listOf("render", "agree")) job.stages.getValue(stage).state = "skipped"
                job.state = "failed"
                return
            }
            job.stages.getValue("take").state = "running"
            val staged = synchronized(lock) { open[pushId]?.staged?.toMap().orEmpty() }
            val source = Staged(sent.take.associate { it.id to it.unit }, staged)
            val applied = database.writeBlocking { db ->
                Take.applyUnits(db, store, source, sent.take.map { it.id to it.digest },
                                sent.take.associate { it.id to it.expected }, now)
            }
            taken.add(applied)
            for (id in applied.taken) job.units.add(Triple(id, "taken", ""))
            for ((id, why) in applied.left) job.units.add(Triple(id, "left", why))
            job.stages.getValue("take").apply {
                state = "done"
                detail = "took ${applied.taken.size}" + if (applied.left.isEmpty()) "" else ", left ${applied.left.size}"
            }
            job.stages.getValue("render").state = "done"
            val agreed = database.writeBlocking { db ->
                Compare.recordAgreement(db, sent.from, Units.libraryState(db), sent.units, sent.at)
            }
            job.stages.getValue("agree").apply { state = "done"; detail = "$agreed units the two agree on" }
            job.state = "done"
        } catch (e: Throwable) {
            errors.add(e)
            job.stages.values.firstOrNull { it.state == "running" }?.apply { state = "failed"; detail = "${e.message}" }
            job.state = "failed"
        } finally {
            for (stage in job.stages.values) if (stage.state == "waiting") stage.state = "skipped"
            synchronized(lock) { open.remove(pushId) }
            job.over.countDown()
        }
    }

    private fun job(exchange: HttpExchange, number: String) {
        val job = number.toIntOrNull()?.let { synchronized(lock) { jobs[it] } }
            ?: return json(exchange, 404, obj("error" to JsonPrimitive("No such request: it may be older than the " +
                                                                       "history keeps.")))
        onPoll?.invoke(job.id)
        job.polls++
        if (job.polls <= runningPolls) return json(exchange, 200, job.asJson("running"))
        if (holdTakes == null) job.over.await(10, TimeUnit.SECONDS)
        json(exchange, 200, job.asJson())
    }

    // --- a push's document, read as peer_push reads it -----------------------------------------------------------

    private class Entry(val id: String, val expected: String?, val digest: String?, val unit: JsonObject?)

    private class Sent(val from: String, val name: String, val at: String, val units: Map<String, SyncUnit>,
                       val take: List<Entry>)

    /** peer_push.read_push_document. */
    private fun readPushDocument(data: JsonObject?): Sent {
        if (data == null || data["format"] != JsonPrimitive(Units.FORMAT)) {
            throw Refusal(400, "That isn't a push of format ${Units.FORMAT} (the other caracole may be of another version).")
        }
        val from = text(data["from"])
        if (from == null || !ID.matches(from)) throw Refusal(400, "Who pushes? Its caracole's id is 16 hex.")
        val name = text(data["name"])
        val version = text(data["caracole"])
        val at = text(data["at"])
        if (name == null || version == null || at.isNullOrEmpty()) {
            throw Refusal(400, "A push says its library's name, its caracole's version and when it compared.")
        }
        if (!STAMP_SHAPE.matches(at)) {
            throw Refusal(400, "'${at.take(80)}' isn't a time: a push says when it compared as this side's state said it.")
        }
        val units = (data["units"] as? JsonObject ?: throw Refusal(400, "Its state can't be read: a sync state with " +
                                                                         "no units, or a server id that can't be read."))
            .mapValues { (id, u) ->
                val label = text((u as? JsonObject)?.get("label"))
                val digest = text((u as? JsonObject)?.get("digest"))
                if ('/' !in id || label == null || digest == null) {
                    throw Refusal(400, "Its state can't be read: a unit that can't be read: '${id.take(80)}'.")
                }
                SyncUnit(id, label, digest)
            }
        val take = (data["take"] as? JsonArray ?: throw Refusal(400, "What does it give? A push lists its units to take."))
            .map { taken(it, units) }
        if (take.map { it.id }.toSet().size != take.size) throw Refusal(400, "A push gives each unit once.")
        return Sent(from, name, at, units, take)
    }

    /** peer_push._taken. */
    private fun taken(entry: JsonElement, units: Map<String, SyncUnit>): Entry {
        val e = entry as? JsonObject ?: throw Refusal(400, "A unit to take that can't be read.")
        val id = text(e["id"])
        if (id == null || '/' !in id || id.length > 1000) throw Refusal(400, "A unit to take with no id to read.")
        val expected = digestOrNull(e["expected"], id)
        val digest = digestOrNull(e["digest"], id)
        val unit = e["unit"].takeUnless { it == null || it is JsonNull }
        if ((digest == null) != (unit == null) || (unit != null && unit !is JsonObject)) {
            throw Refusal(400, "${id.take(200)}: a document goes with a digest, and none with none.")
        }
        if (digest != units[id]?.digest) throw Refusal(400, "${id.take(200)}: given other than its state says.")
        return Entry(id, expected, digest, unit as JsonObject?)
    }

    private fun digestOrNull(e: JsonElement?, id: String): String? {
        if (e == null || e is JsonNull) return null
        return text(e)?.takeIf { SHA256.matches(it) } ?: throw Refusal(400, "${id.take(200)}: a digest that can't be read.")
    }

    /** peer_push.check_digests: each document is what its digest says. */
    private fun checkDigest(entry: Entry) {
        val unit = entry.unit ?: return
        val found = try {
            Units.valueOfDocument(entry.id, unit)?.let(Canonical::digest)
        } catch (e: Exception) {
            throw Refusal(400, "${entry.id.take(200)}: ${e.message}.")
        }
        if (found != entry.digest) throw Refusal(400, "${entry.id.take(200)}: its document isn't what its digest says.")
    }

    /** Push.files: the SHA-256 of every file a song document of [take] keeps. */
    private fun songFiles(take: List<Entry>): Set<String> {
        val found = LinkedHashSet<String>()
        for (entry in take) {
            val unit = entry.unit ?: continue
            if (entry.id.substringBefore('/') != "song") continue
            val versions = unit["versions"] as? JsonArray ?: throw Refusal(400, "${entry.id.take(200)}: a song with no versions to read.")
            for (version in versions) {
                val files = (version as? JsonObject)?.get("files") as? JsonArray
                if (files == null || files.any { it !is JsonObject }) {
                    throw Refusal(400, "${entry.id.take(200)}: a version whose files can't be read.")
                }
                for (file in files) found.add(checkSha256(text((file as JsonObject)["sha256"])))
            }
        }
        return found
    }

    private fun notFromHere(from: String) {
        if (from == id) {
            throw Refusal(400, "That push comes from this caracole itself (the same id): its database is a copy of " +
                               "this one's. Give one of them another: caracole peer new-id.")
        }
    }

    private fun checkId(push: String) {
        if (!ID.matches(push)) throw Refusal(400, "Which push? Its id is 16 hex.")
    }

    private fun checkSha256(digest: String?): String {
        if (digest == null || !SHA256.matches(digest)) throw Refusal(400, "Which file? Its SHA-256 is 64 hex.")
        return digest
    }

    /** A push's units and files, as `caracole peer take` reads them (peer_push.StagedSource). */
    private inner class Staged(private val units: Map<String, JsonObject?>, private val staged: Map<String, ByteArray>) :
        UnitSource {
        override fun unit(id: String): JsonObject? {
            if (id !in units) throw PeerError("the push doesn't give it")
            return units[id]
        }

        override fun file(songKey: String, name: String, sha256: String): ByteArray =
            staged[sha256] ?: kept(sha256)
                ?: throw PeerError("$name wasn't sent with the push, nor is it kept here as it was: the song is left " +
                                   "as it was here.")
    }

    /** A kept file here whose bytes have [sha256] (peer_push.kept_copy). */
    private fun kept(sha256: String): ByteArray? = database.read { db ->
        db.query("SELECT path FROM files WHERE sha256 = ? ORDER BY id", sha256) { it.text(0) }
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
        /** peer_push.OPEN: pushes here at once, open or sent and not taken yet. */
        const val OPEN = 2

        /** peer_routes.PEER_PUSH: a take's job key, the pushing caracole's id after it. */
        const val PEER_PUSH = "peer-push:"

        private val KINDS = listOf("song", "removed", "songbook", "alias", "artist_url", "block")
        private val ID = Regex("[0-9a-f]{16}")
        private val SHA256 = Regex("[0-9a-f]{64}")
        private val STAMP_SHAPE = Regex("""\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?(Z|[+-]\d{2}:\d{2})?""")
        private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(ZoneOffset.UTC)

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
