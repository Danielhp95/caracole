package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.Records
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.Closeable
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole youtube --sheet` on the phone through the real queue, with a fake yt-dlp: what only the phone does (the
 * replay, YouTubeSheetReplayTest, holds the stages to Python's): a lookup queued during the download runs first, the
 * audio let go once the sheet is kept, a run that never started a wait counted against nothing, a stop mid-download
 * stopping yt-dlp and keeping nothing, a download the phone can't decode said so, and the decoded length said. The
 * song's lyrics are instrumental, so that no site is asked. */
class YouTubeSheetRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private val display = "Calla Lake - River Road"
    private val video = "RiverRoad01"
    private val url = "https://www.youtube.com/watch?v=$video"

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val store: AudioStore, val database: Database,
                        val runners: MutableMap<String, CommandRunner>, val scope: CoroutineScope)

    private fun phone(scope: CoroutineScope = this.scope): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        val store = AudioStore(parts.stateDir, { _, _ -> AudioStore.Audio("M4A", 213.0, emptyMap()) })
        database.writeBlocking { db ->
            val song = parts.store.add(db, "Calla Lake", "River Road", now = Stamps.now())
            Versions.updateSong(db, song.id, mapOf("lyrics_status" to "instrumental"))
        }
        return Phone(parts, queue, store, database, runners, scope)
    }

    private fun folder(phone: Phone) = YouTubeAudio.folder(File(phone.parts.stateDir, "cache"))

    /** A yt-dlp of one download: [during] before it answers (on the run's own thread), then the audio written where
     * `-o` says and its line printed; or [notStarted]. [closed] once the job closed it. */
    private class Downloader(val during: () -> Unit = {}, val notStarted: String? = null) : YtDlpProcess, Closeable {
        val closed = CountDownLatch(1)
        val ran = CopyOnWriteArrayList<List<String>>()

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            notStarted?.let { throw YtDlpProcess.NotStarted(it) }
            ran += argv
            during()
            if (closed.count == 0L) throw java.util.concurrent.CancellationException("yt-dlp was stopped")
            val file = File(argv[argv.indexOf("-o") + 1].replace("%(ext)s", "m4a"))
            file.writeBytes(ByteArray(4096) { it.toByte() })
            val line = """{"id": "RiverRoad01", "title": "Calla Lake - River Road", "channel": "Calla Lake", """ +
                """"duration": 213, "filepath": "${file.path}"}"""
            return Ran(0, line + "\n", "")
        }

        override fun close() = closed.countDown()
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

    private class Models(val heard: Heard, val fail: Boolean = false) : ChordModels {
        override fun ready(): String? = null
        override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
            onStep("setting up the models")
            if (fail) throw AudioUnreadable("its fragments can't be read")
            return heard
        }
    }

    private fun runner(phone: Phone, process: YtDlpProcess, models: ChordModels = Models(heard)) =
        YouTubeSheetRunner(phone.parts, Engine(process, File(phone.parts.stateDir, "cache")), models, phone.store,
                           problem = { null }, chordsProblem = { null })

    private fun spec(): JobSpec {
        val commands = listOf(Command("Making the sheet",
                                      listOf("youtube", "--sheet", "--progress", "--url=$url", "--song=$display")))
        return JobSpec("Sheet from a YouTube video: $display", JobCommands.YOUTUBE_SHEET + "calla-lake/river-road",
                       "song", JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
    }

    private fun run(phone: Phone, runner: YouTubeSheetRunner): Job = runBlocking {
        phone.runners[YouTubeSheetRunner.COMMAND] = runner
        val job = phone.queue.submit(spec()).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    private fun ends(job: Job): Map<String, Pair<String, String>> = job.stages.associate { it.name to (it.state to it.detail) }

    /** The design's §5.5: the download holds no write, and a lookup queued meanwhile runs while yt-dlp does; then the
     * sheet is kept and the video's audio let go (§5.4). */
    @Test fun aLookupQueuedDuringTheDownloadRunsFirstAndTheAudioGoesOnceTheSheetIsKept() {
        val phone = phone()
        val log = CopyOnWriteArrayList<String>()
        val looked = CountDownLatch(1)
        phone.runners["get"] = CommandRunner { args, _ ->
            phone.database.writeBlocking { }  // a lookup writes: no write of the job's is held
            log += "get ${args.last()}"
            looked.countDown()
        }
        val process = Downloader(during = {
            runBlocking {
                phone.queue.submit(JobSpec("Get Harbour Lights - Paper Boats", "harbour-lights/paper-boats", "song",
                                           emptyList(), commands = JobCommands.lookupSteps("Harbour Lights", "Paper Boats"),
                                           fetching = true))
            }
            log += "downloading"
            assertTrue(looked.await(20, TimeUnit.SECONDS), "the lookup never ran during the download")
            log += "downloaded"
        })
        val job = run(phone, runner(phone, process))
        assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
        assertEquals(listOf("downloading", "get Paper Boats", "downloaded"), log)
        val ends = ends(job)
        assertEquals("done" to "downloaded Calla Lake - River Road (Calla Lake), $url", ends["audio"])
        assertEquals("done" to "chords only, no lyrics", ends["chords"])
        assertTrue(job.steps.single().output.any { it == "decoded 212.98 s of audio; yt-dlp said the video is 213.00 s" },
                   "${job.steps.single().output}")
        assertEquals(1, process.ran.size)
        phone.database.read { db ->
            val song = Songs.byKey(db, "calla-lake/river-road")!!
            assertTrue(Kept.keptFiles(db, song.id).any { it.name == "sheet (auto).txt" })
            assertNull(song.audioPath)
            assertNull(Records.load(db, song.id).audio)
            assertEquals(video, Records.load(db, song.id).video?.id)
            val raw = Versions.get(db, 1)!!.raw
            assertEquals(JsonPrimitive("phone"), raw["made_on"])
            assertEquals(JsonPrimitive(video), (raw["youtube"] as JsonObject)["id"])
            assertFalse("audio_name" in raw)
        }
        assertEquals(emptyList(), folder(phone).listFiles().orEmpty().map { it.name })
    }

    /** One run at a time across the app: a run the debug bench holds is NotStarted, a wait in words that say to try
     * again, counted against nothing (no error on the record, no failure of the video), exit 0. */
    @Test fun aRunThatNeverStartedIsAWaitCountedAgainstNothing() {
        val phone = phone()
        val process = Downloader(notStarted = "another run is going in the app")
        val job = run(phone, runner(phone, process))
        assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
        assertEquals(Job.FAILED to "yt-dlp didn't start (another run is going in the app); try again in a moment",
                     ends(job)["audio"])
        phone.database.read { db ->
            val record = Records.load(db, 1)
            assertNull(record.error)
            assertEquals(emptyMap(), record.failures)
            assertEquals(0L, db.one("SELECT COUNT(*) FROM events WHERE provider = 'youtube'") { it.long(0) })
        }
    }

    /** A stop of the queue mid-download stops yt-dlp (its process closed) and ends the job interrupted, nothing
     * kept: no audio linked, no file, no download's own folder. */
    @Test fun aStopMidDownloadStopsYtDlpAndKeepsNothing() {
        val own = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val phone = phone(own)
        val started = CountDownLatch(1)
        lateinit var process: Downloader
        process = Downloader(during = {
            started.countDown()
            assertTrue(process.closed.await(30, TimeUnit.SECONDS), "yt-dlp was never stopped")
        })
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, process)
        val job = phone.queue.submit(spec()).first
        assertTrue(started.await(30, TimeUnit.SECONDS))
        own.cancel()
        assertTrue(process.closed.await(30, TimeUnit.SECONDS))
        runBlocking {
            withTimeout(30_000) { while (phone.queue.job(job.id)?.state != Job.INTERRUPTED) kotlinx.coroutines.delay(20) }
        }
        phone.database.read { db -> assertNull(Songs.byKey(db, "calla-lake/river-road")!!.audioPath) }
        assertEquals(emptyList(), folder(phone).listFiles().orEmpty().map { it.name })
    }

    /** A download the phone can't decode (a fragmented MP4 whose fragments can't be read, Mp4's refusal) fails the
     * chords in the audio-unreadable words, never as a bug; its audio kept for Try again. */
    @Test fun aDownloadThePhoneCantDecodeIsSaidSoNeverABug() {
        val phone = phone()
        val job = run(phone, runner(phone, Downloader(), Models(heard, fail = true)))
        assertEquals(Job.FAILED, job.state)
        assertEquals(Job.FAILED to "audio the phone can't read: its fragments can't be read", ends(job)["chords"])
        assertEquals(listOf("1-$video.m4a"), folder(phone).listFiles().orEmpty().map { it.name })
    }
}
