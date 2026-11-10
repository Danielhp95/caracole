package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.LookupRoutes
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.testing.PageCards
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
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
import java.time.Instant

/**
 * The library page's lookups on the phone (tests/test_conformance_lookup_routes.py's docstring has the shapes):
 *
 * - vectors/web/lookup_routes.jsonl: each request posted to the phone's route (LookupRoutes', LibraryRoutes' `/request`)
 *   as caracole serve's was, over its library (the vector's fixture, in a database of its own) with the record's kv and
 *   events rows, to a fresh queue that runs nothing ([NOWHERE]; one of no room for a `full` record), LaCuerda's gate at
 *   the record's time: its refusal, `{status, title, message}`, or its answer (status, `Location`, its JSON less the
 *   view) and the job it queued (title, key, commands, fetching, note, display). Where caracole serve wrote wanted.txt
 *   (`wanted`), the phone writes none: its note says nothing then, and a full queue says nothing was added
 *   ([LibraryRoutes.FULL]); caracole serve's `caracole add` is the phone's own add job, a run of no command.
 * - vectors/web/api_search_gate.jsonl: `/api/search`'s `lacuerda_search` and `lacuerda_unlisted` for each query over a
 *   search fixture with the record's rows, LaCuerda's search on, its gate at the record's time (search_routes'
 *   `_found_for`'s: a query too short to look for, answered `short`, has neither, null both).

 */
object LookupRoutesReplay : AreaReplay {
    override val area = "lookup-routes"
    const val ROUTES = "web/lookup_routes.jsonl"
    const val GATE = "web/api_search_gate.jsonl"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    override fun replay(misses: Misses) {
        routes(misses)
        gate(misses)
    }

    // --- the routes -------------------------------------------------------------------------------------------------

