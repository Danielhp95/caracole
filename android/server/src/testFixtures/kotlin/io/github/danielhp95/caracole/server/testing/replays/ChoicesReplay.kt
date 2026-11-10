package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.RenderStats
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
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.HarmonicaRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.HarmonicaRoutes
import io.github.danielhp95.caracole.server.routes.VersionsRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files

/**
 * A sheet's versions and a harmonica tab's readings chosen on the phone (tests/test_conformance_choices.py's
 * docstring has the shapes): vectors/web/versions_routes.jsonl and harmonica_routes.jsonl, each scene's library (its
 * fixture, in a database of its own, the tabs' files in its library folder), then each record over it:
 *
 * - a page, `GET /versions` or `GET /harmonica`, answered by the phone's route (VersionsRoutes, HarmonicaRoutes) with
 *   the record's job as the queue's (JobViewsReplay.jobOf): its refusal, `{status, title, message}`, or its page,
 *   whole but its stylesheet's text;
 * - a post to a fresh queue that runs nothing, after the record's `before` posts: its refusal, or its status, its
 *   `Location`, the job it queued (title, key, commands, fetching, display, song) and how many the queue holds;
 * - `caracole harmonica`: the phone's runner (HarmonicaRunner) over the scene, its overrides as the fixture left them,
 *   its render a recording SongPages: its exit code, its lines, the error it failed with, whether it rendered the
 *   song again, and `[harmonica]` after it.
 */
object ChoicesReplay : AreaReplay {
    override val area = "choices"
    const val VERSIONS = "web/versions_routes.jsonl"
    const val HARMONICA = "web/harmonica_routes.jsonl"
    const val CSRF = "tok"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(kotlinx.coroutines.Job().apply { cancel() })
    private val STYLE = Regex("<style>.*?</style>", RegexOption.DOT_MATCHES_ALL)

    override fun replay(misses: Misses) {
        replay(misses, VERSIONS)
        replay(misses, HARMONICA)
    }

    /** The fixture of the scene [scene] of the vector [name] ([VERSIONS], [HARMONICA]): its records, for a test that
     * makes a phone of that library (Fixtures.loadRecords, its files under the library given). */
    fun scene(name: String, scene: String): List<JsonObject> = Corpus.lines(name)
        .first { fn(it) == "fixture" && it["scene"]?.jsonPrimitive?.content == scene }
        .getValue("records").jsonArray.map { it.jsonObject }

