package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.serialization.json.Json
import org.junit.Test
import java.nio.file.Files
import java.time.Instant
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * `caracole lyrics --song --record --progress` on the phone against the computer's picks (vectors/lookup/
 * lyrics_pick.jsonl, tests/test_conformance_lyrics_pick.py): each record's world made as LookupScenariosReplay makes
 * one, then [LyricsRunner] given the command line the phone queues ([JobCommands.lyricsPickSteps]), its pages
 * [SongPages.NONE], no chord models; compared as a lookup is: each stage's end, the song, the files readable, the
 * stages as told, the exit, and every request, event, row, kv record and file.
 */
class LyricsRunnerTest {
    private val records = Corpus.lines(PICKS).filter { it["header"] != JsonPrimitive(true) }

    private class Told(private val progress: Progress) : JobContext {
        val said = ArrayList<String>()
        val states = LinkedHashMap<String, JsonElement>()
        val details = LinkedHashMap<String, JsonElement>()
        var song: Pair<Long, String>? = null
        var files: Map<String, String> = emptyMap()

        override fun stage(name: String, state: String, detail: String) {
            progress.stage(name, state, detail)
            if (state == "running") return
            states[name] = JsonPrimitive(state)
            details[name] = JsonPrimitive(detail)
        }

        override fun say(line: String) {
            said += line
        }

        override fun song(id: Long, display: String) {
            progress.song(id, display)
            song = id to display
        }

        override fun readable(files: Map<String, String>, seconds: Double) {
            progress.readable(files, seconds)
            this.files = files
        }

        override fun outcome(value: JsonObject) {}
        override val isCancelled: Boolean = false
    }

    private val picking = LookupScenariosReplay.Run { w ->
        val display = w.kw.getValue("song").jsonPrimitive.content
        val steps = JobCommands.lyricsPickSteps(display, w.kw.getValue("record").jsonPrimitive.content)
        val scope = CoroutineScope(SupervisorJob())
        try {
            val state = File(w.cacheDir.parentFile, "state").apply { mkdirs() }
            val parts = PhoneParts(w.database, w.store, state, { w.config }, JobQueue(scope), MirrorPageData(null),
                                   { w.clients() }, SongPages.NONE, SongbookPages.NONE, Alerts.NONE, w.pacing,
                                   searchesLacuerda = false)
            val told = Told(w.progress)
            val stamped = w.database.read { db -> db.query("SELECT id, created_at FROM files") { it.long(0)!! to it.text(1) }.toMap() }
            val exit = try {
                runBlocking { LyricsRunner(parts).run(steps.single().args, told) }
                0
            } catch (e: CommandExit) {
                e.code
            }
            w.database.writeBlocking { db ->  // a file kept at the clock's time, as Python's at SQLite's: both at `now`
                for ((id, at) in db.query("SELECT id, created_at FROM files") { it.long(0)!! to it.text(1) }) {
                    if (stamped[id] != at) db.execute("UPDATE files SET created_at = ? WHERE id = ?", w.record.getValue("now").jsonPrimitive.content, id)
                }
            }
            LookupScenariosReplay.Ran(JsonObject(mapOf(
                "song_id" to (told.song?.first?.let(::JsonPrimitive) ?: JsonNull),
                "display" to JsonPrimitive(told.song?.second ?: display),
                "states" to JsonObject(told.states),
                "details" to JsonObject(told.details),
                "files" to JsonObject(told.files.mapValues { JsonPrimitive(it.value) }),
                "exit" to JsonPrimitive(exit),
            )))
        } finally {
            scope.cancel()
        }
    }

    @Test fun everyPickDoesWhatCaracoleLyricsRecordDid() {
        val misses = Misses("lyrics-pick")
        val replayed = LookupScenariosReplay.replay(PICKS, misses, picking)
        misses.assertNone()
        assertEquals(records.map { it.getValue("case").jsonPrimitive.content }, replayed)
    }

    @Test fun anLrclibPickSendsNoRequestAndAReLayRunsNoModel() {
        val lrclib = records.first { it.getValue("case").jsonPrimitive.content.startsWith("LRCLIB's record") }
        val out = lrclib.getValue("out").jsonObject
        assertEquals(JsonArray(emptyList()), out.getValue("requests"))
        val ends = out.getValue("result").jsonObject.getValue("result").jsonObject.getValue("states").jsonObject
        assertEquals(JsonPrimitive("done"), ends["chords"])  // replayed above with no chord models at all
    }

