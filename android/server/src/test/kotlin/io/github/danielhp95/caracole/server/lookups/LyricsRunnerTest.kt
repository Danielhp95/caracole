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
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.sites.LyricsPickCommands
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

    /** What the last pick replayed sent its sites, and how many times a chord model was asked to hear. */
    private var sent: List<String> = emptyList()
    private var heardTimes = 0

    /** A chord model that hears nothing: a pick of `models` (a sheet up to date) asks it none. */
    private val noModel = object : ChordModels {
        override fun ready(): String? = null
        override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
            heardTimes++
            throw AssertionError("a model ran on $audio")
        }
    }

    /** The repository's root, where the generator ran: a song's own audio (`tests/fixtures/audio/…`) is under it. */
    private val root: File = File(System.getProperty("caracole.conformance")).parentFile.parentFile.parentFile

    private val picking = LookupScenariosReplay.Run { w ->
        if (w.fn == "caracole.commands.lyrics._lyrics_clear") return@Run clearing(w)
        val display = w.kw.getValue("song").jsonPrimitive.content
        val record = w.kw["record"]?.takeIf { it != JsonNull }?.jsonPrimitive?.content
        val row = w.kw["pick"]?.takeIf { it != JsonNull }?.jsonPrimitive?.content
        val args = if (record != null) JobCommands.lyricsPickSteps(display, record).single().args
                   else listOf("lyrics", "--song=$display", "--pick=$row", "--progress")
        val models = w.kw["models"]?.jsonPrimitive?.content == "true"
        val relative = w.database.read { db -> db.query("SELECT id, audio_path FROM songs WHERE audio_path LIKE 'tests/%'") {
            it.long(0)!! to it.text(1)!! } }
        w.database.writeBlocking { db ->
            for ((id, path) in relative) db.execute("UPDATE songs SET audio_path = ? WHERE id = ?", File(root, path).path, id)
        }
        val scope = CoroutineScope(SupervisorJob())
        try {
            val state = File(w.cacheDir.parentFile, "state").apply { mkdirs() }
            val parts = PhoneParts(w.database, w.store, state, { w.config }, JobQueue(scope), MirrorPageData(null),
                                   { w.clients() }, SongPages.NONE, SongbookPages.NONE, Alerts.NONE, w.pacing,
                                   searchesLacuerda = false)
            val told = Told(w.progress)
            val stamped = w.database.read { db -> db.query("SELECT id, created_at FROM files") { it.long(0)!! to it.text(1) }.toMap() }
            val runner = if (models) LyricsRunner(parts, chords = noModel, store = AudioStore(state, { _, _ ->
                error("no file examined") })) else LyricsRunner(parts)
            val exit = try {
                runBlocking { runner.run(args, told) }
                0
            } catch (e: CommandExit) {
                e.code
            }
            sent = w.transport.said
            w.database.writeBlocking { db ->  // the song's audio as Python's record names it
                for ((id, path) in relative) db.execute("UPDATE songs SET audio_path = ? WHERE id = ?", path, id)
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

    /** `caracole lyrics --song --clear` as the phone runs it: its line, its exit and its error's words. */
    private fun clearing(w: LookupScenariosReplay.World): LookupScenariosReplay.Ran {
        val display = w.kw.getValue("song").jsonPrimitive.content
        val scope = CoroutineScope(SupervisorJob())
        try {
            val state = File(w.cacheDir.parentFile, "state").apply { mkdirs() }
            val parts = PhoneParts(w.database, w.store, state, { w.config }, JobQueue(scope), MirrorPageData(null),
                                   { w.clients() }, SongPages.NONE, SongbookPages.NONE, Alerts.NONE, w.pacing,
                                   searchesLacuerda = false)
            val told = Told(w.progress)
            val (exit, error) = try {
                runBlocking { LyricsRunner(parts).run(listOf("lyrics", "--song=$display", "--clear"), told) }
                0 to null
            } catch (e: CommandExit) {
                e.code to e.message
            }
            return LookupScenariosReplay.Ran(JsonObject(mapOf(
                "lines" to JsonArray(told.said.map(::JsonPrimitive)), "exit" to JsonPrimitive(exit),
                "error" to (error?.let(::JsonPrimitive) ?: JsonNull))))
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

    @Test fun anLrclibPickSendsNoRequestAndAReLayOrASheetUpToDateRunsNoModel() {
        val cases = records.map { it.getValue("case").jsonPrimitive.content }
        val lrclib = cases.first { it.startsWith("LRCLIB's record") }
        val misses = Misses("lyrics-pick")
        var told: JsonObject? = null
        LookupScenariosReplay.replay(PICKS, misses, { w -> picking.run(w).also { told = it.result } }, only = setOf(lrclib))
        misses.assertNone()
        assertEquals(emptyList(), sent)  // what the phone's run sent: nothing
        assertEquals(JsonPrimitive("done"), told!!.getValue("states").jsonObject["chords"])  // re-laid, no models given
        val upToDate = cases.first { it.startsWith("the same record again, its sheet of its own audio up to date") }
        LookupScenariosReplay.replay(PICKS, misses, { w -> picking.run(w).also { told = it.result } }, only = setOf(upToDate))
        misses.assertNone()
        assertEquals(0, heardTimes)
        assertEquals(JsonPrimitive("up to date: chords over the lyrics"), told!!.getValue("details").jsonObject["chords"])
    }

    /** A record that can't be noted (the song's `[lyrics]` entry one the reader refuses, written after the job read
     * the overrides): the stage fails, the lyric files put back (none), nothing else changed (lyrics_pick._keep's). */
    @Test fun aRecordThatCantBeNotedPutsTheLyricFilesBack() {
        val mega = records.map { it.getValue("case").jsonPrimitive.content }.first { it.startsWith("Megalobiz's record, one") }
        var ended: LyricsPickCommands.Ended? = null
        var files: List<String> = emptyList()
        var status: String? = null
        LookupScenariosReplay.replay(PICKS, Misses("put back"), { w ->
            w.database.writeBlocking { db ->
                val now = Instant.parse(w.record.getValue("now").jsonPrimitive.content)
                val picked = LyricsPickCommands.findSong(db, "Nick Cani", "Vikingos veganos", Overrides(), now,
                                                         "megalobiz:5001")
                db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('lyrics', ?, ?, '\"x\"')",
                           picked.song.key, picked.song.display)
                val ask = InteractiveAsk(w.clients(), db, Pace.lookupRunId(now), now, Alerts.NONE, w.config)
                val c = object : CommandContext {
                    override val db = db
                    override val asking = ask
                    override val now = now
                    override fun say(line: String) {}
                }
                ended = LyricsPickCommands.lyrics(c, w.config, w.cacheDir, w.store, picked, null)
                status = db.one("SELECT lyrics_status FROM songs") { it.text(0) }
            }
            files = w.store.libraryDir.walkTopDown().filter { it.isFile }.map { it.name }.toList()
            LookupScenariosReplay.Ran(JsonObject(emptyMap()))
        }, only = setOf(mega))
        assertTrue(ended!!.failed && ended!!.state == "failed", "${ended?.detail}")
        assertTrue(ended!!.detail.startsWith("couldn't note the record in overrides.toml: ") &&
                       ended!!.detail.endsWith("; nothing kept"), ended!!.detail)
        assertTrue(files.none { it.startsWith("lyrics.") }, "$files")
        assertEquals("missing", status)
    }

    /** A clear's lyric file that is a dangling link is removed, as `unlink(missing_ok=True)` removes one. */
    @Test fun aClearRemovesALyricFileThatIsADanglingLink() {
        val case = records.map { it.getValue("case").jsonPrimitive.content }.first { it.startsWith("--clear of LRCLIB") }
        var link: java.nio.file.Path? = null
        var told: JsonObject? = null
        LookupScenariosReplay.replay(PICKS, Misses("a dangling link"), { w ->
            val txt = w.store.libraryDir.walkTopDown().first { it.name == "lyrics.txt" }.toPath()
            java.nio.file.Files.delete(txt)
            java.nio.file.Files.createSymbolicLink(txt, txt.resolveSibling("nowhere"))
            link = txt
            clearing(w).also { told = it.result }
        }, only = setOf(case))
        assertEquals(JsonPrimitive(0), told!!["exit"])
        assertTrue(!java.nio.file.Files.exists(link!!, java.nio.file.LinkOption.NOFOLLOW_LINKS), "$link")
        assertTrue("couldn't be removed" !in told.toString(), "$told")
    }

    /** A phone whose chord models aren't downloaded skips a pick's chords in lyrics_pick.py's PHONE_NOT_DOWNLOADED
     * (audio_sheet.json's words), the "isn't here" record's world with the models' problem the download's. */
    @Test fun aPhoneWithoutTheChordModelsSaysWhereToDownloadThem() {
        val case = records.map { it.getValue("case").jsonPrimitive.content }.first { it.startsWith("a song of its own audio and no sheet") }
        var told: JsonObject? = null
        LookupScenariosReplay.replay(PICKS, Misses("not downloaded"), { w ->
            val display = w.kw.getValue("song").jsonPrimitive.content
            val scope = CoroutineScope(SupervisorJob())
            val path = w.database.read { db -> db.one("SELECT audio_path FROM songs") { it.text(0) }!! }
            w.database.writeBlocking { db -> db.execute("UPDATE songs SET audio_path = ?", File(root, path).path) }
            try {
                val state = File(w.cacheDir.parentFile, "state").apply { mkdirs() }
                val parts = PhoneParts(w.database, w.store, state, { w.config }, JobQueue(scope), MirrorPageData(null),
                                       { w.clients() }, SongPages.NONE, SongbookPages.NONE, Alerts.NONE, w.pacing,
                                       searchesLacuerda = false)
                val t = Told(w.progress)
                runBlocking {
                    LyricsRunner(parts, chords = noModel, problem = { AudioRunner.NOT_DOWNLOADED })
                        .run(JobCommands.lyricsPickSteps(display, "lrclib:77").single().args, t)
                }
                told = JsonObject(t.details)
            } finally {
                scope.cancel()
            }
            LookupScenariosReplay.Ran(JsonObject(emptyMap()))
        }, only = setOf(case))
        val data = Json.parseToJsonElement(File(System.getProperty("caracole.conformance")).parentFile
            .resolve("data/caracole/library/audio_sheet.json").readText()).jsonObject.getValue("words").jsonObject
        assertEquals(data.getValue("phone_not_downloaded"), told!!["chords"])
        assertEquals(0, heardTimes)
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
    @Test fun aPickOverTheSongsOwnAudioHearsItsChordsByTheModels() = pickOverOwnAudio { told, exit, database, heardFrom ->
        val audio = heardFrom!!
        assertEquals(0, exit)
        assertEquals(JsonPrimitive("done"), told.states["lyrics"])
        assertEquals(JsonPrimitive("done"), told.states["chords"], "${told.details}")
        assertEquals(JsonPrimitive("chords over the lyrics"), told.details["chords"])
        database.read { db ->
            val raw = db.one("SELECT raw FROM versions WHERE provider = 'auto'") { it.text(0) }!!
            val made = Json.parseToJsonElement(raw).jsonObject
            assertEquals(JsonPrimitive("phone"), made["made_on"])
            assertEquals(JsonPrimitive("synced"), made["lyrics"])
            val stamps = db.query("SELECT fetched_at FROM versions WHERE provider = 'auto' UNION ALL SELECT " +
                                      "created_at FROM files WHERE name = 'sheet (auto).txt'") { it.text(0)!! }
            assertEquals(1, stamps.toSet().size, "$stamps")
            assertEquals(db.one("SELECT lyrics_at FROM songs") { it.text(0) }, stamps.first())
        }
    }

    /** The song ignored, or given a site's sheet, while its chords were heard (AudioRunner's stillOurs): no auto sheet
     * kept over it, the job refused in the audio job's words (its song stage's, as staged.py `_refuse`). */
    @Test fun aSongIgnoredOrGivenASheetWhileItsChordsWereHeardKeepsNoAutoSheet() {
        pickOverOwnAudio({ database -> database.writeBlocking { db -> db.execute("UPDATE songs SET status = 'ignored'") } }) {
                told, exit, database, heardFrom ->
            assertTrue(heardFrom != null)
            assertEquals(1, exit)
            assertEquals(JsonPrimitive("done"), told.states["lyrics"])
            assertEquals(JsonPrimitive("Nick Cani - Vikingos veganos is ignored (overrides.toml)"), told.details["song"])
            assertEquals(JsonPrimitive("skipped"), told.states["chords"])
            assertEquals(0L, database.read { db -> db.one("SELECT COUNT(*) FROM versions WHERE provider = 'auto'") { it.long(0) } })
        }
        pickOverOwnAudio({ database -> database.writeBlocking { db ->
            val song = db.one("SELECT id FROM songs") { it.long(0)!! }!!
            db.execute("INSERT INTO versions (song_id, provider, slot, kind, tab_id, url, fetched_at) VALUES " +
                           "(?, 'ug', 'sheet', 'chords', '1', 'https://tabs.ultimate-guitar.com/tab/1', " +
                           "'2026-01-01T00:00:00Z')", song)
            val version = db.one("SELECT max(id) FROM versions") { it.long(0)!! }!!
            db.execute("INSERT INTO files (song_id, version_id, name, path, sha256, kept_rank, created_at) VALUES " +
                           "(?, ?, 'sheet.txt', 'Nick Cani/Vikingos veganos/sheet.txt', 'x', 1, " +
                           "'2026-01-01T00:00:00Z')", song, version)
        } }) { told, exit, database, _ ->
            assertEquals(1, exit)
            assertEquals(JsonPrimitive("Nick Cani - Vikingos veganos already has a sheet"), told.details["song"])
            assertEquals(0L, database.read { db -> db.one("SELECT COUNT(*) FROM versions WHERE provider = 'auto'") { it.long(0) } })
        }
    }

    /** A Megalobiz pick over a song with audio of its own on the phone and no auto sheet, the chord models hearing it
     * ([meanwhile] run as they hear), then [check]ed: what was told, the exit, the database, the audio heard. */
    private fun pickOverOwnAudio(meanwhile: (Database) -> Unit = {}, check: (Told, Int, Database, File?) -> Unit) {
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
                var ticks = 0L  // a clock that moves a minute each time it is read: every stamp is the job's own
                val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
                                    monotonic = { 0.0 }, clock = { now.plusSeconds(60 * ticks++) })
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
                        meanwhile(database)
                        return Heard.of(heardRecord)
                    }
                }
                val told = Told(object : Progress { override fun stage(name: String, state: String, detail: String) {} })
                val exit = try {
                    runBlocking {
                        LyricsRunner(parts, chords, AudioStore(state, { _, _ -> error("no file examined") })).run(
                            JobCommands.lyricsPickSteps("Nick Cani - Vikingos veganos", "megalobiz:5001").single().args, told)
                    }
                    0
                } catch (e: CommandExit) {
                    e.code
                }
                check(told, exit, database, heardFrom)
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
