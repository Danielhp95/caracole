package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
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
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.RenderRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.ExportRoutes
import io.github.danielhp95.caracole.server.routes.Exports
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.runBlocking
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
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files

/**
 * Export PDF and Make this my version on the phone (tests/test_conformance_export.py's docstring has the shapes), over
 * the vector's library (its fixture, in a database of its own, files and all):
 *
 * - `GET /export.pdf`: each target asked of the phone's route (ExportRoutes, no mirror: the library's viewers are its
 *   records) by its method, to a fresh queue that runs nothing (one of no room for a `full` record): its refusal,
 *   `{status, title, message}`, or its answer, `{name, label}` with its status, and the job `mine=1` queued (title,
 *   key, commands, display, song), none otherwise;
 * - `render.ExportSheet`: the song's export sheet (Exports.sheet), its own version and the version the query holds
 *   (Exports.version) as Exports.query writes them, the version's labels, ExportSheet.entry and ExportSheet.kept;
 * - `render --mine`: the render runner over the library's overrides as the fixture holds them: the line it says
 *   first and the song's `[version]` after it, or its exit and its `error:` words.
 *
 * A refusal's words name the library's folder `{library}`, and a record of `"prefix": true` holds their start alone
 * ([said]).
 */
object ExportReplay : AreaReplay {
    override val area = "export"
    const val EXPORT = "web/export.jsonl"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    override fun replay(misses: Misses) {
        val lines = Corpus.lines(EXPORT).filter { it["header"] != JsonPrimitive(true) }
        val fixture = lines.first { it["fn"]?.jsonPrimitive?.content == "fixture" }.getValue("records").jsonArray
            .map { it.jsonObject }
        val dir = Files.createTempDirectory("export").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                val library = File(dir, "library").apply { mkdirs() }
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture, library) }
                val overrides = fixture.filter { it["table"] == JsonPrimitive("phone_overrides") }
                for (r in lines) {
                    when (r["fn"]?.jsonPrimitive?.content) {
                        "GET /export.pdf" -> request(misses, database, dir, r)
                        "render.ExportSheet" -> sheet(misses, database, library, r)
                        "render --mine" -> {
                            database.writeBlocking { db ->
                                db.execute("DELETE FROM phone_overrides")
                                Fixtures.loadRecords(db, overrides)
                            }
                            mine(misses, database, dir, r)
                        }
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** One request asked of the phone's route as the generator asked caracole serve's, its answer compared. */
    private fun request(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val case = "GET /export.pdf (${r.getValue("case").jsonPrimitive.content})"
        val full = r.getValue("full").jsonPrimitive.boolean
        val queue = JobQueue(NOWHERE, limit = if (full) 0 else JobQueue.LIMIT)
        val route = ExportRoutes(parts(database, dir, queue)).routes.single { it.method == "GET" && it.path == "/export.pdf" }
        val asked = TestApp.request(r.getValue("method").jsonPrimitive.content, r.getValue("target").jsonPrimitive.content,
                                    mapOf("accept" to "application/json"), ByteArray(0), TestApp.SECRET)
        val out = r.getValue("out").jsonObject
        val got: JsonObject = try {
            val answer = route.get!!.answer(asked)
            val body = Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8)).jsonObject
            val job = queue.snapshot().singleOrNull()
            if (queue.snapshot().size > 1) return misses.check(false) { "$case: ${queue.snapshot().size} jobs queued" }
            JsonObject(linkedMapOf(
                "status" to JsonPrimitive(answer.status), "name" to (body["name"] ?: JsonNull),
                "label" to (body["label"] ?: JsonNull),
                "job" to (job?.let {
                    JsonObject(linkedMapOf(
                        "title" to JsonPrimitive(it.title), "key" to JsonPrimitive(it.key),
                        "steps" to JsonArray(it.steps.map { s ->
                            JsonArray(listOf(JsonPrimitive(s.label), JsonArray(s.args.map(::JsonPrimitive))))
                        }),
                        "display" to JsonPrimitive(it.display), "song" to (it.songId?.let(::JsonPrimitive) ?: JsonNull),
                    ))
                } ?: JsonNull),
            ))
        } catch (e: Refused) {
            if (queue.snapshot().isNotEmpty()) return misses.check(false) { "$case: refused, yet a job queued" }
            JsonObject(linkedMapOf("status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title)) +
                       said(out, "message", e.message.orEmpty(), dir))
        }
        WebJson.difference(out, got).let { at -> misses.check(at == null) { "$case: at $at: $got" } }
    }

    /** One export sheet's answers, compared. */
    private fun sheet(misses: Misses, database: Database, library: File, r: JsonObject) {
        val case = "render.ExportSheet (${r.getValue("case").jsonPrimitive.content})"
        val out = r.getValue("out").jsonObject
        val got = database.read { db ->
            val song = Songs.byId(db, r.getValue("song").jsonPrimitive.long)!!
            val overrides = Overrides.read(db)
            val sheet = Exports.sheet(db, library, song)
            val own = sheet.own(overrides)
            val v = Exports.version(r.getValue("query").jsonPrimitive.content, own)
            JsonObject(linkedMapOf(
                "own" to JsonPrimitive(Exports.query(own)), "version" to JsonPrimitive(Exports.query(v)),
                "label" to JsonPrimitive(sheet.label(v)), "traditional" to JsonPrimitive(sheet.label(v, traditional = true)),
                "entry" to JsonPrimitive(sheet.entry(v)), "kept" to (sheet.kept(v, overrides)?.let(::JsonPrimitive) ?: JsonNull),
            ))
        }
        WebJson.difference(out, got).let { at -> misses.check(at == null) { "$case: at $at: $got" } }
    }

    /** The render runner's Make this my version, compared: what it said first and wrote, or how it was refused. */
    private fun mine(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val case = "render --mine (${r.getValue("case").jsonPrimitive.content})"
        val args = r.getValue("args").jsonArray.map { it.jsonPrimitive.content }
        val out = r.getValue("out").jsonObject
        val said = ArrayList<String>()
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) = Unit
            override fun say(line: String) {
                said += line
            }
            override fun outcome(value: JsonObject) = Unit
            override val isCancelled: Boolean = false
        }
        val got: JsonElement = try {
            runBlocking { RenderRunner(parts(database, dir, JobQueue(NOWHERE))).run(args, context) }
            val name = args.first { it.startsWith("--song=") }.removePrefix("--song=")
            val version = database.read { db -> Overrides.read(db).version[OverrideUrls.overrideKey(name)] }
            JsonObject(linkedMapOf("said" to JsonArray(said.take(1).map(::JsonPrimitive)),
                                   "version" to (version?.let(::JsonPrimitive) ?: JsonNull)))
        } catch (e: CommandExit) {
            JsonObject(linkedMapOf<String, JsonElement>("exit" to JsonPrimitive(e.code)) +
                       said(out, "error", e.message.orEmpty(), dir))
        }
        WebJson.difference(out, got).let { at -> misses.check(at == null) { "$case: at $at: $got" } }
    }

    /**
     * A refusal's words [message] as the record holds them under [name]: the library's folder (under [dir]) named
     * `{library}`; for a record of `"prefix": true`, the start of the message alone, which ends with the reader's own
     * words on a file it couldn't read (Python's OSError, UnicodeDecodeError or JSONDecodeError's).
     */
    private fun said(out: JsonObject, name: String, message: String, dir: File): Map<String, JsonElement> {
        val words = message.replace(File(dir, "library").path, LIBRARY)
        val expected = (out[name] as? JsonPrimitive)?.content
        if (out["prefix"] != JsonPrimitive(true)) return mapOf(name to JsonPrimitive(words))
        val start = if (expected != null && words.startsWith(expected)) expected else words
        return linkedMapOf(name to JsonPrimitive(start), "prefix" to JsonPrimitive(true))
    }

    /** The library's folder in a record's message. */
    private const val LIBRARY = "{library}"

    /** The parts of a phone over [database], with no mirror and no pages of its own. */
    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                          MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }
}