    @Test fun aStrayPickIsTold() {
        val first = records.first().getValue("case").jsonPrimitive.content
        val misses = Misses("lyrics-pick")
        LookupScenariosReplay.replay(PICKS, misses, picking, only = setOf(first)) { r ->
            val out = r.getValue("out").jsonObject
            JsonObject(r + ("out" to JsonObject(out + ("library" to JsonObject(emptyMap())))))
        }
        assertFailsWith<AssertionError> { misses.assertNone() }
    }

    /** A song with audio of its own on the phone and no auto sheet: the pick's chords are heard by the chord models,
     * the lookups queued going first, and the sheet kept as the audio job keeps one, over the lyrics just picked. */
    @Test fun aPickOverTheSongsOwnAudioHearsItsChordsByTheModels() {
        val mega = records.first { it.getValue("case").jsonPrimitive.content.startsWith("Megalobiz's record") }
        val heardRecord = records.first { it.getValue("case").jsonPrimitive.content.startsWith("LRCLIB's record") }
            .getValue("out").jsonObject.getValue("rows").jsonObject.getValue("versions").jsonArray
            .map { Json.parseToJsonElement(it.jsonObject.getValue("raw").jsonPrimitive.content).jsonObject }
            .first { "heard" in it }.getValue("heard")
        val dir = Files.createTempDirectory("caracole-pick").toFile()
        val scope = CoroutineScope(SupervisorJob())
        try {
            val now = Instant.parse(mega.getValue("now").jsonPrimitive.content)
            val library = File(dir, "library").apply { mkdirs() }
            val state = File(dir, "state").apply { mkdirs() }
            val audio = File(state, "audio/1-0123456789abcdef.m4a").apply { parentFile.mkdirs(); writeBytes(ByteArray(64)) }
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, mega.getValue("fixture").jsonArray.map { it.jsonObject }, library)
                    db.execute("UPDATE songs SET audio_path = ?, audio_mtime = 1.0", audio.path)
                }
                val answers = mega.getValue("answers").jsonObject.mapValues { (_, a) ->
                    val o = a.jsonObject
                    HttpAnswer(o.getValue("status").jsonPrimitive.content.toInt(),
                               o.getValue("headers").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content },
                               Scenarios.body(o.getValue("body")))
                }
                val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
                                    monotonic = { 0.0 }, clock = { now })
                val cache = File(dir, "cache")
                val parts = PhoneParts(database, LibraryStore(library, File(state, AudioStore.FOLDER)), state,
                                       { PhoneConfig.DEFAULTS }, JobQueue(scope), MirrorPageData(null),
                                       { Clients(PhoneConfig.DEFAULTS, cache, { FakeTransport(answers) }, pacing) },
                                       SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
                var heardFrom: File? = null
                val chords = object : ChordModels {
                    override fun ready(): String? = null
                    override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
                        heardFrom = audio
                        onStep("hearing the chords")
                        return Heard.of(heardRecord)
                    }
                }
                val told = Told(object : Progress { override fun stage(name: String, state: String, detail: String) {} })
                runBlocking {
                    LyricsRunner(parts, chords, AudioStore(state, { _, _ -> error("no file examined") })).run(
                        JobCommands.lyricsPickSteps("Nick Cani - Vikingos veganos", "megalobiz:5001").single().args, told)
                }
                assertEquals(audio, heardFrom)
                assertEquals(JsonPrimitive("done"), told.states["lyrics"])
                assertEquals(JsonPrimitive("done"), told.states["chords"], "${told.details}")
                assertEquals(JsonPrimitive("chords over the lyrics"), told.details["chords"])
                database.read { db ->
                    val raw = db.one("SELECT raw FROM versions WHERE provider = 'auto'") { it.text(0) }!!
                    val made = Json.parseToJsonElement(raw).jsonObject
                    assertEquals(JsonPrimitive("phone"), made["made_on"])
                    assertEquals(JsonPrimitive("synced"), made["lyrics"])
                }
            }
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
    }

    @Test fun aPickIsTheQueuesAndItsCommandLineIsRead() {
        val steps = JobCommands.lyricsPickSteps("Radiohead - Creep", "lrclib:1")
        assertEquals(listOf("lyrics", "--song=Radiohead - Creep", "--record=lrclib:1", "--progress"), steps.single().args)
        assertTrue(!JobCommands.isLookup(steps.single().args))
    }

    private companion object {
        const val PICKS = "lookup/lyrics_pick.jsonl"
    }
}