    private fun replay(misses: Misses, name: String) {
        val lines = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }
        for (fixture in lines.filter { fn(it) == "fixture" }) {
            val scene = fixture.getValue("scene").jsonPrimitive.content
            inFolder("choices-$scene") { dir ->
                TestDb.fresh(dir).use { database ->
                    val library = File(dir, "library").apply { mkdirs() }
                    database.writeBlocking { db ->
                        Fixtures.loadRecords(db, fixture.getValue("records").jsonArray.map { it.jsonObject }, library)
                    }
                    val overrides = database.read { db -> rows(db) }
                    for (r in lines.filter { fn(it) != "fixture" && it["scene"]?.jsonPrimitive?.content == scene }) {
                        val fn = fn(r)
                        when {
                            fn.startsWith("GET ") -> page(misses, database, dir, r)
                            fn.startsWith("POST ") -> post(misses, database, dir, r)
                            fn == "caracole harmonica" -> {
                                database.writeBlocking { db -> restore(db, overrides) }
                                command(misses, database, dir, r)
                            }
                            else -> misses.check(false) { "$name: a record of no kind the replay knows, $fn" }
                        }
                    }
                }
            }
        }
    }

    private fun fn(r: JsonObject): String = r["fn"]?.jsonPrimitive?.content.orEmpty()

    private fun case(r: JsonObject): String = "${fn(r)} (${r["scene"]?.jsonPrimitive?.content}, ${r["case"]?.jsonPrimitive?.content})"

    /** The routes of [fn]'s area, over [parts], [jobOf] the queue's jobs. */
    private fun module(fn: String, parts: PhoneParts, jobOf: (Int) -> Job?): RouteModule =
        if (fn.contains("/versions")) VersionsRoutes(parts, CSRF, jobOf) else HarmonicaRoutes(parts, CSRF, jobOf)

    /** A refusal as the records hold one. */
    private fun refusal(e: Refused): JsonObject = JsonObject(linkedMapOf(
        "status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title), "message" to JsonPrimitive(e.message),
    ))

    private fun page(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val held = r["job"] as? JsonObject
        val job = held?.let { JobViewsReplay.jobOf(misses, it) ?: return }
        val parts = parts(database, dir, JobQueue(NOWHERE))
        val path = fn(r).removePrefix("GET ")
        val route = module(fn(r), parts) { id -> job?.takeIf { it.id == id } }.routes
            .first { it.method == "GET" && it.path == path }
        val target = r.getValue("target").jsonPrimitive.content
        val out = r.getValue("out").jsonObject
        val answer: Response = try {
            route.get!!.answer(TestApp.request("GET", target, emptyMap(), ByteArray(0), TestApp.SECRET))
        } catch (e: Refused) {
            val got = refusal(e)
            misses.check(got == out) { "${case(r)}: refused $got, caracole serve's $out" }
            return
        }
        if ("page" !in out) return misses.check(false) { "${case(r)}: answered ${answer.status}, caracole serve's $out" }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.int) {
            "${case(r)}: status ${answer.status}, caracole serve's ${out["status"]}"
        }
        val page = answer.bytes.toString(Charsets.UTF_8).replaceFirst(STYLE, "<style></style>")
        val python = out.getValue("page").jsonPrimitive.content
        misses.check(page == python) { "${case(r)}: its page differs from line ${firstDifference(page, python)}:\n$page" }
    }

    private fun post(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val queue = JobQueue(NOWHERE)
        val parts = parts(database, dir, queue)
        val routes = module(fn(r), parts, queue::job).routes
        fun posted(path: String, fields: JsonArray): Response {
            val route = routes.first { it.method == "POST" && it.path == path }
            val form = LinkedHashMap<String, String>()
            for (field in fields) form[field.jsonArray[0].jsonPrimitive.content] = field.jsonArray[1].jsonPrimitive.content
            return route.post!!.answer(TestApp.request("POST", path, emptyMap(), ByteArray(0), TestApp.SECRET), form)
        }
        for (before in r.getValue("before").jsonArray) {
            posted(before.jsonArray[0].jsonPrimitive.content, before.jsonArray[1].jsonArray)
        }
        val out = r.getValue("out").jsonObject
        val answer = try {
            posted(fn(r).removePrefix("POST "), r.getValue("form").jsonArray)
        } catch (e: Refused) {
            val got = refusal(e)
            misses.check(got == out) { "${case(r)}: refused $got, caracole serve's $out" }
            return
        }
        if ("job" !in out) return misses.check(false) { "${case(r)}: answered ${answer.status}, caracole serve's $out" }
        val id = answer.data?.get("job")?.jsonObject?.get("id")?.jsonPrimitive?.int
        val jobs = queue.snapshot()
        val job = jobs.firstOrNull { it.id == id }
            ?: return misses.check(false) { "${case(r)}: no job of its answer's, $id, in ${jobs.map { it.id }}" }
        val got = JsonObject(linkedMapOf(
            "status" to JsonPrimitive(answer.status), "location" to (answer.header("location")?.let(::JsonPrimitive) ?: JsonNull),
            "job" to JsonObject(linkedMapOf(
                "title" to JsonPrimitive(job.title), "key" to JsonPrimitive(job.key),
                "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
                "fetching" to JsonPrimitive(job.fetching), "display" to JsonPrimitive(job.display),
                "song_id" to (job.songId?.let(::JsonPrimitive) ?: JsonNull),
            )),
            "jobs" to JsonPrimitive(jobs.size),
        ))
        WebJson.difference(out, got)?.let { misses.check(false) { "${case(r)}: at $it: $got" } }
    }

    private fun command(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val rendered = ArrayList<Long>()
        val pages = SongPages { _, ids, _ -> rendered += ids; RenderStats() }
        val parts = parts(database, dir, JobQueue(NOWHERE), pages)
        val lines = ArrayList<String>()
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) {}
            override fun say(line: String) { lines += line }
            override fun outcome(value: JsonObject) {}
            override val isCancelled: Boolean = false
        }
        val args = listOf("harmonica") + r.getValue("args").jsonArray.map { it.jsonPrimitive.content }
        var code = 0
        var error: String? = null
        try {
            runBlocking { HarmonicaRunner(parts).run(args, context) }
        } catch (e: CommandExit) {
            code = e.code
            error = e.message
        }
        val harmonica = database.read { db -> Overrides.read(db).harmonica }
        val got = JsonObject(linkedMapOf(
            "code" to JsonPrimitive(code), "lines" to JsonArray(lines.map(::JsonPrimitive)),
            "error" to (error?.let(::JsonPrimitive) ?: JsonNull), "rendered" to JsonPrimitive(rendered.isNotEmpty()),
            "harmonica" to JsonObject(harmonica.mapValues { JsonObject(it.value) }),
        ))
        val out = r.getValue("out").jsonObject
        misses.check(got == out) { "${case(r)}: $got, caracole's $out" }
        if (rendered.isNotEmpty()) {
            misses.check(rendered.toSet().size == 1 && out.getValue("rendered").jsonPrimitive.boolean) {
                "${case(r)}: rendered songs $rendered"
            }
        }
    }

    /** The phone's overrides rows, as the fixture left them. */
    private fun rows(db: Db): List<List<String>> =
        db.query("SELECT tbl, key, written, value FROM phone_overrides ORDER BY rowid") {
            listOf(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!)
        }

    private fun restore(db: Db, rows: List<List<String>>) {
        db.execute("DELETE FROM phone_overrides")
        for (row in rows) {
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)", *row.toTypedArray())
        }
    }

    private fun firstDifference(a: String, b: String): Int {
        val x = a.split('\n')
        val y = b.split('\n')
        return (x.indices.firstOrNull { it >= y.size || x[it] != y[it] } ?: x.size) + 1
    }

    /** The parts of a phone over [database], its library at `dir/library`, as caracole serve's generator had it. */
    private fun parts(database: Database, dir: File, queue: JobQueue, pages: SongPages = SongPages.NONE): PhoneParts {
        val state = File(dir, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                          MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          pages, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
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
