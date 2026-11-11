package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.SongbookRoutes
import io.github.danielhp95.caracole.server.songbooks.SongbookRunner
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.header
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
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
 * The Songbooks tab's forms on the phone (tests/test_conformance_songbook_routes.py's docstring has the shapes):
 * vectors/songbook/routes.jsonl's scenarios, each form posted in turn to the phone's SongbookRoutes as caracole serve's
 * were, over its library (the vector's fixture, in a database and a library folder of their own), to one fresh queue
 * of the record's limit that runs nothing ([NOWHERE]): each answer, a refusal `{status, title, message}` or the jobs it
 * answers with (the songbook job's id, the lookups' it queued first, what is left, and each of those jobs' view as the
 * page's script reads it), and the queue's jobs after (title, key, commands, fetching, note, display, together).
 * Where caracole serve wrote wanted.txt (`wanted`), the phone writes none: its lookup's note says nothing then, and a
 * full queue says nothing was added ([LibraryRoutes.FULL]). [skip]: the scenarios to leave aside, by a path one of
 * their forms posts. [runner]: the commands those forms queue, run (routes_runner.jsonl). Both are of area
 * songbook-tab (SongbookTabReplay), and SongbookRoutesTest's on the JVM.
 */
object SongbookRoutesReplay {
    const val ROUTES = "songbook/routes.jsonl"
    const val RUNNER = "songbook/routes_runner.jsonl"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    fun replay(misses: Misses, skip: (path: String) -> Boolean = { false }) {
        val lines = Corpus.lines(ROUTES).filter { it["header"] != JsonPrimitive(true) }
        val fixture = lines.first { it["fn"]?.jsonPrimitive?.content == "fixture" }.getValue("records").jsonArray
            .map { it.jsonObject }
        val dir = Files.createTempDirectory("songbook-routes").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                val library = File(dir, "library").apply { mkdirs() }
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture, library) }
                for (r in lines) {
                    if (r["fn"]?.jsonPrimitive?.content != "songbook_routes") continue
                    val asked = r.getValue("asked").jsonArray.map { it.jsonObject }
                    if (asked.any { skip(it.getValue("path").jsonPrimitive.content) }) continue
                    scenario(misses, database, dir, r, asked)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun scenario(misses: Misses, database: Database, dir: File, r: JsonObject, asked: List<JsonObject>) {
        val case = r.getValue("case").jsonPrimitive.content
        val queue = JobQueue(NOWHERE, limit = r.getValue("limit").jsonPrimitive.int)
        val routes = SongbookRoutes(parts(database, dir, queue)).routes
        val outs = r.getValue("out").jsonArray
        for ((n, form) in asked.withIndex()) {
            val path = form.getValue("path").jsonPrimitive.content
            val said = "$case, form ${n + 1} ($path)"
            val route = routes.firstOrNull { it.method == "POST" && it.path == path }
                ?: return misses.check(false) { "$said: no route of the phone's" }
            val fields = LinkedHashMap<String, String>()
            for (field in form.getValue("form").jsonArray) {
                fields[field.jsonArray[0].jsonPrimitive.content] = field.jsonArray[1].jsonPrimitive.content
            }
            answer(misses, said, outs[n].jsonObject) {
                route.post!!.answer(TestApp.request("POST", path, mapOf("accept" to "application/json"), ByteArray(0),
                                                    TestApp.SECRET), fields)
            }
        }
        val jobs = queue.snapshot().sortedBy { it.id }
        val python = r.getValue("queue").jsonArray.map { it.jsonObject }
        if (jobs.size != python.size) {
            return misses.check(false) { "$case: ${jobs.size} jobs queued (${jobs.map { it.title }}), caracole serve's ${python.size}" }
        }
        for ((job, want) in jobs.zip(python)) {
            val phone = JsonObject(linkedMapOf(
                "id" to JsonPrimitive(job.id), "title" to JsonPrimitive(job.spec.title), "key" to JsonPrimitive(job.key),
                "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
                "fetching" to JsonPrimitive(job.fetching), "note" to JsonPrimitive(job.spec.note),
                "display" to JsonPrimitive(job.display), "together" to JsonArray(job.together.map(::JsonPrimitive)),
            ))
            // the phone writes no wanted.txt: no line for a new song's note to name
            val wanted = (want["wanted"] as? JsonPrimitive)?.boolean == true
            val expected = JsonObject(want - "wanted" + if (wanted) mapOf("note" to JsonPrimitive("")) else emptyMap())
            WebJson.difference(expected, phone)?.let { misses.check(false) { "$case: job ${job.id} at $it: $phone" } }
                ?: misses.check(true) { "" }
        }
    }

    /** One form's answer against caracole serve's [out]. */
    private fun answer(misses: Misses, said: String, out: JsonObject, post: () -> Response) {
        val wanted = (out["wanted"] as? JsonPrimitive)?.boolean == true
        val answer: Response = try {
            post()
        } catch (e: Refused) {
            val message = if (wanted) LibraryRoutes.FULL else out["message"]?.jsonPrimitive?.content
            val expected = JsonObject(linkedMapOf("status" to (out["status"] ?: JsonNull), "title" to (out["title"] ?: JsonNull),
                                                  "message" to JsonPrimitive(message)))
            val got = JsonObject(linkedMapOf("status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title),
                                             "message" to JsonPrimitive(e.message)))
            misses.check("job" !in out && expected == got) { "$said: refused $got, caracole serve's $out" }
            return
        }
        if ("job" !in out) return misses.check(false) { "$said: answered ${answer.status}, caracole serve refused $out" }
        val data = answer.data ?: JsonObject(emptyMap())
        val phone = JsonObject(linkedMapOf(
            "status" to JsonPrimitive(answer.status), "location" to (answer.header("location")?.let(::JsonPrimitive) ?: JsonNull),
            "job" to (data["job"] as? JsonObject)?.get("id").orNull(),
            "jobs" to JsonArray((data["jobs"] as? JsonArray).orEmpty().map { (it as JsonObject).getValue("id") }),
            "left" to data["left"].orNull(),
            "views" to JsonArray(listOfNotNull(data["job"]) + (data["jobs"] as? JsonArray).orEmpty()),
        ))
        val expected = JsonObject(out - "wanted")
        WebJson.difference(expected, phone)?.let { misses.check(false) { "$said: its answer at $it: $phone" } }
            ?: misses.check(true) { "" }
    }

    private fun JsonElement?.orNull(): JsonElement = this ?: JsonNull

    // --- the runner --------------------------------------------------------------------------------------------------

    /** The songbooks' pages of the generator's: render_songbooks making nothing, yet no [SongbookPages.NONE], so the
     * runner says what `_render` says once the songbooks are made. */
    private val NOTHING_MADE = SongbookPages { _, _ -> SongbookStats() }

    /**
     * vectors/songbook/routes_runner.jsonl: each case's `caracole songbook` commands run in turn by the phone's
     * SongbookRunner, over the songbook tab's library (SongbookTabReplay.LIBRARY, loaded afresh for each case) and the
     * record's overrides, the songbooks' pages making nothing ([NOTHING_MADE]): each command's lines as the queue
     * writes them (what it said, then its `error:` line, the library folder's path written `{library}`) and its exit
     * code, and every songbook after the last (Songbooks.value), as commands/songbook.py's.
     */
    fun runner(misses: Misses) {
        val records = Corpus.lines(RUNNER).filter { it["header"] != JsonPrimitive(true) }
        val o = records.first { it["fn"]?.jsonPrimitive?.content == "overrides" }.getValue("out").jsonObject
        val overrides = Overrides(
            version = o.getValue("version").jsonObject.mapValues { it.value.jsonPrimitive.content },
            transpose = o.getValue("transpose").jsonObject.mapValues { it.value.jsonPrimitive.int },
            ignore = o.getValue("ignore").jsonArray.mapTo(HashSet()) { it.jsonPrimitive.content },
        )
        for (r in records) {
            if (r["fn"]?.jsonPrimitive?.content != "songbook_runner") continue
            val dir = Files.createTempDirectory("songbook-runner").toFile()
            try {
                TestDb.fresh(dir).use { database ->
                    val library = File(dir, "library").apply { mkdirs() }
                    database.writeBlocking { db -> Fixtures.load(db, SongbookTabReplay.LIBRARY, library) }
                    val parts = parts(database, dir, JobQueue(NOWHERE), NOTHING_MADE)
                    runCase(misses, parts, SongbookRunner(parts, readOverrides = { overrides }), library, r)
                }
            } finally {
                dir.deleteRecursively()
            }
        }
    }

    private fun runCase(misses: Misses, parts: PhoneParts, runner: SongbookRunner, library: File, r: JsonObject) {
        val case = r.getValue("case").jsonPrimitive.content
        for ((n, command) in r.getValue("commands").jsonArray.map { it.jsonObject }.withIndex()) {
            val args = command.getValue("args").jsonArray.map { it.jsonPrimitive.content }
            val heard = Heard()
            val code = try {
                runBlocking { runner.run(args, heard) }
                0
            } catch (e: CommandExit) {
                if (!e.message.isNullOrEmpty()) heard.say("error: ${e.message!!.lines().first()}")
                e.code
            }
            val phone = JsonObject(linkedMapOf(
                "lines" to JsonArray(heard.lines.map { JsonPrimitive(it.replace(library.path, "{library}")) }),
                "code" to JsonPrimitive(code),
            ))
            val expected = JsonObject(linkedMapOf("lines" to command.getValue("lines"), "code" to command.getValue("code")))
            WebJson.difference(expected, phone)?.let {
                misses.check(false) { "$case, command ${n + 1} (${args.joinToString(" ")}) at $it: $phone" }
            } ?: misses.check(true) { "" }
        }
        val books = JsonArray(parts.database.read { db -> Songbooks.all(db) }.map(Songbooks::value))
        WebJson.difference(r.getValue("songbooks"), books)?.let { misses.check(false) { "$case: the songbooks at $it: $books" } }
            ?: misses.check(true) { "" }
    }

    /** What a command says, line by line, as the queue hears it. */
    private class Heard : JobContext {
        val lines = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) = Unit
        override fun say(line: String) {
            lines += line
        }
        override fun outcome(value: JsonObject) = Unit
        override val isCancelled: Boolean get() = false
    }

    /** The parts of a phone over [database], as caracole serve's generator had it. */
    private fun parts(database: Database, dir: File, queue: JobQueue, songbooks: SongbookPages = SongbookPages.NONE): PhoneParts {
        val state = File(dir, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                          MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, songbooks, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }
}
