package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.page.MirrorPageData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** The lookup commands run as the phone's jobs: `caracole get` and its words, a lookup stopped with its records
 * kept, and the commands' lines and events (LookupJobs). */
class LookupRunnersTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })
    private val ug = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
    private val lacuerdaSearch = LaCuerdaPages.searchUrl("de musica ligera")
    private val site = FakeTransport(mapOf("GET $ug" to FakeTransport.answer(403, "Forbidden"),
                                           "GET $lacuerdaSearch" to FakeTransport.answer(500, "x")) +
                                     LaCuerdaPages.artistSlugCandidates("soda stereo").associate {
                                         "GET ${LaCuerdaPages.artistUrl(it)}" to FakeTransport.answer(404, "x")
                                     })
    private val quiet = SiteStage { StageEnd("skipped", "nothing to do") }

    private fun stages(ugSheet: SiteStage = quiet, lrclib: SiteStage = quiet) = SiteStages(
        quiet, ugSheet, quiet, quiet, quiet, lrclib, SiteStage { LookupWords.NOTHING_TO_ASK },
        SiteStage { LookupWords.NOTHING_TO_ASK }, quiet, quiet, quiet)

    private fun parts(database: Database, scope: CoroutineScope, queue: JobQueue,
                      pages: SongPages = SongPages.NONE): PhoneParts {
        val state = File(tmp.root, "state").apply { mkdirs() }
        return PhoneParts(database, LibraryStore(File(tmp.root, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                          MirrorPageData(null),
                          { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { site }, pacing) },
                          pages, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
    }

    /** A job's context that keeps what it is told. */
    private class Heard : JobContext {
        val stages = ArrayList<Triple<String, String, String>>()
        val said = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) {
            stages += Triple(name, state, detail)
        }

        override fun say(line: String) {
            said += line
        }

        override fun outcome(value: kotlinx.serialization.json.JsonObject) {}
        override val isCancelled: Boolean = false
    }

    /** A queue whose runners are [runners] of the phone's parts, the job of [commands] run in it to its end. */
    private fun job(commands: List<io.github.danielhp95.caracole.server.jobs.Command>,
                    runners: (PhoneParts) -> Map<String, CommandRunner>, check: (Job, Database) -> Unit) {
        val scope = CoroutineScope(SupervisorJob())
        TestDb.fresh(tmp.newFolder()).use { database ->
            val made = HashMap<String, CommandRunner>()
            val queue = JobQueue(scope, commands = Commands(made))
            made += runners(parts(database, scope, queue))
            val (job, _) = queue.submit(JobSpec("Look it up", "radiohead/creep", "song", emptyList(), commands = commands))
            val over = runBlocking { withTimeout(30_000) { queue.await(job.id) } }
            check(over, database)
        }
        scope.cancel()
    }

    private val none: (io.github.danielhp95.caracole.core.db.Db) -> Overrides = { Overrides() }

    @Test fun aLookupIsAJobItsStagesItsLinesAndItsSong() = job(JobCommands.lookupSteps("Radiohead", "Creep"), { p ->
        mapOf("get" to GetRunner(p, none, stages()))
    }) { job, database ->
        assertEquals(Job.DONE, job.state)
        assertEquals(LookupWords.STAGES.map { it.first }, job.stages.map { it.name })
        assertEquals("done" to LookupWords.ADDED, job.stages[0].state to job.stages[0].detail)
        assertEquals("skipped" to LookupWords.NO_SHEET_YET, job.stages[3].state to job.stages[3].detail)
        val output = job.steps.single().output
        assertEquals("Song: ${LookupWords.ADDED}.", output.first())
        assertEquals("Done in 0.0 s: 0 asks.", output.last())
        val song = database.read { Songs.byKey(it, Normalize.identityKey("Radiohead", "Creep")) }!!
        assertEquals(song.id, job.songId)
        assertEquals("Radiohead - Creep", job.songDisplay)
    }

    @Test fun aLookupReadsAndWritesThePhonesOwnOverrides() = job(JobCommands.lookupSteps("Radiohead", "Creep",
                                                                                       ug = "radiohead/creep"), { p ->
        mapOf("get" to GetRunner(p, stages = stages()))  // Overrides.read, the phone's
    }) { job, database ->
        assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
        assertEquals("${LookupWords.ADDED}; recorded in overrides.toml: [match] radiohead/creep", job.stages[0].detail)
        val key = Normalize.identityKey("Radiohead", "Creep")
        assertEquals("radiohead" to "creep", database.read { Overrides.read(it) }.match[key])
    }

    @Test fun aRefusedLookupFailsItsStepAndSaysWhy() = job(JobCommands.lookupSteps("Radiohead", "Creep"), { p ->
        mapOf("get" to GetRunner(p, { Overrides(ignore = setOf(Normalize.identityKey("Radiohead", "Creep"))) }, stages()))
    }) { job, _ ->
        assertEquals(Job.FAILED, job.state)
        assertEquals(1, job.steps.single().code)
        val why = "Radiohead - Creep is ignored in overrides.toml: take it out of [ignore] to look it up"
        assertEquals("failed" to why, job.stages[0].state to job.stages[0].detail)
        assertEquals("error: Nothing looked up: $why.", job.steps.single().output.last())
    }

    @Test fun aBugFailsTheStepOnceTheOtherStagesRan() = job(JobCommands.lookupSteps("Radiohead", "Creep"), { p ->
        mapOf("get" to GetRunner(p, none, stages(lrclib = SiteStage { error("no such column") })))
    }) { job, _ ->
        assertEquals(Job.FAILED, job.state)
        val output = job.steps.single().output
        assertEquals("error: a bug in caracole: lyrics: IllegalStateException: no such column", output.last())
        assertTrue(output[output.size - 2].startsWith("Done in "))
        assertEquals("done", job.stages.first { it.name == "pages" }.state)
    }

    @Test fun aCommandLineGetCantReadIsAUsageError() {
        for ((args, said) in listOf(
            listOf("get", "--progress", "--", "Radiohead") to
                "error: caracole get takes a song as \"Artist - Title\", or as ARTIST TITLE, not 'Radiohead'",
            listOf("get", "--progress", "--duration=soon", "--", "Radiohead", "Creep") to
                "error: --duration: 'soon' isn't a duration: write m:ss, h:mm:ss or seconds",
            listOf("get", "--progress", "--ug=radiohead", "--", "Radiohead", "Creep") to
                "error: --ug takes an Ultimate Guitar song as artist-key/song-key (radiohead/creep), not 'radiohead'",
            listOf("get", "--nonsense", "--", "Radiohead", "Creep") to "error: No such option: --nonsense",
        )) {
            job(listOf(io.github.danielhp95.caracole.server.jobs.Command("Look it up now", args)), { p ->
                mapOf("get" to GetRunner(p, none, stages()))
            }) { job, _ ->
                assertEquals(2, job.steps.single().code, "$args")
                assertEquals(said, job.steps.single().output.last())
            }
        }
    }

    @Test fun aStoppedLookupKeepsWhatItRecordedAsItHappened() {
        val scope = CoroutineScope(SupervisorJob())
        val asked = CountDownLatch(1)
        val release = CountDownLatch(1)
        TestDb.fresh(tmp.newFolder()).use { database ->
            val made = HashMap<String, CommandRunner>()
            val queue = JobQueue(scope, commands = Commands(made))
            val blocks = SiteStage { ctx ->
                val end = LookupWords.end(ctx.config, "ug", ctx.asking.ask("ug") { it.get(ug); StageEnd("done", "x") })
                asked.countDown()
                release.await(30, TimeUnit.SECONDS)
                end
            }
            made["get"] = GetRunner(parts(database, scope, queue), none, stages(ugSheet = blocks))
            val (job, _) = queue.submit(JobSpec("Look it up", "radiohead/creep", "song", emptyList(),
                                                commands = JobCommands.lookupSteps("Radiohead", "Creep")))
            assertTrue(asked.await(30, TimeUnit.SECONDS))
            database.read { db ->  // committed as it happened, while the lookup still runs
                assertEquals("blocked", db.one("SELECT decision FROM events WHERE provider = 'ug'") { it.text(0) })
                assertNotNull(Health.state(db, "ug").cooldownUntil)
                assertEquals("1793707200.000", db.kvGet(Pace.LAST_SENT + "ug"))
            }
            scope.cancel()
            release.countDown()
            val over = runBlocking { withTimeout(30_000) { queue.await(job.id) } }
            assertEquals(Job.INTERRUPTED, over.state)
            assertEquals(null, over.stages.firstOrNull { it.name == "pdf" && it.state == "running" })
            database.read { db -> assertNotNull(Health.state(db, "ug").cooldownUntil) }
        }
    }

    @Test fun aCommandsProgressLinesAreItsJobsEventsWhenItReportsThem() {
        val stages = ArrayList<Triple<String, String, String>>()
        val said = ArrayList<String>()
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) {
                stages += Triple(name, state, detail)
            }

            override fun say(line: String) {
                said += line
            }

            override fun outcome(value: kotlinx.serialization.json.JsonObject) {}
            override val isCancelled: Boolean = false
        }
        val line = JobCommands.PROGRESS_PREFIX + """{"stage":"search","state":"running","detail":"asking LaCuerda"}"""
        LookupJobs.said(context, line, reports = true)
        LookupJobs.said(context, JobCommands.PROGRESS_PREFIX + """{"done":{"ok":true}}""", reports = true)
        LookupJobs.said(context, "Searched: LaCuerda has 2 songs for “x”, in the index now.", reports = true)
        LookupJobs.said(context, line, reports = false)
        assertEquals(listOf(Triple("search", "running", "asking LaCuerda")), stages)
        assertEquals(listOf("Searched: LaCuerda has 2 songs for “x”, in the index now.", line), said)
    }

    @Test fun aLookupCommandsProgressLinesAreTheQueuesOwn() {
        // :core's words for a command's lines (core/lookup/sites/ can't reach :server's) are the queue's to the byte.
        assertEquals(JobCommands.PROGRESS_PREFIX, LookupWords.PROGRESS_PREFIX)
        val event = kotlinx.serialization.json.JsonObject(linkedMapOf(
            "stage" to kotlinx.serialization.json.JsonPrimitive("version"),
            "state" to kotlinx.serialization.json.JsonPrimitive("done"),
            "detail" to kotlinx.serialization.json.JsonPrimitive("Kept tab 4169 beside the sheet of Sigur Rós - Hoppípolla")))
        assertEquals(JobCommands.progressLine(event), LookupWords.progressLine(event))
        assertEquals(JobCommands.progressLine(event),
                     LookupWords.stageLine("version", "done", "Kept tab 4169 beside the sheet of Sigur Rós - Hoppípolla"))
        assertEquals("""caracole-progress: {"song":{"id":7,"display":"Sigur Rós - Hoppípolla"}}""",
                     LookupWords.songLine(7, "Sigur Rós - Hoppípolla"))
        assertEquals("lookup:lacuerda-search:2026-11-03T12:00:00Z", LookupWords.searchRunId(now))
        assertEquals(Pace.lookupRunId(now), LookupWords.lookupRunOf(now))
    }

    @Test fun aKeepsPagesAreMadeAtItsPdfAndPagesEventsAndEndedInThePhonesWords() {
        val scope = CoroutineScope(SupervisorJob())
        TestDb.fresh(tmp.newFolder()).use { database ->
            val made = ArrayList<List<Long>>()
            val rendering = SongPages { _, ids, _ -> made += ids.toList(); RenderStats(written = 1) }
            val failing = SongPages { _, ids, _ -> RenderStats(failed = mapOf(ids.first() to "the page can't be made")) }
            database.writeBlocking { db ->
                val song = LibraryStore(File(tmp.root, "library")).add(db, "Radiohead", "Creep", now = "2026-11-03T12:00:00Z")
                val words = "the version's page made"
                for ((pages, pdf) in listOf(SongPages.NONE to ("skipped" to LookupWords.NO_PDFS),
                                            rendering to ("done" to words),
                                            failing to ("failed" to "the page can't be made"))) {
                    val heard = Heard()
                    val p = parts(database, scope, JobQueue(scope), pages)
                    val lines = LookupJobs.CommandLines(heard, reports = true, LookupJobs.CommandPages(p, db, song, words))
                    lines.say(LookupWords.stageLine("version", "done", "Kept tab 4169 beside the sheet of Radiohead - Creep"))
                    lines.say(LookupWords.stageLine("pdf", "running"))
                    lines.say(LookupWords.stageLine("pdf", "done", words))
                    lines.say("Viewer: /library/Radiohead/Creep/version-4169.html")
                    lines.say(LookupWords.stageLine("pages", "running"))
                    lines.say(LookupWords.stageLine("pages", "done", "_todo.md and index.html rewritten"))
                    assertEquals(listOf(Triple("version", "done", "Kept tab 4169 beside the sheet of Radiohead - Creep"),
                                        Triple("pdf", "running", ""), Triple("pdf", pdf.first, pdf.second),
                                        Triple("pages", "running", ""), Triple("pages", "done", LookupWords.LIBRARY_PAGE)),
                                 heard.stages)
                    assertEquals(listOf("Viewer: /library/Radiohead/Creep/version-4169.html"), heard.said)
                }
                assertEquals(listOf(listOf(song.id)), made)  // the pages made once, at the pdf stage's running event
                // A version that isn't kept: versions_cmd.py's pages alone, nothing rendered.
                val heard = Heard()
                val lines = LookupJobs.CommandLines(heard, reports = true,
                                                    LookupJobs.CommandPages(parts(database, scope, JobQueue(scope), rendering),
                                                                            db, song, words))
                lines.say(LookupWords.stageLine("pages", "running"))
                assertEquals(listOf(Triple("pages", "running", ""), Triple("pages", "done", LookupWords.LIBRARY_PAGE)),
                             heard.stages)
                assertEquals(1, made.size)
            }
        }
        scope.cancel()
    }

    @Test fun eachLookupCommandIsItsRunnersAndSaysItsLastLine() {
        val noIndex = "Not read: harptabs.com's index is empty: the nightly run reads its sitemap, or caracole " +
            "harptabs --index now."  // lane harptabs': nothing asked of a phone with no index
        for ((args, said) in listOf(
            listOf("lacuerda", "--artist=soda  stereo") to "Not found: LaCuerda has no artist page for soda stereo.",
            listOf("harptabs", "--artist=Billy Joel") to noIndex,
            listOf("lacuerda", "--search=de musica ligera", "--progress") to
                "Not searched: LaCuerda failed (lacuerda: 500: $lacuerdaSearch: HTTP 500); nothing changed: try again later.",
        )) {
            job(listOf(io.github.danielhp95.caracole.server.jobs.Command("Ask", args)), { p ->
                mapOf("lacuerda" to LaCuerdaRunner(p), "harptabs" to HarpTabsRunner(p))
            }) { job, database ->
                assertEquals(Job.DONE, job.state, "$args")
                assertEquals(listOf(said), job.steps.single().output, "$args")  // the progress lines its stages
                if ("--progress" in args) database.writeBlocking { db ->  // the error counted, under the search's run
                    assertNotNull(Health.state(db, "lacuerda").lastError)
                    assertEquals(1, Pace.lookupRequestsUsed(db, "lacuerda", now, "lookup:lacuerda-search:"))
                }
            }
        }
    }

    @Test fun aCommandLineALookupCommandCantReadIsAUsageError() {
        for ((args, said) in listOf(
            listOf("lacuerda", "--artist=x", "--search=y") to "error: --index reads every artist's listing, --artist " +
                "one artist's page and --search one query of LaCuerda's search: give one of them",
            listOf("lacuerda", "--artist=x", "--auto") to "error: --auto and --progress go with --search",
            listOf("harptabs", "--budget=3", "--artist=x") to "error: --budget goes with --index",
            listOf("versions", "--keep-more", "--clear", "--", "Radiohead", "Creep") to
                "error: caracole versions takes one of --keep, --keep-more, --choose and --clear",
            listOf("versions", "--clear", "--", "Radiohead") to
                "error: caracole versions takes a song as \"Artist - Title\", or as ARTIST TITLE, not 'Radiohead'",
        )) {
            job(listOf(io.github.danielhp95.caracole.server.jobs.Command("Ask", args)), { p ->
                mapOf("lacuerda" to LaCuerdaRunner(p), "harptabs" to HarpTabsRunner(p),
                      "versions" to VersionsRunner(p, none, stages()))
            }) { job, _ ->
                assertEquals(2, job.steps.single().code, "$args")
                assertEquals(said, job.steps.single().output.last())
            }
        }
    }

    @Test fun aLaCuerdaSearchCountsInTheHoursSearches() = TestDb.fresh(tmp.newFolder()).use { database ->
        val scope = CoroutineScope(SupervisorJob())
        val p = parts(database, scope, JobQueue(scope))
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) {}
            override fun say(line: String) {}
            override fun outcome(value: kotlinx.serialization.json.JsonObject) {}
            override val isCancelled: Boolean = false
        }
        database.writeBlocking { db ->
            val (c, ask) = LookupJobs.context(p, db, listOf("lacuerda", "--search=x"), context, now,
                                              "lookup:lacuerda-search:2026-11-03T12:00:00Z")
            c.asking.ask("ug") { it.get(ug) }
            ask.close()
            assertEquals(1, Pace.lookupRequestsUsed(db, "ug", now, "lookup:lacuerda-search:"))
        }
        scope.cancel()
    }

    @Test fun aKeepOfATabTheSongHasntIsRefusedInVersionsCmdsWords() {
        job(JobCommands.versionSteps("Radiohead", "Creep", keep = "4169"), { p ->
            p.database.writeBlocking { p.store.add(it, "Radiohead", "Creep", now = "2026-11-03T12:00:00Z") }
            mapOf("versions" to VersionsRunner(p, none, stages()))
        }) { job, _ ->
            assertEquals(Job.FAILED, job.state)
            assertEquals(1, job.steps.single().code)  // versions_cmd.py's fail
            assertEquals(listOf("error: Tab 4169 isn't one of the Ultimate Guitar chords versions of Radiohead - Creep: " +
                                    "caracole versions \"Radiohead - Creep\" lists them."), job.steps.single().output)
            assertTrue(site.said.isEmpty())
        }
    }

    @Test fun aKeepAsksThroughTheLookupsEnvelopeAndSaysItsLinesAsTheJobKeepsThem() {
        // VersionsCommands says versions_cmd.py's lines from {"song": …} on (vectors/lookup/commands_versions.jsonl);
        // the runner owns the rest of Python's output: the song stage begun before it, and the last line once it
        // returns. Here the version's page answers 403: the envelope (InteractiveAsk) cools Ultimate Guitar down.
        job(JobCommands.versionSteps("Radiohead", "Creep", keep = "4169"), { p ->
            p.database.writeBlocking { db ->
                val song = p.store.add(db, "Radiohead", "Creep", now = "2026-11-03T12:00:00Z")
                io.github.danielhp95.caracole.core.library.Versions.upsert(
                    db, "ug", "4169", song.id, "sheet", "chords", 4.5, 10, 1, null, ug,
                    kotlinx.serialization.json.JsonObject(emptyMap()), "2026-11-03T12:00:00Z")
            }
            mapOf("versions" to VersionsRunner(p, none, stages()))
        }) { job, database ->
            assertEquals(Job.DONE, job.state)  // a block exits 0, as versions_cmd.py's
            assertEquals(listOf("GET $ug"), site.said)
            val until = database.read { Health.state(it, "ug").cooldownUntil }
            assertNotNull(until)
            val words = "Ultimate Guitar blocked caracole (ug: 403: $ug: HTTP 403): no more requests to it until " +
                java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(java.time.ZoneOffset.UTC)
                    .format(until) + "; nothing kept."
            // No page made after a block, as versions_cmd.py makes none: the queue's end skips the stages left.
            assertEquals(listOf("song" to "done", "version" to "skipped", "pdf" to "skipped", "pages" to "skipped"),
                         job.stages.map { it.name to it.state })
            assertEquals("in the book", job.stages.first { it.name == "song" }.detail)
            assertEquals(words, job.stages.first { it.name == "version" }.detail)
            assertEquals(listOf(words), job.steps.single().output)  // its last line, said once it returned
            assertEquals(database.read { Songs.byKey(it, Normalize.identityKey("Radiohead", "Creep")) }!!.id, job.songId)
        }
    }

    @Test fun aClearWithNoPinSaysSoAndLooksNothingUp() {
        job(JobCommands.versionSteps("Radiohead", "Creep"), { p ->
            p.database.writeBlocking { p.store.add(it, "Radiohead", "Creep", now = "2026-11-03T12:00:00Z") }
            mapOf("versions" to VersionsRunner(p, none, stages()))
        }) { job, _ ->
            assertEquals(Job.DONE, job.state)
            assertEquals(listOf("No [pin] chooses the sheet of Radiohead - Creep: caracole's pick is the sheet already."),
                         job.steps.single().output)
        }
    }
}
