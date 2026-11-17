package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.sites.UgLinkCommands
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.UgUrls
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.UgLinkRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.URLEncoder
import java.nio.file.Files
import java.security.MessageDigest
import java.time.Instant
import java.util.zip.GZIPOutputStream

/**
 * A UG link pasted into the library page's search box, on the phone (tests/test_conformance_ug_link.py's docstring
 * has the shapes), area `ug-link`:
 *
 * - vectors/web/ug_link.jsonl: `read_link` over every shape (UgUrls.readLink); then each scene's fixture loaded into a
 *   database of its own, its UG answers into the phone's HTTP cache, and each `GET /api/ug/link` and `POST /ug/link`
 *   asked of the phone's UgLinkRoutes at the vectors' time over it, the post to a fresh queue that runs nothing: its
 *   answer (status and JSON) or its refusal, and the job it queued (title, key, commands, display, stages);
 * - vectors/lookup/commands_ug_link.jsonl: `caracole ug --link`, UgLinkCommands through lane lookup's InteractiveAsk
 *   over each scenario record's client, at the lookup's run, each request with caracole's own user agent: its lines
 *   (its progress lines with `--progress`), the rows, kv and events it left. The phone notes each artist page it
 *   stores for the next push (kv `phone:read:ug:<page>`), which Python doesn't: checked against the record's
 *   `noted`, then left out of the kv compared.
 */
object UgLinkReplay : AreaReplay {
    override val area = "ug-link"
    const val WEB = "web/ug_link.jsonl"
    const val COMMANDS = "lookup/commands_ug_link.jsonl"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    override fun replay(misses: Misses) {
        links(misses)
        routes(misses)
        commands(misses)
    }

