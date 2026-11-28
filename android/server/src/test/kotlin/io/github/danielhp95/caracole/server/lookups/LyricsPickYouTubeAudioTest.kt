package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.Record
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A lyrics pick whose chords stage hears the song's audio when that audio is the file the phone took from YouTube (a
 * YouTube sheet job whose chords failed keeps it three days) keeps the sheet as the YouTube job keeps one, as the
 * computer's pick does (run.py `_generate`: `youtube_audio`, `_from_youtube`): the video credited, `raw.youtube`, the
 * video's address as the version's; and lets that audio go once the sheet is kept (phone-youtube-design.md §5.4).
 */
class LyricsPickYouTubeAudioTest {
    private val records = Corpus.lines("lookup/lyrics_pick.jsonl").filter { it["header"] != JsonPrimitive(true) }

    private class Told : JobContext {
        val states = LinkedHashMap<String, String>()
        val details = LinkedHashMap<String, String>()
        override fun stage(name: String, state: String, detail: String) {
            if (state == "running") return
            states[name] = state
            details[name] = detail
        }
        override fun say(line: String) {}
        override fun outcome(value: JsonObject) {}
        override val isCancelled: Boolean = false
    }

    @Test fun aPickThatHearsYouTubesAudioCreditsTheVideoAndLetsItsAudioGo() {
        val mega = records.first { it.getValue("case").jsonPrimitive.content.startsWith("Megalobiz's record") }
        val heardRecord = records.first { it.getValue("case").jsonPrimitive.content.startsWith("LRCLIB's record") }
            .getValue("out").jsonObject.getValue("rows").jsonObject.getValue("versions").jsonArray
            .map { Json.parseToJsonElement(it.jsonObject.getValue("raw").jsonPrimitive.content).jsonObject }
            .first { "heard" in it }.getValue("heard")
        val dir = Files.createTempDirectory("caracole-pick-yt").toFile()
        val scope = CoroutineScope(SupervisorJob())
        try {
            val now = Instant.parse(mega.getValue("now").jsonPrimitive.content)
            val library = File(dir, "library").apply { mkdirs() }
            val state = File(dir, "state").apply { mkdirs() }
            val cache = File(state, "cache")
            val folder = YouTubeAudio.folder(cache)
            val video = Video("dQw4w9WgXcQ", "Vikingos veganos (Official Video)", "Nick Cani", 201.0)
            val audio = File(folder, YouTubeAudio.name(1, video.id, ".m4a")).apply { parentFile.mkdirs(); writeBytes(ByteArray(64)) }
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, mega.getValue("fixture").jsonArray.map { it.jsonObject }, library)
                    val id = db.one("SELECT id FROM songs") { it.long(0)!! }!!
                    assertEquals(1L, id)
                    db.execute("UPDATE songs SET audio_path = ?, audio_mtime = 1.0", audio.path)
                    // The phone's YouTube record of the song: the video pasted, its audio the linked file.
                    Records.save(db, id, Record(video = video, source = "pasted", audio = audio.path,
                                                 downloadedAt = "2026-11-27T10:00:00Z"))
                    assertNotNull(YouTubeAudio.youtubeAudio(db, Songs.byId(db, id)!!), "the song's audio is YouTube's")
                }
                val answers = mega.getValue("answers").jsonObject.mapValues { (_, a) ->
                    val o = a.jsonObject
                    HttpAnswer(o.getValue("status").jsonPrimitive.content.toInt(),
                               o.getValue("headers").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content },
                               Scenarios.body(o.getValue("body")))
                }
                var ticks = 0L
                val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
                                    monotonic = { 0.0 }, clock = { now.plusSeconds(60 * ticks++) })
                val http = File(dir, "http")
                val parts = PhoneParts(database, LibraryStore(library, File(state, AudioStore.FOLDER), folder), state,
                                       { PhoneConfig.DEFAULTS }, JobQueue(scope), MirrorPageData(null),
                                       { Clients(PhoneConfig.DEFAULTS, http, { FakeTransport(answers) }, pacing) },
                                       SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
                var heardFrom: File? = null
                val chords = object : ChordModels {
                    override fun ready(): String? = null
                    override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
                        heardFrom = audio
                        return Heard.of(heardRecord)
                    }
                }
                val told = Told()
                val exit = try {
                    runBlocking {
                        LyricsRunner(parts, chords, AudioStore(state, { _, _ -> error("no file examined") })).run(
                            JobCommands.lyricsPickSteps("Nick Cani - Vikingos veganos", "megalobiz:5001").single().args, told)
                    }
                    0
                } catch (e: CommandExit) {
                    e.code
                }
                assertEquals(0, exit, "${told.details}")
                assertEquals("done", told.states["chords"], "${told.details}")
                assertEquals(audio, heardFrom, "the pick heard the audio the phone took from YouTube")
                database.read { db ->
                    val (url, rawText) = db.one("SELECT url, raw FROM versions WHERE provider = 'auto'") { it.text(0) to it.text(1)!! }!!
                    val raw = Json.parseToJsonElement(rawText).jsonObject
                    val sheet = File(library, "Nick Cani/Vikingos veganos/sheet (auto).txt").readText()
                    assertTrue("youtube" in raw, "the sheet's version keeps the video it was heard from (raw.youtube): ${raw.keys}")
                    assertEquals(video.id, Records.videoOf(raw["youtube"])?.id, "raw.youtube is the video's")
                    assertEquals(video.url, url, "the version's address is the video's")
                    assertTrue("Audio from YouTube" in sheet, "the sheet credits the video")
                    val after = Songs.byId(db, 1L)!!
                    assertNull(after.audioPath, "the video's audio is let go once its sheet is kept")
                    val record = Records.load(db, 1L)
                    assertNull(record.audio, "the record names no audio any more")
                    assertEquals(video.id, record.video?.id, "the record keeps its video")
                }
                assertFalse(audio.exists(), "the video's audio file is deleted")
            }
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
    }
}
