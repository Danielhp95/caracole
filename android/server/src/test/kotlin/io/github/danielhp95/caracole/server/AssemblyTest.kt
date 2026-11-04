package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** The phone's wiring: its route modules in their order, each route answered by one of them, its command runners,
 * and its build carrying caracole's own page assets. What a module answers is its own tests'. */
class AssemblyTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    private fun <T> phone(block: (Phone) -> T): T {
        val scope = CoroutineScope(SupervisorJob())
        try {
            return TestDb.fresh(tmp.root).use { database ->
                block(Phone(PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope,
                                      NoAddress, secret = "s".repeat(64), csrf = "tok",
                                      transport = { RefusingTransport })))
            }
        } finally {
            scope.cancel()
        }
    }

    @Test fun theModulesAreInTheirOrderAndEachRouteIsOneModulesAlone() = phone { phone ->
        assertEquals(listOf("PageRoutes", "SearchRoutes", "JobsRoutes", "RequestsRoutes", "SyncRoutes", "LibraryRoutes",
                            "LookupRoutes"), phone.modules.map { it::class.simpleName })
        val owners = phone.modules.flatMap { module -> module.routes.map { "${it.method} ${it.path}" to module } }
        val twice = owners.groupBy({ it.first }, { it.second::class.simpleName }).filterValues { it.size > 1 }
        assertEquals(emptyMap(), twice)
        // A stub stands only for a route no module answers yet.
        val stubbed = Stubs().routes.map { "${it.method} ${it.path}" }.toSet()
        assertEquals(emptySet(), stubbed intersect owners.map { it.first }.toSet())
        for (moved in listOf("POST /fetch", "POST /lacuerda/artist", "POST /lacuerda/search", "POST /harptabs/artist",
                             "POST /versions/keep-more", "GET /requests.json", "POST /jobs/again", "POST /lookup",
                             "POST /request", "POST /remove")) {
            assertTrue(moved in owners.map { it.first }, "$moved has a module")
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
        assertEquals(setOf("get", "versions", "lacuerda", "harptabs"), phone.queue.commands.runners.keys)
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
