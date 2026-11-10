package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.match.MatchCandidate
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.SongFacts
import io.github.danielhp95.caracole.server.lookups.Review
import io.github.danielhp95.caracole.server.lookups.ReviewRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.ReviewRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files
import java.time.Instant

/**
 * An uncertain match reviewed on the phone (tests/test_conformance_review.py's docstring has the shapes), every record
 * of vectors/web/review.jsonl over its library (the vector's fixture, in a database of its own):
 *
 * - review.py's rules ([Review]): its constants, `candidates_of`, `step_words`, `writes_alias`, `search_candidates`
 *   and the picker's choices (`library_page.review_choices`), each compared as a candidate's four fields;
 * - `GET /review`: the picker's page byte for byte (its style, the message page's, left out of both), its policy the
 *   message page's, or its refusal;
 * - `POST /review`: to a fresh queue that runs nothing (one of no room for a `full` record; one holding a request of
 *   the song's for a `busy` one), its refusal or its answer and the job it queued, its commands the phone's
 *   (`phone_steps`);
 * - `caracole review`: the review runner over a fresh copy of the library, its exit status, its last word, its lines,
 *   then the phone's overrides and every song's match;
 * - `POST /review, run`: the job POST /review queues, run by the phone's queue and its review runner, then its line as
 *   the phone's says it (JobViews.line, its song's facts SongFacts.songOf) and the rows as above.
 */
object ReviewReplay : AreaReplay {
    override val area = "review"
    const val REVIEW = "web/review.jsonl"

    /** The library's name and the form token the generator's pages had. */
    private const val NAME = "Songs & Co"
    private const val CSRF = "tok"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    private val COLUMNS = listOf("key", "status", "review", "match_decision", "match_step", "match_score",
                                 "match_artist_key", "match_song_key", "match_candidates", "ug_dirty")

