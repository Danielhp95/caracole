package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.ShareRoutes
import io.github.danielhp95.caracole.server.routes.SyncFileRoutes
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** The phone's wiring: its route modules in their order, each route answered by one of them, its command runners,
 * and its build carrying caracole's own page assets. What a module answers is its own tests'. */
class AssemblyTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    private fun <T> phone(render: ((PhoneDeps) -> PhoneRender)? = null, block: (Phone) -> T): T {
        val scope = CoroutineScope(SupervisorJob())
        try {
            return TestDb.fresh(tmp.root).use { database ->
                val deps = PhoneDeps(database, tmp.newFolder("library"), File(tmp.root, "state").apply { mkdirs() }, null, scope,
                                     NoAddress, secret = "s".repeat(64), csrf = "tok", transport = { RefusingTransport })
                block(Phone(deps, render?.invoke(deps)))
            }
        } finally {
            scope.cancel()
        }
    }

    /** A render that owes pages, as phone-render's does once its build changed ([stale]) or a take forgot some
     * ([owesAfterSync]): its job makes one song's. */
    private class Owing(deps: PhoneDeps, val stale: Boolean = false, val owesAfterSync: Boolean = false) :
        PhoneRender(deps.database, deps.libraryDir, deps.mirror, deps.version) {
        val betweens = AtomicInteger()

        override fun stale(): Boolean = stale
        override fun build(): String = "build-1"
        override fun afterSync(): Boolean = owesAfterSync
        override fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit): RenderStats {
            between()
            betweens.incrementAndGet()
            progress(1, 1)
            return RenderStats(written = 1)
        }
    }

    @Test fun theModulesAreInTheirOrderAndEachRouteIsOneModulesAlone() = phone { phone ->
        assertEquals(listOf("PageRoutes", "SearchRoutes", "JobsRoutes", "RequestsRoutes", "SyncRoutes", "SyncFileRoutes",
                            "LibraryRoutes", "LookupRoutes", "UgLinkRoutes", "LyricsRoutes", "SongbookRoutes",
                            "VersionsRoutes", "HarmonicaRoutes",
                            "ReviewRoutes", "ExportRoutes", "GuitarRoutes", "AudioRoutes", "ShareRoutes"),
                     phone.modules.map { it::class.simpleName })
        val owners = phone.modules.flatMap { module -> module.routes.map { "${it.method} ${it.path}" to module } }
        val twice = owners.groupBy({ it.first }, { it.second::class.simpleName }).filterValues { it.size > 1 }
        assertEquals(emptyMap(), twice)
        // A stub stands only for a route no module answers yet: YouTube's, and the computer's lookup page, for good.
        val stubbed = Stubs().routes.map { "${it.method} ${it.path}" }.toSet()
        assertEquals(setOf("GET /lookup", "POST /youtube", "POST /youtube/search", "POST /youtube/video",
                           "GET /api/youtube/video"), stubbed)
        assertEquals(emptySet(), stubbed intersect owners.map { it.first }.toSet())
        val moved = mapOf(
            "LookupRoutes" to listOf("POST /lookup", "POST /fetch", "POST /lacuerda/artist", "POST /lacuerda/search",
                                     "POST /harptabs/artist", "POST /versions/keep-more"),
            "UgLinkRoutes" to listOf("GET /api/ug/link", "POST /ug/link"),
            "RequestsRoutes" to listOf("GET /requests.json", "POST /jobs/again"),
            "LibraryRoutes" to listOf("POST /request", "POST /remove"),
            "SongbookRoutes" to listOf("make", "add", "add-song", "get", "remove", "move", "set", "rename", "delete")
                .map { "POST /songbook/$it" },
            "VersionsRoutes" to listOf("GET /versions", "POST /versions/choose", "POST /versions/keep",
                                       "POST /versions/clear"),
            "HarmonicaRoutes" to listOf("GET /harmonica", "POST /harmonica/pin", "POST /harmonica/clear"),
            "ReviewRoutes" to listOf("GET /review", "POST /review"),
            "ExportRoutes" to listOf("GET /export.pdf"),
            "GuitarRoutes" to listOf("GET /guitar", "GET /assets/alphatab/"),
            "AudioRoutes" to listOf("POST /audio/upload", "POST /audio", "POST /audio/drop"),
            "SyncRoutes" to listOf("GET /api/sync", "POST /sync/test", "POST /sync/compare", "GET /api/sync/unit",
                                   "GET /api/sync/indexes", "POST /sync/apply"),
            "SyncFileRoutes" to listOf("GET /api/sync/sizes", "POST /sync/export", "GET /api/sync/export",
                                       "POST /sync/import/open", "POST /sync/import/part", "POST /sync/import/compare",
                                       "POST /sync/import/drop"),
        )
        // The phone's own page of a song shared to the app, which caracole serve has none of.
        assertEquals(listOf("GET /share", "POST /share", "GET /share/cancel", "GET /share/audio",
                            "POST /share/audio/cancel"),
                     phone.modules.filterIsInstance<ShareRoutes>().single().routes.map { "${it.method} ${it.path}" })
        val ownerOf = owners.associate { (route, module) -> route to module::class.simpleName }
        for ((module, routes) in moved) {
            for (route in routes) assertEquals(module, ownerOf[route], route)
        }
        // Milestone 6's modules answer the routes moved to them, and nothing else.
        for (module in phone.modules.filter { it::class.simpleName in moved.keys - setOf("LibraryRoutes") }) {
            val name = module::class.simpleName!!
            assertEquals(moved.getValue(name).toSet(), module.routes.map { "${it.method} ${it.path}" }.toSet(), name)
        }
    }

    @Test fun theSyncIsTheAppsAndHandsAFilesComparisonToTheFilesRoutes() = phone { phone ->
        assertSame(phone.modules.filterIsInstance<SyncRoutes>().single(), phone.sync, "the app's unattended sync's")
        assertSame(phone.modules.filterIsInstance<SyncFileRoutes>().single(), phone.sync.files,
                   "Sync on a file's comparison queues its import")
    }

    @Test fun anExportAnEarlierStartLeftIsClearedAsThePhoneStarts() {
        val left = File(tmp.root, "state/cache/peer").apply { mkdirs() }.let { File(it, "export-0123456789abcdef.caracole") }
        left.writeBytes(ByteArray(1))
        phone { assertTrue(!left.exists(), "no earlier start's export can be asked for") }
    }

    /** Overrides the reader refuses (no take writes one now; an older app's might have) never stop the phone's start:
     * its Backups, which a restore needs, are reached through the same Phone. */
    @Test fun overridesThatCantBeReadNeverStopThePhonesStart() = phone<Unit> { phone ->
        phone.parts.database.writeBlocking { db ->
            phone.parts.store.add(db, "Muse", "Hysteria", now = "2026-11-01T10:00:00Z")
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('transpose', 'muse/hysteria', " +
                           "'Muse - Hysteria', '99')")
        }
        phone.start()
        assertEquals(emptyList(), phone.queue.snapshot().map { it.spec.kind }, "nothing it can't read is queued")
    }

    @Test fun theIndexFilesASyncKilledInItsMiddleLeftAreSweptAsThePhoneStarts() {
        val cache = File(tmp.root, "state/cache").apply { mkdirs() }
        val left = listOf("index-0123456789abcdef.sqlite", "import-indexes-0123456789abcdef.sqlite",
                          "reads-0123456789abcdef.sqlite", "index-0123456789abcdef.sqlite-wal")
            .map { File(cache, it).apply { writeBytes(ByteArray(16)) } }
        val others = listOf("notes.sqlite", "index-mine.sqlite").map { File(cache, it).apply { writeBytes(ByteArray(1)) } }
        phone {
            assertTrue(left.none { it.exists() }, "a killed sync's index files are gone")
            assertTrue(others.all { it.exists() }, "nothing else is touched")
        }
    }

    @Test fun theFileACataloguesImportKilledInItsMiddleLeftIsSweptAsThePhoneStarts() {
        val folder = File(tmp.root, "state/cache/catalogues").apply { mkdirs() }
        val left = listOf("indexes-s17-20261124T1815Z.sqlite", "indexes-s17-20261124T1815Z.sqlite-journal")
            .map { File(folder, it).apply { writeBytes(ByteArray(16)) } }
        val beside = File(tmp.root, "state/cache/notes.txt").apply { writeBytes(ByteArray(1)) }
        phone {
            assertTrue(left.none { it.exists() }, "the unpacked index a killed import left is gone")
            assertTrue(folder.isDirectory, "its folder stays")
            assertTrue(beside.exists(), "nothing beside it is touched")
        }
    }

    /** The given audio no song names (a song a take removed or merged, a removal's) is tidied as the phone starts
     * and after a sync's take; a kept file a song names, a staged upload and anything else stay. */
    @Test fun theGivenAudioNoSongNamesIsTidiedAtTheStartAndAfterATake() {
        val folder = File(tmp.root, "state/audio").apply { mkdirs() }
        val orphan = File(folder, "7-0123456789abcdef.mp3").apply { writeBytes(ByteArray(8)) }
        val staged = File(folder, ".upload-0123456789abcdef.mp3").apply { writeBytes(ByteArray(8)) }
        phone { phone ->
            assertTrue(!orphan.exists(), "a kept file no song names is gone at the start")
            assertTrue(staged.exists(), "a staged upload is the sweep's, never the tidy's")
            val again = File(folder, "8-0123456789abcdef.mp3").apply { writeBytes(ByteArray(8)) }
            phone.afterSync()
            assertTrue(!again.exists(), "and after a take")
        }
    }

    /** `caracole audio` is the phone's command, AudioRunner's; with no chord models wired in (a build without
     * `:ml`, the assembly's default) its job refuses before anything is kept, in the command's words; the models' remove is
     * refused while one waits or runs (ModelsRunner.USES). */
    @Test fun theAudioCommandIsWiredAndWithNoChordsItRefusesBeforeAnythingIsKept() = phone { phone ->
        val commands = io.github.danielhp95.caracole.server.jobs.JobCommands.audioSheetSteps("Calla Lake - River Road",
                                                                                           "0123456789abcdef")
        assertTrue(io.github.danielhp95.caracole.server.jobs.JobCommands.AUDIO_SHEET in
                       io.github.danielhp95.caracole.server.lookups.ModelsRunner.USES)
        val job = phone.queue.submit(JobSpec("Sheet from an audio file: Calla Lake - River Road",
                                             "audio:calla-lake/river-road", "song",
                                             io.github.danielhp95.caracole.server.jobs.JobCommands.stages(commands.map { it.args }),
                                             commands = commands)).first
        val over = runBlocking { phone.queue.await(job.id) }
        assertEquals(Job.FAILED, over.state)
        assertEquals(listOf("error: caracole makes no sheet from an audio file here: auto-chords isn't on the phone"),
                     over.steps.single().output)
    }

    /** A take checks a song's `[version]` and `[harmonica]` entries with the viewer's own checks, as
     * overrides.put_song_entries reads them back: the engine is given Versions.keyVersion and HarpTabs.checkSpec. */
    @Test fun theSyncEngineTakesWithTheViewersChecksOfAnOverridesEntry() = phone<Unit> { phone ->
        val checks = phone.sync.engine.checks
        assertSame(OVERRIDE_CHECKS, checks)
        val version = assertFailsWith<IllegalArgumentException> { checks.keyVersion!!("key=H") }
        assertEquals("key must be a key as a sheet names it, such as \"G\", \"F#m\" or \"Bb dorian\", got 'H'",
                     version.message)
        val reading = assertFailsWith<IllegalArgumentException> { checks.checkSpec!!(JsonPrimitive("nonesuch")) }
        assertEquals("expected signs, brackets, letters, signs after, barrett or legend, got 'nonesuch'", reading.message)
    }

    @Test fun thePagesAPhoneMakesAreItsOwnSeams() = phone<Unit> { phone ->
        // The lookup's pdf stage is the phone's render, its songbooks stage the songbooks' pages, each through its
        // seam: NONE while its lane hasn't landed, so a lookup calls none of a later milestone's code; both have
        // (phone-render, songbook-entries).
        assertSame(phone.render.seam, phone.parts.pages)
        assertSame(phone.songbookPages.seam, phone.parts.songbooks)
        assertSame(phone.render, phone.parts.pages)
        assertSame<SongbookPages>(phone.songbookPages, phone.parts.songbooks)
        assertTrue(phone.parts.cards is PhonePageData)
        // A library with no song owes no page, so its start queues no render job, nor does a take that brought none.
        phone.start()
        phone.afterSync()
        assertEquals(emptyList(), phone.queue.snapshot().map { it.spec.kind })
        assertNotNull(phone.modules.filterIsInstance<JobsRoutes>().single().songbooks)
    }

    @Test fun theRenderJobIsQueuedByStartOnceTheAppHearsTheQueueAndItYieldsBetweenSongs() {
        phone(render = { Owing(it, stale = true) }) { phone ->
            // Building the phone queues nothing: the app wires the queue's onBusy first, then calls start.
            assertEquals(emptyList(), phone.queue.snapshot())
            val heard = CopyOnWriteArrayList<Boolean>()
            phone.queue.onBusy = { heard += it }
            phone.start()
            val job = phone.queue.snapshot().single()
            assertEquals(listOf("render", "render:build-1", "Remake the pages", "The phone's pages"),
                         listOf(job.spec.kind, job.spec.key, job.spec.title, job.display))
            val over = runBlocking { phone.queue.await(job.id) }
            assertEquals(Job.DONE, over.state)
            assertEquals("Pages remade · 1 songs", over.stages.single().detail)
            assertEquals(1, (phone.render as Owing).betweens.get())
            assertEquals(true, heard.first(), "the foreground service hears the start-time render")
        }
    }

    @Test fun aTakeThatOwesPagesQueuesTheRenderJobAfterTheSyncNeverInsideIt() {
        phone(render = { Owing(it, owesAfterSync = true) }) { phone ->
            phone.afterSync()
            val job = phone.queue.snapshot().single()
            assertEquals("render:build-1", job.spec.key)
            assertEquals(Job.DONE, runBlocking { phone.queue.await(job.id) }.state)
        }
    }

    @Test fun theRenderJobAndATakeMakeAgainTheSongbookPagesThePhoneMadeAtItsBuild() {
        phone(render = { Owing(it, stale = true) }) { phone ->
            val database = phone.parts.database
            val gig = File(phone.parts.store.libraryDir, "_songbooks/Gig/songbook.html")
            database.writeBlocking { db ->
                Songbooks.make(db, "Gig", listOf("Muse - Hysteria"))
                Songbooks.make(db, "Picnic", listOf("Muse - Hysteria"))
                phone.songbookPages.render(db, setOf("Gig"))
            }
            val made = gig.readText()
            // a take that owes no page: the songbook pages the phone made are made again where they moved
            gig.writeText("changed on a device")
            phone.afterSync()
            assertEquals(made, gig.readText())
            // the render job ends with them too
            gig.writeText("changed on a device")
            phone.start()
            val job = phone.queue.snapshot().single()
            assertEquals(Job.DONE, runBlocking { phone.queue.await(job.id) }.state)
            assertEquals(made, gig.readText())
            // a songbook the phone made no page of keeps the computer's
            assertFalse(File(phone.parts.store.libraryDir, "_songbooks/Picnic").exists())
        }
    }

    @Test fun theQueueRunsACommandByItsRunnerAndTellsEachJobsEnd() = phone { phone ->
        val ended = mutableListOf<Job>()
        val after = phone.queue.onEnd
        phone.queue.onEnd = { job -> after(job); ended += job }
        val job = phone.queue.submit(JobSpec("Nothing", "nothing", "other", emptyList(),
                                             commands = listOf(Command("Nothing", listOf("nothing"))))).first
        val over = runBlocking { phone.queue.await(job.id) }
        assertEquals(Job.FAILED, over.state)  // no runner of "nothing" on the phone
        assertEquals("error: caracole nothing isn't on the phone", over.output.last())
        assertEquals(listOf(job.id), ended.map { it.id })
        assertEquals(setOf("get", "lyrics", "versions", "lacuerda", "harptabs", "ug", "review", "harmonica", "render",
                           "songbook", "inbox", "backup", "catalogues", "models", "audio"),
                     phone.queue.commands.runners.keys)
        // The JVM's classpath carries no models.json, as the release's: the models' job is offered and says so.
        assertEquals(null, phone.models.folder())
        assertEquals("This build carries no chord models.", phone.models.ready())
        // The site catalogues listed through GitHub's API, the one source.
        assertTrue(phone.catalogues.source(io.github.danielhp95.caracole.mirror.Http()) is
                       io.github.danielhp95.caracole.core.catalogues.CatalogueSource.Api)
    }

    /** The requests a start ran are the next start's too (docs/android_port.md: the Requests tab's history kept
     * across the app's restarts): `stateDir/requests.jsonl`, JobHistory.at's, and the ids go on after theirs. */
    @Test fun theRequestsAStartRanAreRememberedByTheNextAndItsIdsGoOn() {
        val library = tmp.newFolder("history-library")
        val state = File(tmp.root, "history-state").apply { mkdirs() }
        fun <T> start(db: String, block: (Phone) -> T): T {
            val scope = CoroutineScope(SupervisorJob())
            try {
                return TestDb.fresh(tmp.newFolder(db)).use { database ->
                    block(Phone(PhoneDeps(database, library, state, null, scope, NoAddress, secret = "s".repeat(64),
                                          csrf = "tok", transport = { RefusingTransport })))
                }
            } finally {
                scope.cancel()
            }
        }
        val ran = start("db1") { phone ->
            val job = phone.queue.submit(JobSpec("Back up the book", "backup:by-hand", "backup",
                                                 listOf("backup" to "Backing up"),
                                                 run = { it.stage("backup", "done", "done") })).first
            runBlocking { phone.queue.await(job.id) }
        }
        assertEquals(Job.DONE, ran.state)
        assertTrue(File(state, "requests.jsonl").isFile, "the phone's history: stateDir/requests.jsonl")
        start("db2") { phone ->
            assertEquals(listOf(ran.id to "Back up the book"), phone.queue.snapshot().map { it.id to it.title })
            val next = phone.queue.submit(JobSpec("Something", "something", "add", listOf("add" to "Adding"),
                                                  run = { it.stage("add", "done", "done") })).first
            assertTrue(next.id > ran.id, "the ids go on after the history's: ${next.id} after ${ran.id}")
            runBlocking { phone.queue.await(next.id) }
        }
    }

    @Test fun theLibraryAssetsAreOnTheClasspathByteForByte() {
        val source = File(System.getProperty("caracole.conformance")).resolve("../../../src/caracole/library_assets")
        val names = source.listFiles()!!.map { it.name }.filter { it.substringAfterLast('.') in setOf("js", "css", "html") }
        assert(names.isNotEmpty())
        for (name in names) {
            val copied = javaClass.getResourceAsStream("/caracole/library_assets/$name")
            assertNotNull(copied, name)
            assertContentEquals(File(source, name).readBytes(), copied.use { it.readBytes() }, name)
        }
    }
}