    private fun records(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    private fun text(e: JsonElement?): String = e!!.jsonPrimitive.content

    // --- the links ----------------------------------------------------------------------------------------------------

    /** `read_link` over every shape of helpers/ug_links.py. */
    fun links(misses: Misses) {
        val shapes = records(WEB).filter { it["fn"] == JsonPrimitive("caracole.ug_urls.read_link") }
        misses.check(shapes.size > 50) { "ug_link.jsonl holds ${shapes.size} shapes" }
        for (r in shapes) {
            val asked = text(r.getValue("args").jsonArray[0])
            val got: JsonElement = UgUrls.readLink(asked)?.let {
                JsonObject(linkedMapOf("kind" to JsonPrimitive(it.kind), "url" to JsonPrimitive(it.url),
                                       "tab_id" to (it.tabId?.let(::JsonPrimitive) ?: JsonNull),
                                       "type" to (it.type?.let(::JsonPrimitive) ?: JsonNull)))
            } ?: JsonNull
            misses.check(got == (r["out"] ?: JsonNull)) { "read_link(${PyJson.dumps(JsonPrimitive(asked))}) = $got, Python's ${r["out"]}" }
        }
    }

    // --- the routes ---------------------------------------------------------------------------------------------------

    /** Each scene loaded, then each record over it asked of the phone's routes. */
    fun routes(misses: Misses) {
        val all = records(WEB).filter { it["fn"] != JsonPrimitive("caracole.ug_urls.read_link") }
        var at = 0
        while (at < all.size) {
            val fixture = all[at]
            check(fixture["fn"] == JsonPrimitive("fixture")) { "a record before its scene's fixture: ${fixture["fn"]}" }
            val scene = text(fixture["scene"])
            val asked = all.drop(at + 1).takeWhile { it["fn"] != JsonPrimitive("fixture") }
            at += 1 + asked.size
            inFolder("caracole-ug-link") { dir ->
                TestDb.fresh(dir).use { database ->
                    val library = File(dir, "library").apply { mkdirs() }
                    val state = File(dir, "state").apply { mkdirs() }
                    database.writeBlocking { db ->
                        Fixtures.loadRecords(db, fixture.getValue("records").jsonArray.map { it.jsonObject }, library,
                                             scene)
                        keptFiles(db, library)
                    }
                    seedCache(File(state, "cache"), fixture.getValue("cache").jsonObject)
                    for (r in asked) {
                        misses.check(text(r["scene"]) == scene) { "${r["case"]}: of scene ${r["scene"]}, under $scene" }
                        request(misses, database, dir, r)
                    }
                }
            }
        }
    }

    /** One record's request, asked of the phone's route at the vectors' time, its answer compared. */
    private fun request(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val fn = text(r["fn"])
        val case = "$fn ${text(r["scene"])}: ${text(r["case"])}"
        val now = Instant.parse(NOW)
        val queue = JobQueue(NOWHERE)
        val routes = UgLinkRoutes(parts(database, dir, queue)) { now }
        val (method, path) = fn.split(' ', limit = 2)
        val route: Route = routes.routes.firstOrNull { it.method == method && it.path == path }
            ?: return misses.check(false) { "$case: no route of the phone's" }
        val url = text(r["url"])
        val out = r.getValue("out").jsonObject
        val answer: Response = try {
            if (method == "GET") {
                route.get!!.answer(TestApp.request("GET", "$path?url=${URLEncoder.encode(url, Charsets.UTF_8)}",
                                                   mapOf("accept" to "application/json"), ByteArray(0), TestApp.SECRET))
            } else {
                route.post!!.answer(TestApp.request("POST", path, mapOf("accept" to "application/json"), ByteArray(0),
                                                    TestApp.SECRET), mapOf("csrf" to "tok", "url" to url))
            }
        } catch (e: Refused) {
            val got = JsonObject(linkedMapOf("message" to JsonPrimitive(e.message), "status" to JsonPrimitive(e.status),
                                             "title" to JsonPrimitive(e.title)))
            misses.check("body" !in out && got == out) { "$case: refused $got, caracole serve's $out" }
            return
        }
        if ("body" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.content.toInt()) {
            "$case: status ${answer.status}, caracole serve's ${out["status"]}"
        }
        val body = Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8))
        WebJson.difference(out.getValue("body"), body)?.let { misses.check(false) { "$case: its answer at $it" } }
        val python = out["job"] as? JsonObject ?: return misses.check(queue.snapshot().isEmpty()) { "$case: a job queued" }
        val jobs = queue.snapshot()
        if (jobs.size != 1) return misses.check(false) { "$case: ${jobs.size} jobs queued" }
        val job = jobs.single()
        val phone = JsonObject(linkedMapOf(
            "display" to JsonPrimitive(job.display), "key" to JsonPrimitive(job.key),
            "stages" to JsonArray(job.stages.map { JsonArray(listOf(JsonPrimitive(it.name), JsonPrimitive(it.label))) }),
            "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
            "title" to JsonPrimitive(job.spec.title),
        ))
        WebJson.difference(python, phone)?.let { misses.check(false) { "$case: its job at $it: $phone" } }
    }

    /** The phone's parts over [database]: the library and state under [dir], its settings the database's, its cards
     * the phone's own (PhonePageData), sites that refuse every request. */
    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state")
        val store = LibraryStore(File(dir, "library"))
        val config = { database.read { PhoneConfig.read(it) } }
        return PhoneParts(database, store, state, config, queue, PhonePageData(MirrorPageData(null), store),
                          { Clients(config(), File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }

    /** The files a fixture's `files` rows name, made in the library as they were kept (their contents no answer
     * reads: a sheet's link is to a file there). */
    private fun keptFiles(db: Db, library: File) {
        for (path in db.query("SELECT path FROM files ORDER BY id") { it.text(0)!! }) {
            val file = File(library, path)
            if (file.exists()) continue
            file.parentFile.mkdirs()
            file.writeText("")
        }
    }

    /** The record's cache, `{"GET <url>": {status, fetched_at, headers, body}}`, written as http.py writes UG's: the
     * body gzip'd, the meta as json.dumps writes it. */
    private fun seedCache(cacheDir: File, cache: JsonObject) {
        for ((request, e) in cache) {
            val url = request.substringAfter(' ')
            val entry = e.jsonObject
            val key = sha256(url.toByteArray(Charsets.UTF_8))
            val folder = File(File(File(cacheDir, "http"), "ug"), key.substring(0, 2)).apply { mkdirs() }
            File(folder, "$key.body").writeBytes(gzip(Scenarios.body(entry.getValue("body"))))
            val meta = JsonObject(linkedMapOf("url" to JsonPrimitive(url), "status" to entry.getValue("status"),
                                              "headers" to (entry["headers"] ?: JsonObject(emptyMap())),
                                              "fetched_at" to entry.getValue("fetched_at")))
            File(folder, "$key.json").writeBytes(PyJson.dumps(meta).toByteArray(Charsets.UTF_8))
        }
    }

    private fun gzip(data: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(data) }
        return out.toByteArray()
    }

    private fun sha256(data: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(data)
        .joinToString("") { b -> HEX[(b.toInt() shr 4) and 15].toString() + HEX[b.toInt() and 15] }

    private const val HEX = "0123456789abcdef"

    // --- the command --------------------------------------------------------------------------------------------------

    /** `caracole ug --link`, each record a world of its own. */
    fun commands(misses: Misses) {
        val all = records(COMMANDS)
        misses.check(all.size > 10) { "commands_ug_link.jsonl holds ${all.size} records" }
        for (r in all) {
            val now = Instant.parse(text(r["now"]))
            Scenarios.replay(r, misses, eventLog = { db, run -> EventLog(db, run) { now } }) { w ->
                try {
                    run(w, r)
                } finally {
                    checked(misses, r, w)
                }
            }
        }
    }

    private fun run(w: ScenarioWorld, r: JsonObject): JsonArray {
        val kw = r.getValue("kw").jsonObject
        val link = UgUrls.readLink(text(kw["link"])) ?: throw AssertionError("${r["case"]}: no UG link")
        val lines = ArrayList<String>()
        val ask = asking(w)
        val c = object : CommandContext {
            override val db = w.db
            override val asking = ask
            override val now = w.now
            override fun say(line: String) {
                lines += line
            }
        }
        lines += UgLinkCommands.link(c, PhoneConfig.read(w.db), w.cacheDir, { Overrides.read(w.db) }, link,
                                     progress = kw.getValue("progress").jsonPrimitive.boolean)
        return JsonArray(lines.map { JsonPrimitive(it) })
    }

    /** Every request with the record's `agent`, and the pages noted for the next push its `noted`, checked then
     * forgotten. */
    private fun checked(misses: Misses, r: JsonObject, world: ScenarioWorld) {
        val agent = r["agent"]?.let(::text)
        for (request in world.transport.requests) {
            val sent = request.headers.filter { it.first.equals("User-Agent", ignoreCase = true) }.map { it.second }
            misses.check(agent != null && sent == listOf(agent)) {
                "${r["case"]}: ${request.url} sent as $sent, Python's agent $agent"
            }
        }
        val db = world.db
        val notes = db.query("SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key", Reads.READ,
                             Reads.READ.dropLast(1) + ";") { it.text(0)!! to it.text(1)!! }
        val done = (r["out"] ?: r["after"])!!.jsonObject
        val want = (done["noted"] as? JsonObject ?: JsonObject(emptyMap())).mapValues { text(it.value) }.toList()
        misses.check(notes == want) { "${r["case"]}: the phone noted $notes, Python's $want" }
        for ((key, _) in notes) db.kvDelete(key)
    }

    /** A lookup's envelope in a scenario: lane lookup's InteractiveAsk, at the lookup's run and the phone's settings
     * now, its clients the record's own, so that nothing but the record's answers is sent. */
    private fun asking(w: ScenarioWorld): InteractiveAsk {
        val config = PhoneConfig.read(w.db)
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { w.now.epochSecond.toDouble() },
                            monotonic = { 0.0 }, clock = { w.now })
        return InteractiveAsk(Clients(config, w.cacheDir, { RefusingTransport }, pacing), w.db, Pace.lookupRunId(w.now),
                              w.now, config = config, make = { provider, _ -> w.clients.getValue(provider) })
    }

    /** The vectors' time, test_conformance_ug_link.NOW. */
    private const val NOW = "2026-11-17T12:00:00Z"

    private fun inFolder(name: String, body: (File) -> Unit) {
        val dir = Files.createTempDirectory(name).toFile()
        try {
            body(dir)
        } finally {
            dir.deleteRecursively()
        }
    }
}
