package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.Due
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/**
 * Byoutube-6: a YouTube download the phone can't hear is noted (kv `youtube-unheard:<id>`), so that once the 3-day sweep
 * lets its audio go the automatic pass ([Due.songs]) never downloads the same video again; another video, or 30 days,
 * make the song due again, and a sheet kept forgets the note.
 */
class YouTubeUnheardTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private val display = "Calla Lake - River Road"
    private val key = "calla-lake/river-road"
    private val video = "RiverRoad01"
    private val url = "https://www.youtube.com/watch?v=$video"

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val store: AudioStore, val database: Database,
                        val runners: MutableMap<String, CommandRunner>)

    /** A phone with the song, its lyrics an instrumental's; no pause sleeps; every site answers 404. */
    private fun phone(): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val base = TestParts.of(database, dir, scope, queue)
        val quick = Pacing.REAL.copy(sleep = { })
        val parts = PhoneParts(base.database, base.store, base.stateDir, base.config, base.queue, base.cards,
                               { Clients(PhoneConfig.DEFAULTS, File(base.stateDir, "cache"),
                                         { _ -> Transport { _ -> HttpAnswer(404, emptyList(), ByteArray(0)) } },
                                         quick) },
                               base.pages, base.songbooks, base.alerts, quick, base.searchesLacuerda)
        val store = AudioStore(parts.stateDir, { _, _ -> AudioStore.Audio("M4A", 213.0, emptyMap()) })
        database.writeBlocking { db ->
            val song = parts.store.add(db, "Calla Lake", "River Road", now = Stamps.now())
            Versions.updateSong(db, song.id, mapOf("match_decision" to "not_found", "lyrics_status" to "instrumental"))
        }
        return Phone(parts, queue, store, database, runners)
    }

    private class Engine(val process: YtDlpProcess, val cache: File) : YouTubeEngine {
        override fun ready(): String? = null
        override fun process(): YtDlpProcess = process
        override fun gate(): YtDlpGate = object : YtDlpGate {
            override val proxyArg = "http://test:secret@127.0.0.1:9"
            override fun log(): Map<String, HostGate.HostUse> = emptyMap()
            override fun close() {}
        }
        override val qjs = File("/qjs")
        override val cacheDir = cache
    }

    private val heard = Heard(1, 212.98, listOf(ChordSegment(0.0, 10.0, "Am"), ChordSegment(10.0, 20.0, "F")),
                              (0..40).map { it * 0.5 }, (0..10).map { it * 2.0 })

    private class Models(val heard: Heard, val fail: Boolean) : ChordModels {
        override fun ready(): String? = null
        override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
            if (fail) throw AudioUnreadable("its fragments can't be read")
            return heard
        }
    }

    /** A yt-dlp of one download that works. */
    private class Downloader : YtDlpProcess {
        val ran = CopyOnWriteArrayList<List<String>>()

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            ran += argv
            val file = File(argv[argv.indexOf("-o") + 1].replace("%(ext)s", "m4a"))
            file.writeBytes(ByteArray(4096) { it.toByte() })
            return Ran(0, """{"id": "RiverRoad01", "title": "Calla Lake - River Road", "channel": "Calla Lake", """ +
                """"duration": 213, "filepath": "${file.path}"}""" + "\n", "")
        }
    }

    private fun runner(phone: Phone, process: YtDlpProcess, fail: Boolean) =
        YouTubeSheetRunner(phone.parts, Engine(process, File(phone.parts.stateDir, "cache")), Models(heard, fail),
                           phone.store, problem = { null }, chordsProblem = { null })

    private fun pasted(): JobSpec {
        val commands = listOf(Command("Making the sheet",
                                      listOf("youtube", "--sheet", "--progress", "--url=$url", "--song=$display")))
        return JobSpec("Sheet from a YouTube video: $display", JobCommands.YOUTUBE_SHEET + key, "song",
                       JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
    }

    private fun run(phone: Phone, spec: JobSpec): Job = runBlocking {
        withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
    }

    private fun ends(job: Job): Map<String, Pair<String, String>> = job.stages.associate { it.name to (it.state to it.detail) }

    private fun songId(phone: Phone): Long = phone.database.read { db -> Songs.byKey(db, key)!!.id }

    private fun due(phone: Phone, now: Instant): List<String> = phone.database.read { db ->
        Due.songs(db, Overrides.read(db), now, paired = false).map { it.display }
    }

    private fun sweep(phone: Phone, at: Instant) {
        val folder = YouTubeAudio.folder(File(phone.parts.stateDir, "cache"))
        phone.database.writeBlocking { db -> YouTubeAudio.sweep(db, folder, at, Stamps.of(at)) }
    }

    @Test fun aSongWhoseAudioThePhoneCantHearIsNotDueAgainOnceItsAudioIsSwept() {
        val phone = phone()
        val ytdlp = Downloader()
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, ytdlp, fail = true)
        val now = Instant.now()
        assertEquals(listOf(display), due(phone, now), "due before anything")
        val job = run(phone, pasted())
        assertEquals(Job.FAILED to "audio the phone can't read: its fragments can't be read", ends(job)["chords"])
        val note = phone.database.read { db -> db.kvGet("youtube-unheard:${songId(phone)}") }
        assertNotNull(note, "the video the phone couldn't hear is noted")
        val read = Json.parseToJsonElement(note).jsonObject
        assertEquals(video, read.getValue("video").jsonPrimitive.content)
        assertEquals("audio the phone can't read: its fragments can't be read", read.getValue("error").jsonPrimitive.content)
        assertEquals(emptyList(), due(phone, now), "its audio is kept: not due")
        val later = now.plus(Duration.ofDays(4))
        sweep(phone, later)
        assertEquals(emptyList(), due(phone, later),
                     "after the 3-day sweep the song the phone couldn't hear is due again: the automatic pass " +
                         "downloads the same video again (downloads so far: ${ytdlp.ran.size})")
        assertEquals(listOf(display), due(phone, now.plus(Duration.ofDays(31))), "30 days on, tried again")
        phone.database.writeBlocking { db ->
            OverrideWriters.addYoutube(db, display, "https://www.youtube.com/watch?v=RiverRoad02")
        }
        assertEquals(listOf(display), due(phone, later), "another video pasted: due again")
    }

    @Test fun aSheetKeptForgetsTheNote() {
        val phone = phone()
        val ytdlp = Downloader()
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, ytdlp, fail = true)
        assertEquals(Job.FAILED, ends(run(phone, pasted()))["chords"]?.first)
        val id = songId(phone)
        assertNotNull(phone.database.read { db -> db.kvGet("youtube-unheard:$id") })
        // Try again, the models hearing it this time (the audio still kept: no download)
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, ytdlp, fail = false)
        val again = run(phone, pasted())
        assertEquals(Job.DONE, again.state, "${again.stages.map { it.name to it.detail }}")
        assertEquals(1, ytdlp.ran.size)
        assertNull(phone.database.read { db -> db.kvGet("youtube-unheard:$id") }, "a sheet kept forgets the note")
    }
}
