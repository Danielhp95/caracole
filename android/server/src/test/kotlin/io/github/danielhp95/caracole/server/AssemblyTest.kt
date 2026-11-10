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
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import kotlinx.coroutines.CoroutineScope
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
                val deps = PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope,
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
        assertEquals(listOf("PageRoutes", "SearchRoutes", "JobsRoutes", "RequestsRoutes", "SyncRoutes", "LibraryRoutes",
                            "LookupRoutes", "SongbookRoutes", "VersionsRoutes", "HarmonicaRoutes", "ReviewRoutes",
                            "ExportRoutes", "GuitarRoutes", "ShareRoutes"), phone.modules.map { it::class.simpleName })
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
        )
        // The phone's own page of a song shared to the app, which caracole serve has none of.
        assertEquals(listOf("GET /share", "GET /share/cancel"),
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
            assertEquals(listOf("render", "render:build-1", "Make the pages again", "The phone's pages"),
                         listOf(job.spec.kind, job.spec.key, job.spec.title, job.display))
            val over = runBlocking { phone.queue.await(job.id) }
            assertEquals(Job.DONE, over.state)
            assertEquals("Pages made again for 1 songs", over.stages.single().detail)
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
        assertEquals(setOf("get", "versions", "lacuerda", "harptabs", "review", "harmonica", "render", "songbook", "inbox",
                           "backup"), phone.queue.commands.runners.keys)
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
