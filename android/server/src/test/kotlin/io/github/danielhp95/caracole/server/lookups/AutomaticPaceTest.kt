package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.HttpRequest
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
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
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * An automatic YouTube job's lyrics stage asks at the bulk pace (the design's §5.3): LRCLIB, Megalobiz and AZLyrics
 * through each provider's own `budget` and `delay`, under a run of its own (`youtube-auto:<UTC>:<song id>`), so never
 * within `lookup_per_hour` and never counted as a lookup, and still within Megalobiz's `per_day`; a job asked for now
 * keeps the lookup pace. The sites refuse every request (an error each, recorded), a draw of the pause recorded.
 */
class AutomaticPaceTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private val display = "Calla Lake - River Road"
    private val url = "https://www.youtube.com/watch?v=RiverRoad01"
    private val lyricsSites = listOf("lrclib", "megalobiz", "azlyrics")

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val database: Database,
                        val runners: MutableMap<String, CommandRunner>, val draws: List<Pair<Double, Double>>,
                        val asked: List<String>)

    private fun phone(answer: (String) -> HttpAnswer? = { null },
                      seed: (io.github.danielhp95.caracole.core.db.Db, Instant) -> Unit = { _, _ -> }): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val draws = CopyOnWriteArrayList<Pair<Double, Double>>()
        val asked = CopyOnWriteArrayList<String>()
        val pacing = Pacing.REAL.copy(sleep = {}, draws = Draws { low, high -> draws += low to high; low })
        val refusing = object : Transport {
            override fun send(request: HttpRequest): HttpAnswer {
                asked += request.url
                answer(request.url)?.let { return it }
                throw TransportError("refused", "no site from a test: ${request.url}")
            }
        }
        val state = File(dir, "state").apply { mkdirs() }
        val parts = PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                               MirrorPageData(null),
                               { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { refusing }, pacing) },
                               SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
        database.writeBlocking { db ->
            parts.store.add(db, "Calla Lake", "River Road", now = Stamps.now())
            val now = Instant.now()
            for (site in lyricsSites) db.kvSet(Pace.LAST_SENT + site, "%.3f".format(java.util.Locale.ROOT, now.toEpochMilli() / 1000.0))
            seed(db, now)
        }
        return Phone(parts, queue, database, runners, draws, asked)
    }

    private val heard = Heard(1, 212.98, listOf(ChordSegment(0.0, 10.0, "Am")), (0..40).map { it * 0.5 },
                              (0..10).map { it * 2.0 })

    private fun runner(phone: Phone, metered: () -> Boolean = { false }): YouTubeSheetRunner {
        val process = object : YtDlpProcess {
            override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
                val file = File(argv[argv.indexOf("-o") + 1].replace("%(ext)s", "m4a"))
                file.writeBytes(ByteArray(4096) { it.toByte() })
                return Ran(0, """{"id": "RiverRoad01", "title": "River Road", "channel": "Calla Lake", "duration": 213, """ +
                    """"filepath": "${file.path}"}""" + "\n", "")
            }
        }
        val engine = object : YouTubeEngine {
            override fun ready(): String? = null
            override fun process(): YtDlpProcess = process
            override fun gate(): YtDlpGate = object : YtDlpGate {
                override val proxyArg = "http://test:secret@127.0.0.1:9"
                override fun log(): Map<String, HostGate.HostUse> = emptyMap()
                override fun close() {}
            }
            override val qjs = File("/qjs")
            override val cacheDir = File(phone.parts.stateDir, "cache")
        }
        val models = object : ChordModels {
            override fun ready(): String? = null
            override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard = heard
        }
        return YouTubeSheetRunner(phone.parts, engine, models,
                                  AudioStore(phone.parts.stateDir, { _, _ -> AudioStore.Audio("M4A", 213.0, emptyMap()) }),
                                  problem = { null }, chordsProblem = { null }, metered = metered)
    }

    private fun run(phone: Phone, automatic: Boolean, metered: () -> Boolean = { false }): Job = runBlocking {
        phone.runners[YouTubeSheetRunner.COMMAND] = runner(phone, metered)
        val commands = listOf(Command("Making the sheet",
                                      listOf("youtube", "--sheet", "--progress", "--url=$url", "--song=$display")))
        val spec = JobSpec("Sheet from a YouTube video: $display", JobCommands.YOUTUBE_SHEET + "calla-lake/river-road",
                           "song", JobCommands.stages(commands.map { it.args }), display = display, commands = commands,
                           automatic = automatic)
        withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
    }

    /** The lyrics sites' events since the seed: (provider, run, decision). */
    private fun events(phone: Phone): List<Triple<String, String, String>> = phone.database.read { db ->
        db.query("SELECT provider, run, decision FROM events WHERE provider IN ('lrclib', 'megalobiz', 'azlyrics') " +
                     "AND run NOT LIKE '%seed' ORDER BY id") { Triple(it.text(0)!!, it.text(1)!!, it.text(2)!!) }
    }

    private fun seedLookups(db: io.github.danielhp95.caracole.core.db.Db, now: Instant, provider: String, n: Int,
                            run: String = "lookup:seed") {
        repeat(n) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, 'u', 200, 'ok')",
                       run, Stamps.of(now.minusSeconds(60)), provider)
        }
    }

    @Test fun anAutomaticJobsLyricsAskUnderARunOfItsOwnAtTheBulkPaceOutsideTheHoursLookups() {
        // The hour's lookups of LRCLIB spent: a lookup would ask it nothing, the automatic job still does.
        val phone = phone(seed = { db, now -> seedLookups(db, now, "lrclib", PhoneConfig.DEFAULTS.provider("lrclib").lookupPerHour) })
        val job = run(phone, automatic = true)
        assertEquals("done", job.stages.first { it.name == "song" }.state, "${job.steps.single().output}")
        val events = events(phone)
        assertEquals(lyricsSites, events.map { it.first }.distinct(), "$events")
        val runs = events.map { it.second }.toSet()
        assertEquals(1, runs.size, "$runs")
        assertTrue(Regex("""youtube-auto:\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ:1""").matches(runs.single()), "$runs")
        phone.database.read { db ->
            assertEquals(PhoneConfig.DEFAULTS.provider("lrclib").lookupPerHour,
                         Pace.lookupRequestsUsed(db, "lrclib", Instant.now()))  // untouched: only the seed's
        }
        for (site in lyricsSites) {
            val p = PhoneConfig.DEFAULTS.provider(site)
            if (p.delay != p.lookupDelay) assertTrue(p.lookupDelay !in phone.draws, "$site drew at the lookup pace")
        }
        assertTrue(PhoneConfig.DEFAULTS.provider("lrclib").delay in phone.draws, "${phone.draws}")
        assertTrue(PhoneConfig.DEFAULTS.provider("megalobiz").delay in phone.draws, "${phone.draws}")
    }

    @Test fun megalobizsDayStillCountsAnAutomaticJobsRequests() {
        val perDay = PhoneConfig.DEFAULTS.provider("megalobiz").perDay!!
        // LRCLIB has none (404s), so Megalobiz is the stage's next ask, and what stopped it its words.
        val phone = phone(answer = { url -> when {
                              "lrclib.net/api/get" in url -> HttpAnswer(404, emptyList(), ByteArray(0))
                              "lrclib.net/api/search" in url -> HttpAnswer(200, emptyList(), "[]".toByteArray())
                              else -> null
                          } },
                          seed = { db, now -> seedLookups(db, now, "megalobiz", perDay, run = "seed") })
        val job = run(phone, automatic = true)
        val events = events(phone)
        assertTrue(events.none { it.first == "megalobiz" && it.third in Pace.SENT }, "$events")
        assertTrue(phone.asked.none { "megalobiz" in it }, "${phone.asked}")
        assertTrue(phone.asked.any { "lrclib" in it }, "${phone.asked}")
        // Its words, true on the phone (no nightly run to promise): the day's limit, the one it met.
        val lyrics = job.stages.first { it.name == "lyrics" }.detail
        assertTrue("no asks of Megalobiz left today ($perDay spent); a later lookup asks" in lyrics, lyrics)
    }

    /** A run's own budget spent is said as that, never as the day's. */
    @Test fun aBulkClientsOwnBudgetSpentIsSaidAsItsOwn() {
        val p = PhoneConfig.DEFAULTS.provider("megalobiz")
        assertEquals(StageEnd("skipped", "this job's ${p.budget} asks of Megalobiz are spent; a later lookup asks"),
                     LookupWords.end(PhoneConfig.DEFAULTS, "megalobiz", Asked.Spent(false, false, bulk = true)))
    }

    @Test fun aJobAskedForNowKeepsTheLookupPace() {
        val phone = phone()
        run(phone, automatic = false)
        val events = events(phone)
        assertTrue(events.isNotEmpty() && events.all { it.second.startsWith(Pace.LOOKUP_RUN) }, "$events")
        assertTrue(PhoneConfig.DEFAULTS.provider("lrclib").lookupDelay in phone.draws, "${phone.draws}")
        assertTrue(PhoneConfig.DEFAULTS.provider("lrclib").delay !in phone.draws, "${phone.draws}")
    }

    /** A metered network met before a run (the job queued on Wi-Fi): an automatic job sends nothing, its audio stage
     * "waiting for Wi-Fi", nothing counted against the video or the song, no run reserved; and it ends there, every
     * stage after the audio skipped in those words, so no lyrics site is asked on that network (Byoutube-5). Asked for
     * now, it goes. */
    @Test fun aMeteredNetworkStopsAnAutomaticJobBeforeItsRunAndCountsNothing() {
        val phone = phone()
        val job = run(phone, automatic = true, metered = { true })
        assertEquals(Job.FAILED to YouTubeSearchRunner.METERED,
                     job.stages.first { it.name == "audio" }.let { it.state to it.detail })
        assertEquals(emptyList(), phone.asked,
                     "the automatic job held back asked the lyrics sites on the metered network; its lyrics stage: " +
                         job.stages.first { it.name == "lyrics" }.let { it.state to it.detail })
        val after = YouTubeSheetRunner.Words.stages.map { it.first }.dropWhile { it != "audio" }.drop(1)
        assertEquals(after.associateWith { Job.SKIPPED to YouTubeSearchRunner.METERED },
                     job.stages.filter { it.name in after }.associate { it.name to (it.state to it.detail) })
        phone.database.read { db ->
            assertEquals(0L, db.one("SELECT COUNT(*) FROM events WHERE provider = 'youtube'") { it.long(0) })
            assertEquals(0L, db.one("SELECT COUNT(*) FROM events WHERE provider IN ('lrclib', 'megalobiz', 'azlyrics')") {
                it.long(0)
            })
            val record = io.github.danielhp95.caracole.core.youtube.Records.load(db, 1)
            assertEquals(null, record.error)
            assertEquals(emptyMap(), record.failures)
            assertEquals(0, io.github.danielhp95.caracole.core.youtube.DayBudget.runs(db, Instant.now()))
        }
        val asked = phone()
        val now = run(asked, automatic = false, metered = { true })
        assertEquals("done", now.stages.first { it.name == "audio" }.state, "${now.steps.single().output}")
        assertTrue(asked.asked.isNotEmpty(), "asked for now, its lyrics stage asks the sites as ever")
    }
}