    override fun replay(misses: Misses) {
        val lines = Corpus.lines(REVIEW).filter { it["header"] != JsonPrimitive(true) }
        val fixture = lines.first { fn(it) == "fixture" }.getValue("records").jsonArray.map { it.jsonObject }
        val library = fixture.filter { it["table"]?.jsonPrimitive?.content == "songs" }
            .associate { it.getValue("row").jsonObject.let { row -> row.getValue("id").jsonPrimitive.content.toLong() to row } }
        inFolder("review") { dir ->
            TestDb.fresh(File(dir, "read").apply { mkdirs() }).use { database ->
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture) }
                for (r in lines) {
                    val fn = fn(r)
                    when {
                        fn.startsWith("caracole.") -> rule(misses, database, fn, r)
                        fn == "GET /review" -> picker(misses, database, dir, r)
                        fn == "POST /review" -> answer(misses, database, dir, r)
                    }
                }
            }
            var n = 0
            for (r in lines) {
                val fn = fn(r)
                if (fn != "caracole review" && fn != "POST /review, run") continue
                val where = File(dir, "case-${n++}").apply { mkdirs() }
                TestDb.fresh(where).use { database ->
                    database.writeBlocking { db -> Fixtures.loadRecords(db, fixture) }
                    if (fn == "caracole review") command(misses, database, where, r, library)
                    else run(misses, database, where, r, library)
                }
            }
        }
    }

    private fun fn(r: JsonObject): String = r["fn"]?.jsonPrimitive?.content.orEmpty()

    // --- review.py's rules ------------------------------------------------------------------------------------------

    private fun rule(misses: Misses, database: Database, fn: String, r: JsonObject) {
        val out = r.getValue("out")
        val case = "$fn(${r["song"] ?: r["cand"] ?: ""})"
        database.read { db ->
            val song = r["song"]?.jsonPrimitive?.content?.let { key -> Songs.byKey(db, key) }
            if ("song" in r && song == null) return@read misses.check(false) { "$case: no such song in the fixture" }
            val got: JsonElement = when (fn) {
                "caracole.review.SHOWN" -> JsonPrimitive(Review.SHOWN)
                "caracole.review.SEARCH" -> JsonPrimitive(Review.SEARCH)
                "caracole.review.SEARCHED" -> JsonPrimitive(Review.SEARCHED)
                "caracole.match.NO_ALIAS_STEPS" -> JsonArray(Match.NO_ALIAS_STEPS.map(::JsonPrimitive))
                "caracole.review.candidates_of" -> candidates(Review.candidatesOf(song!!))
                "caracole.review.step_words" -> JsonPrimitive(Review.stepWords(candidate(r.getValue("cand").jsonObject)))
                "caracole.review.writes_alias" ->
                    JsonPrimitive(Review.writesAlias(song!!, candidate(r.getValue("cand").jsonObject)))
                "caracole.review.search_candidates" -> {
                    val rejected = r.getValue("rejected").jsonArray.map {
                        it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content
                    }.toSet()
                    candidates(Review.searchCandidates(db, song!!, rejected))
                }
                "caracole.library_page.review_choices" -> {
                    val cands = (r["cands"] as? JsonArray)?.map { candidate(it.jsonObject) }
                    JsonArray(Review.choices(db, song!!, cands))
                }
                else -> return@read misses.check(false) { "$fn: no such rule" }
            }
            val expected = if (fn.endsWith("candidates_of") || fn.endsWith("search_candidates")) {
                JsonArray(out.jsonArray.map { normal(it.jsonObject) })
            } else out
            WebJson.difference(expected, got)?.let { misses.check(false) { "$case at $it: $got" } } ?: misses.check(true) { "" }
        }
    }

    /** A candidate of a record, as stored: its keys, score and step (each null when the record has none). */
    private fun candidate(c: JsonObject): MatchCandidate = MatchCandidate(
        c["artist_key"]?.jsonPrimitive?.contentOrNull.orEmpty(), c["song_key"]?.jsonPrimitive?.contentOrNull.orEmpty(),
        (c["score"] as? JsonPrimitive)?.doubleOrNull, (c["step"] as? JsonPrimitive)?.contentOrNull,
    )

    /** A candidate's four fields as JSON, a score a float. */
    private fun candidates(cands: List<MatchCandidate>): JsonArray = JsonArray(cands.map { c ->
        JsonObject(linkedMapOf("artist_key" to JsonPrimitive(c.artistKey), "song_key" to JsonPrimitive(c.songKey),
                               "score" to (c.score?.let(::JsonPrimitive) ?: JsonNull),
                               "step" to (c.step?.let(::JsonPrimitive) ?: JsonNull)))
    })

    /** Python's candidate dict as [candidates] writes one: its four fields, a step it lacks null. */
    private fun normal(c: JsonObject): JsonObject = JsonObject(linkedMapOf(
        "artist_key" to (c["artist_key"] ?: JsonNull), "song_key" to (c["song_key"] ?: JsonNull),
        "score" to ((c["score"] as? JsonPrimitive)?.doubleOrNull?.let(::JsonPrimitive) ?: JsonNull),
        "step" to (c["step"] ?: JsonNull),
    ))

    // --- the routes -------------------------------------------------------------------------------------------------

    private fun routes(database: Database, dir: File, queue: JobQueue): ReviewRoutes =
        ReviewRoutes(parts(database, dir, queue), csrf = { CSRF }, libraryName = { NAME })

    private fun picker(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val case = "GET /review (${r.getValue("case").jsonPrimitive.content})"
        val target = r.getValue("target").jsonPrimitive.content
        val out = r.getValue("out").jsonObject
        val route = routes(database, dir, JobQueue(NOWHERE)).routes.first { it.method == "GET" }
        val answer: Response = try {
            route.get!!.answer(TestApp.request("GET", target, emptyMap(), ByteArray(0), TestApp.SECRET))
        } catch (e: Refused) {
            return refused(misses, case, out, e)
        }
        if ("html" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        val html = answer.bytes.toString(Charsets.UTF_8)
        val style = MessagePage.style
        misses.check(html.split(style).size == 2) { "$case: the page doesn't hold the message page's style once" }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.int) { "$case: status ${answer.status}" }
        misses.check(answer.header("content-security-policy") == MessagePage.csp) { "$case: its policy" }
        val expected = out.getValue("html").jsonPrimitive.content
        val got = html.replace(style, "")
        misses.check(got == expected) { "$case: the page differs at ${firstDifference(expected, got)}" }
    }

    private fun answer(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val case = "POST /review (${r.getValue("case").jsonPrimitive.content})"
        val out = r.getValue("out").jsonObject
        val full = r.getValue("full").jsonPrimitive.boolean
        val queue = JobQueue(NOWHERE, limit = if (full) 0 else JobQueue.LIMIT)
        val form = form(r)
        if (r.getValue("busy").jsonPrimitive.boolean) {  // a request of the song's waits: its add, say
            val song = database.read { db -> Songs.byId(db, form.getValue("song").toLong()) }!!
            queue.submit(JobSpec("Add ${song.display}", song.key, "add", listOf("add" to "Adding to the library"),
                                 display = song.display, run = {}))
        }
        val route = routes(database, dir, queue).routes.first { it.method == "POST" }
        val answer: Response = try {
            route.post!!.answer(TestApp.request("POST", "/review", emptyMap(), ByteArray(0), TestApp.SECRET), form)
        } catch (e: Refused) {
            return refused(misses, case, out, e)
        }
        if ("job" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.int) { "$case: status ${answer.status}" }
        misses.check(answer.header("location") == out["location"]?.jsonPrimitive?.contentOrNull) {
            "$case: Location ${answer.header("location")}, caracole serve's ${out["location"]}"
        }
        val jobs = queue.snapshot().filter { it.spec.kind != "add" }
        if (jobs.size != 1) return misses.check(false) { "$case: ${jobs.size} jobs queued" }
        val job = jobs.single()
        val python = out.getValue("job").jsonObject
        val phone = JsonObject(linkedMapOf(
            "title" to JsonPrimitive(job.spec.title), "key" to JsonPrimitive(job.key),
            "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
            "fetching" to JsonPrimitive(job.fetching), "display" to JsonPrimitive(job.display),
        ))
        val expected = JsonObject(python + ("steps" to out.getValue("phone_steps")))
        WebJson.difference(expected, phone)?.let { misses.check(false) { "$case: its job at $it: $phone" } }
            ?: misses.check(true) { "" }
    }

    private fun refused(misses: Misses, case: String, out: JsonObject, e: Refused) {
        val got = JsonObject(linkedMapOf("status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title),
                                         "message" to JsonPrimitive(e.message)))
        val expected = JsonObject(linkedMapOf("status" to (out["status"] ?: JsonNull), "title" to (out["title"] ?: JsonNull),
                                              "message" to (out["message"] ?: JsonNull)))
        misses.check("message" in out && expected == got) { "$case: refused $got, caracole serve's $out" }
    }

    private fun form(r: JsonObject): Map<String, String> {
        val form = LinkedHashMap<String, String>()
        for (field in r.getValue("form").jsonArray) {
            form[field.jsonArray[0].jsonPrimitive.content] = field.jsonArray[1].jsonPrimitive.content
        }
        return form
    }

    // --- the command, and the job -----------------------------------------------------------------------------------

    /** What a command said, as the queue hears it. */
    private class Said : JobContext {
        val lines = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) = Unit
        override fun say(line: String) { lines += line }
        override fun outcome(value: JsonObject) = Unit
        override val isCancelled: Boolean = false
    }

    private fun command(misses: Misses, database: Database, dir: File, r: JsonObject, library: Map<Long, JsonObject>) {
        val case = "caracole review (${r.getValue("case").jsonPrimitive.content})"
        val args = r.getValue("args").jsonArray.map { it.jsonPrimitive.content }
        val out = r.getValue("out").jsonObject
        val said = Said()
        var code = 0
        var error: String? = null
        try {
            runBlocking { ReviewRunner(parts(database, dir, JobQueue(NOWHERE))).run(args, said) }
        } catch (e: CommandExit) {
            code = e.code
            error = e.message
        }
        misses.check(code == out.getValue("code").jsonPrimitive.int) { "$case: exit $code ($error), caracole's ${out["code"]}" }
        misses.check(error == out["error"]?.jsonPrimitive?.contentOrNull) { "$case: said ${error}, caracole ${out["error"]}" }
        val lines = out.getValue("lines").jsonArray.map { it.jsonPrimitive.content }
        misses.check(said.lines == lines) { "$case: its lines ${said.lines}, caracole's $lines" }
        rows(misses, case, database, out, library)
    }

    private fun run(misses: Misses, database: Database, dir: File, r: JsonObject, library: Map<Long, JsonObject>) {
        val case = "POST /review, run (${r.getValue("case").jsonPrimitive.content})"
        val out = r.getValue("out").jsonObject
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        try {
            val commands = HashMap<String, io.github.danielhp95.caracole.server.jobs.CommandRunner>()
            val queue = JobQueue(scope, commands = Commands(commands))
            val parts = parts(database, dir, queue)
            commands["review"] = ReviewRunner(parts)
            val route = ReviewRoutes(parts, csrf = { CSRF }, libraryName = { NAME }).routes.first { it.method == "POST" }
            val answer = route.post!!.answer(TestApp.request("POST", "/review", emptyMap(), ByteArray(0), TestApp.SECRET),
                                             form(r))
            val id = answer.data!!.getValue("job").jsonObject.getValue("id").jsonPrimitive.int
            val job = runBlocking { withTimeout(60_000) { queue.await(id) } }
            misses.check(job.state == "done") { "$case: the job is ${job.state}: ${job.steps.map { it.output }}" }
            val facts = database.read { db -> SongFacts.ended(queue).songOf(db, job, parts.cards, Instant.now()) }.second
            val line = JobViews.line(job, facts = facts).asJson()
            WebJson.difference(out.getValue("line"), line)?.let { misses.check(false) { "$case: its line at $it: $line" } }
                ?: misses.check(true) { "" }
            rows(misses, case, database, out, library)
        } finally {
            scope.cancel()
        }
    }

    /** The phone's overrides, as rows_of gives the computer's, and every song's match: those the record lists as it
     * lists them, every other as the library had it. */
    private fun rows(misses: Misses, case: String, database: Database, out: JsonObject, library: Map<Long, JsonObject>) {
        val (overrides, songs) = database.read { db -> overrides(db) to songs(db) }
        WebJson.difference(out.getValue("overrides"), overrides)?.let {
            misses.check(false) { "$case: the overrides at $it: $overrides" }
        } ?: misses.check(true) { "" }
        val listed = out.getValue("songs").jsonArray.associate { it.jsonObject.getValue("id").jsonPrimitive.content.toLong() to it.jsonObject }
        for ((id, row) in songs) {
            val expected = listed[id] ?: JsonObject(library.getValue(id).filterKeys { it == "id" || it in COLUMNS })
            WebJson.difference(expected, row)?.let { misses.check(false) { "$case: song $id at $it: $row" } }
                ?: misses.check(true) { "" }
        }
    }

    private fun overrides(db: Db): JsonArray = JsonArray(
        db.query("SELECT tbl, key, written, value FROM phone_overrides") {
            listOf(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!)
        }.sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(a[0], b[0]).takeIf { it != 0 } ?: Py.CODE_POINT_ORDER.compare(a[1], b[1]) }
            .map { (tbl, key, written, value) ->
                JsonObject(linkedMapOf("key" to JsonPrimitive(key), "tbl" to JsonPrimitive(tbl),
                                       "value" to JsonPrimitive(value), "written" to JsonPrimitive(written)))
            },
    )

    /** Every song's match columns, by id, as SQLite holds them. */
    private fun songs(db: Db): Map<Long, JsonObject> =
        db.query("SELECT id, ${COLUMNS.joinToString(", ")} FROM songs ORDER BY id") { row ->
            val values = LinkedHashMap<String, JsonElement>()
            values["id"] = JsonPrimitive(row.long(0))
            for ((i, name) in COLUMNS.withIndex()) {
                values[name] = when (name) {
                    "review", "ug_dirty" -> JsonPrimitive(row.long(i + 1))
                    "match_score" -> row.double(i + 1)?.let(::JsonPrimitive) ?: JsonNull
                    else -> row.text(i + 1)?.let(::JsonPrimitive) ?: JsonNull
                }
            }
            row.long(0)!! to JsonObject(values)
        }.toMap()

    // --- what the cases share ---------------------------------------------------------------------------------------

    /** The parts of a phone over [database], as the generator's caracole serve had them. */
    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(dir, "library").apply { mkdirs() }), state, { PhoneConfig.DEFAULTS },
                          queue, MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }

    private fun firstDifference(a: String, b: String): String {
        val at = a.indices.firstOrNull { it >= b.length || a[it] != b[it] } ?: a.length
        return "$at: …${a.substring(maxOf(0, at - 40), minOf(a.length, at + 40))}… vs …" +
            "${b.substring(maxOf(0, at - 40), minOf(b.length, at + 40))}…"
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
