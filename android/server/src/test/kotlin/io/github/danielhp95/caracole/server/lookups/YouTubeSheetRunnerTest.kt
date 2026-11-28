package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Health
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
import io.github.danielhp95.caracole.server.routes.library.NamedSong
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

    private class Engine(val process: YtDlpProcess, val cache: File, override val version: String? = null) : YouTubeEngine {
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

    /** A sheet from a video asked for by name, of a song the library hasn't: the job adds it with the album and the
     * length the request named (its spec's song, as caracole serve's wanted.txt line keeps them), so LRCLIB is asked
     * with that length; a request's song of another name adds nothing of it. */
    @Test fun aSongAddedByNameKeepsTheAlbumAndLengthItsRequestNamed() {
        val phone = phone()
        val named = "Nueva Banda - Canción"
        val commands = listOf(Command("Making the sheet",
                                      listOf("youtube", "--sheet", "--progress", "--url=$url", "--song=$named")))
        val spec = JobSpec("Sheet from YouTube: $named", JobCommands.YOUTUBE_SHEET + "nueva-banda/cancion", "song",
                           JobCommands.stages(commands.map { it.args }), display = named, commands = commands,
                           song = NamedSong("Nueva Banda", "Canción", "Un Disco", 225_000))
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, Downloader())
        val job = runBlocking { withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) } }
        assertEquals("done", ends(job)["song"]?.first, "${job.steps.single().output}")
        phone.database.read { db ->
            val song = Songs.byKey(db, "nueva-banda/cancion")!!
            assertEquals("Un Disco", song.album)
            assertEquals(225_000L, song.durationMs)
            val asked = db.query("SELECT url FROM events WHERE provider = 'lrclib'") { it.text(0)!! }
            assertTrue(asked.isNotEmpty() && asked.all { "duration=225" in it }, "$asked")
        }
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
        phone.database.read { db ->
            assertNull(Songs.byKey(db, "calla-lake/river-road")!!.audioPath)
            // The run cut off is recorded once, by the runner alone: one error event, its time the next pause's.
            assertEquals(listOf("error"), db.query("SELECT decision FROM events WHERE provider = 'youtube'") { it.text(0) })
            assertTrue(db.kvGet("http:last_request:youtube") != null)
        }
        assertEquals(emptyList(), folder(phone).listFiles().orEmpty().map { it.name })
    }

    /** yt-dlp out of date, or the app's gate refusing a host, is no fault of the video's (YtDlp's KDoc): the audio
     * stage ends in their words, a wait (exit 0), nothing counted against the video. */
    @Test fun anOutOfDateYtDlpOrAGateRefusalIsCountedAgainstNoVideo() {
        for ((stderr, words) in listOf(
            "ERROR: [youtube] $video: Unable to extract yt initial data" to "[youtube] $video: Unable to extract yt initial data",
        )) {
            val phone = phone()
            val process = object : YtDlpProcess {
                override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit) =
                    Ran(1, "", stderr + "\n")
            }
            val job = run(phone, runner(phone, process))
            assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
            assertEquals(Job.FAILED to words, ends(job)["audio"])
            phone.database.read { db -> assertEquals(emptyMap(), Records.load(db, 1).failures) }
        }
        val phone = phone()
        val refusing = object : YouTubeEngine {
            override fun ready(): String? = null
            override fun process(): YtDlpProcess = object : YtDlpProcess {
                override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit) =
                    Ran(1, "", "ERROR: Unable to download webpage: HTTP Error 403: Forbidden\n")
            }
            override fun gate(): YtDlpGate = object : YtDlpGate {
                private var asked = 0
                override val proxyArg = "http://test:secret@127.0.0.1:9"
                override fun log(): Map<String, HostGate.HostUse> =
                    if (asked++ == 0) emptyMap() else mapOf("ads.example" to HostGate.HostUse(refused = 1))
                override fun close() {}
            }
            override val qjs = File("/qjs")
            override val cacheDir = File(phone.parts.stateDir, "cache")
        }
        val job = run(phone, YouTubeSheetRunner(phone.parts, refusing, Models(heard), phone.store, problem = { null },
                                                chordsProblem = { null }))
        assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
        assertEquals(Job.FAILED, ends(job)["audio"]?.first)
        assertTrue("ads.example" in ends(job)["audio"]!!.second, "${ends(job)["audio"]}")
        phone.database.read { db ->
            assertEquals(emptyMap(), Records.load(db, 1).failures)
            assertNull(Health.state(db, "youtube").cooldownUntil)  // a refusal of the gate's is never a block
        }
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

    /** yt-dlp out of date (the design's §7): two videos it can't read within 24 hours set it for this version, told
     * once; the audio stage says the phone's words, and so does the job's outcome; a job asked for now still runs, its
     * audio stage warning first. */
    @Test fun twoVideosYtDlpCantReadSetOutOfDateToldOnceAndAskedNowStillRuns() {
        val phone = phone()
        val told = CopyOnWriteArrayList<String>()
        val alerts = object : io.github.danielhp95.caracole.core.health.Alerts {
            override fun blocked(provider: String, until: java.time.Instant?, message: String) {}
            override fun failed(title: String, line: String) {}
            override fun outdated(version: String, words: String) { told += "$version: $words" }
        }
        val parts = PhoneParts(phone.parts.database, phone.parts.store, phone.parts.stateDir, phone.parts.config,
                               phone.parts.queue, phone.parts.cards, phone.parts.clients, phone.parts.pages,
                               phone.parts.songbooks, alerts, phone.parts.pacing, phone.parts.searchesLacuerda)
        val outdated = object : YtDlpProcess {
            override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit) =
                Ran(1, "", "ERROR: [youtube] x: Unable to extract yt initial data\n")
        }
        val words = "YouTube changed what yt-dlp 2026.11.23 reads: caracole's next release brings a fix"
        fun runner(process: YtDlpProcess) = YouTubeSheetRunner(parts, Engine(process, File(parts.stateDir, "cache"), "2026.11.23"),
                                                               Models(heard), phone.store, problem = { null }, chordsProblem = { null })
        fun sheet(id: String): Job = runBlocking {
            phone.runners[YouTubeSheetRunner.COMMAND] = runner(if (id == "ok") Downloader() else outdated)
            val target = "https://www.youtube.com/watch?v=" + if (id == "ok") video else id
            val commands = listOf(Command("Making the sheet", listOf("youtube", "--sheet", "--progress", "--url=$target",
                                                                     "--song=$display")))
            val spec = JobSpec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + "calla-lake/river-road", "song",
                               JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
            withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
        }
        val first = sheet("FirstVideo1")
        assertEquals(Job.FAILED to words, ends(first)["audio"])
        assertEquals(emptyList(), told, "one video: not yet")
        val second = sheet("SecondVid02")
        assertEquals(Job.FAILED to words, ends(second)["audio"])
        assertEquals(listOf("2026.11.23: $words"), told)
        val outcome = io.github.danielhp95.caracole.server.jobs.Outcomes.outcome(
            second, io.github.danielhp95.caracole.server.jobs.JobViews.line(second))
        assertTrue(words in outcome.reason, "$outcome")
        phone.database.read { db ->
            assertEquals("Unable to extract yt initial data".let { "[youtube] x: $it" },
                         io.github.danielhp95.caracole.core.youtube.Outdated.state(db, "2026.11.23", java.time.Instant.now()))
        }
        sheet("ThirdVideo3")
        assertEquals(1, told.size, "told once a version")
        // Asked for now, a job still runs, warning first: said before its download starts.
        var saidBefore: List<String>? = null
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(Downloader(during = {
            saidBefore = phone.queue.snapshot().first { it.state == Job.RUNNING }.steps.single().output
        }))
        val now = runBlocking {
            val commands = listOf(Command("Making the sheet", listOf("youtube", "--sheet", "--progress", "--url=$url",
                                                                     "--song=$display")))
            val spec = JobSpec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + "calla-lake/river-road", "song",
                               JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
            withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
        }
        assertEquals("done", ends(now)["audio"]?.first, "${now.steps.single().output}")
        assertTrue(saidBefore.orEmpty().contains(words), "said before the download: $saidBefore")
    }

    /** A video passed over (no m4a stream, the phone's PHONE_PASS_OVER) is no sign of yt-dlp out of date: two of them,
     * on two videos, leave Outdated.state null and tell nobody. */
    @Test fun twoPassOversSetNoOutOfDate() {
        val phone = phone()
        val told = CopyOnWriteArrayList<String>()
        val alerts = object : io.github.danielhp95.caracole.core.health.Alerts {
            override fun blocked(provider: String, until: java.time.Instant?, message: String) {}
            override fun failed(title: String, line: String) {}
            override fun outdated(version: String, words: String) { told += version }
        }
        val parts = PhoneParts(phone.parts.database, phone.parts.store, phone.parts.stateDir, phone.parts.config,
                               phone.parts.queue, phone.parts.cards, phone.parts.clients, phone.parts.pages,
                               phone.parts.songbooks, alerts, phone.parts.pacing, phone.parts.searchesLacuerda)
        val passOver = object : YtDlpProcess {
            override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit) =
                Ran(1, "", "ERROR: [youtube] x: Requested format is not available. Use --list-formats for a list of available formats\n")
        }
        for (id in listOf("FirstVideo1", "SecondVid02")) {
            phone.runners[YouTubeSheetRunner.COMMAND] = YouTubeSheetRunner(parts, Engine(passOver, File(parts.stateDir, "cache"),
                                                                                         "2026.11.23"), Models(heard),
                                                                           phone.store, problem = { null }, chordsProblem = { null })
            val commands = listOf(Command("Making the sheet", listOf("youtube", "--sheet", "--progress",
                                                                     "--url=https://www.youtube.com/watch?v=$id", "--song=$display")))
            val spec = JobSpec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + "calla-lake/river-road", "song",
                               JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
            runBlocking { withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) } }
        }
        phone.database.read { db ->
            assertNull(io.github.danielhp95.caracole.core.youtube.Outdated.state(db, "2026.11.23", java.time.Instant.now()))
            assertNull(db.kvGet(io.github.danielhp95.caracole.core.youtube.Outdated.HITS))
        }
        assertEquals(emptyList(), told)
    }

    /** Byoutube-4. An automatic job checks again, as it reads its song, that the song keeps no sheet (Due.songs' rule,
     * R1 as amended: "never for a song with any auto sheet"): one whose song got another caracole's auto sheet between
     * the pass's pick and the job's run (a sync's take queued before it) is refused in its song stage, no yt-dlp run,
     * the sheet as it was. Here the sheet is made "elsewhere" by giving this side another id after a first job made it. */
    @Test fun anAutomaticJobTakesNoAudioForASongThatKeepsAnotherCaracolesAutoSheet() {
        val phone = phone()
        val ytdlp = Downloader()
        val first = run(phone, runner(phone, ytdlp))
        assertEquals(Job.DONE, first.state, "${first.steps.single().output}")
        assertEquals(1, ytdlp.ran.size)
        fun madeBy() = phone.database.read { db ->
            db.one("SELECT raw FROM versions WHERE song_id = 1 AND provider = 'auto'") { it.text(0) }
        }.orEmpty().substringAfter("\"made_by\"").take(24)
        val before = madeBy()
        phone.database.writeBlocking { db -> db.kvSet("sync:id", "ffffffffffffffff") }
        val job = runBlocking {
            withTimeout(60_000) {
                phone.queue.await(phone.queue.submit(YouTubeAuto.spec(display, "calla-lake/river-road")).first.id)
            }
        }
        assertEquals(1, ytdlp.ran.size, "the automatic job ran yt-dlp; its stages: ${ends(job)}")
        assertEquals(Job.FAILED to YouTubeSheetRunner.HAS_SHEET.replace("{display}", display), ends(job)["song"])
        assertEquals(Job.SKIPPED, ends(job)["audio"]?.first)
        assertEquals(before, madeBy(), "the other caracole's auto sheet was replaced")
    }
}