    private fun routes(misses: Misses) {
        val lines = Corpus.lines(ROUTES).filter { it["header"] != JsonPrimitive(true) }
        val fixture = lines.first { it["fn"]?.jsonPrimitive?.content == "fixture" }.getValue("records").jsonArray
            .map { it.jsonObject }
        inFolder("lookup-routes") { dir ->
            TestDb.fresh(dir).use { database ->
                val library = File(dir, "library").apply { mkdirs() }
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture, library) }
                val kv = database.read { db -> db.query("SELECT key, value FROM kv") { it.text(0)!! to it.text(1)!! } }
                for (r in lines) {
                    val fn = r["fn"]?.jsonPrimitive?.content ?: continue
                    if (fn == "fixture") continue
                    database.writeBlocking { db ->
                        db.execute("DELETE FROM events")
                        db.execute("DELETE FROM kv")
                        for ((key, value) in kv) db.kvSet(key, value)
                        Fixtures.loadRecords(db, r.getValue("rows").jsonArray.map { it.jsonObject }, library)
                    }
                    request(misses, database, dir, fn, r)
                }
            }
        }
    }

    /** One record's request, posted to the phone's route as the generator posted it, its answer compared. */
    private fun request(misses: Misses, database: Database, dir: File, fn: String, r: JsonObject) {
        val case = "$fn (${r.getValue("case").jsonPrimitive.content}, json ${r["json"]})"
        val full = r.getValue("full").jsonPrimitive.boolean
        val now = Instant.parse(r.getValue("now").jsonPrimitive.content)
        val queue = JobQueue(NOWHERE, limit = if (full) 0 else JobQueue.LIMIT)
        val parts = parts(database, dir, queue)
        val modules = listOf(LookupRoutes(parts) { now }, LibraryRoutes(parts.store, queue, parts.cards, database))
        val path = fn.removePrefix("POST ")
        val route: Route = modules.flatMap { it.routes }.firstOrNull { it.method == "POST" && it.path == path }
            ?: return misses.check(false) { "$case: no route of the phone's" }
        val form = LinkedHashMap<String, String>()
        for (field in r.getValue("form").jsonArray) form[field.jsonArray[0].jsonPrimitive.content] = field.jsonArray[1].jsonPrimitive.content
        val json = r.getValue("json").jsonPrimitive.boolean
        val asked = TestApp.request("POST", path, if (json) mapOf("accept" to "application/json") else emptyMap(),
                                    ByteArray(0), TestApp.SECRET)
        val out = r.getValue("out").jsonObject
        val wanted = (out["wanted"] as? JsonPrimitive)?.boolean == true
        val answer: Response = try {
            route.post!!.answer(asked, form)
        } catch (e: Refused) {
            val said = if (full && wanted) LibraryRoutes.FULL else out["message"]?.jsonPrimitive?.content
            val expected = JsonObject(linkedMapOf("status" to out.getValue("status"), "title" to (out["title"] ?: JsonNull),
                                                  "message" to JsonPrimitive(said)))
            val got = JsonObject(linkedMapOf("status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title),
                                             "message" to JsonPrimitive(e.message)))
            misses.check("job" !in out && expected == got) { "$case: refused $got, caracole serve's $out" }
            return
        }
        if ("job" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.content.toInt()) {
            "$case: status ${answer.status}, caracole serve's ${out["status"]}"
        }
        val location = answer.header("location")
        misses.check(JsonPrimitive(location) == out["location"] || (location == null && out["location"] == JsonNull)) {
            "$case: Location $location, caracole serve's ${out["location"]}"
        }
        val body = answer.bytes.takeIf { it.isNotEmpty() }?.let { bytes ->
            (Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)) as? JsonObject)?.let { JsonObject(it - "view") }
        } ?: JsonNull
        WebJson.difference(out.getValue("body"), body)?.let { misses.check(false) { "$case: its answer at $it" } }
        val jobs = queue.snapshot()
        if (jobs.size != 1) return misses.check(false) { "$case: ${jobs.size} jobs queued" }
        val job = jobs.single()
        val python = out.getValue("job").jsonObject
        val steps = python.getValue("steps").jsonArray
        val adds = steps.size == 1 && steps[0].jsonArray[1].jsonArray[0].jsonPrimitive.content == "add"
        val commands = if (adds) {
            // caracole serve's `caracole add` is the phone's own add: a run under the same title, of no command
            misses.check(job.spec.kind == "add" && job.spec.run != null && job.stages.map { it.label } ==
                             listOf(steps[0].jsonArray[0].jsonPrimitive.content)) {
                "$case: the phone's add job, not ${job.spec.kind} ${job.stages.map { it.label }}"
            }
            steps
        } else {
            JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) })
        }
        val phone = JsonObject(linkedMapOf(
            "title" to JsonPrimitive(job.spec.title), "key" to JsonPrimitive(job.key), "steps" to commands,
            "fetching" to JsonPrimitive(job.fetching), "note" to JsonPrimitive(job.spec.note),
            "display" to JsonPrimitive(job.display),
        ))
        // the phone writes no wanted.txt: no line to name
        val expected = if (wanted) JsonObject(python + ("note" to JsonPrimitive(""))) else python
        WebJson.difference(expected, phone)?.let { misses.check(false) { "$case: its job at $it: $phone" } }
    }

    /** The parts of a phone over [database], LaCuerda's search on, as caracole serve's generator had it. */
    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                          MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = true)
    }

    // --- /api/search's gate -----------------------------------------------------------------------------------------

    private fun gate(misses: Misses) {
        val records = Corpus.records(GATE)
        val groups = records.groupBy { r -> Triple(r.extra.getValue("fixture"), r.extra.getValue("case"), r.extra.getValue("rows")) }
        for ((group, asked) in groups) {
            val (fixture, case, rows) = group
            inFolder("api-search-gate") { dir ->
                TestDb.fresh(dir).use { database ->
                    database.writeBlocking { db ->
                        Fixtures.load(db, "search/fixtures/${fixture.jsonPrimitive.content}.jsonl")
                        Fixtures.loadRecords(db, rows.jsonArray.map { it.jsonObject })
                    }
                    for (r in asked) {
                        val now = Instant.parse(r.extra.getValue("now").jsonPrimitive.content)
                        val search = SearchRoutes(database, PageCards, searchesLacuerda = true, clock = { now })
                        val q = r.extra.getValue("q").jsonPrimitive.content
                        val target = "/api/search?q=" + URLEncoder.encode(q, Charsets.UTF_8) + "&box=corpus"
                        val route = search.routes.first { it.method == "GET" && it.path == "/api/search" }
                        val answer = route.get!!.answer(TestApp.request("GET", target, emptyMap(), ByteArray(0),
                                                                        TestApp.SECRET))
                        val said = Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8)).jsonObject
                        val out = r.out!!.jsonObject
                        // a query too short to look for is answered short, with neither: the page offers neither
                        val short = said["short"] == JsonPrimitive(true)
                        for (name in listOf("lacuerda_search", "lacuerda_unlisted")) {
                            val got: JsonElement = said[name] ?: if (short) JsonNull else JsonPrimitive("missing")
                            WebJson.difference(out.getValue(name), got)?.let {
                                misses.check(false) { "${fixture.jsonPrimitive.content}, ${case.jsonPrimitive.content}, “$q”: $name at $it" }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun inFolder(name: String, body: (File) -> Unit) {
        val dir = Files.createTempDirectory(name).toFile()
        try {
            body(dir)
        } finally {
            dir.deleteRecursively()
        }
    }
}
