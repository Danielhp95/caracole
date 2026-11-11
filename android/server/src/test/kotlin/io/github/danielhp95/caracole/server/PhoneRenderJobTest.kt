package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The phone's own render job on its real queue, with its real lookups (lane phone-render): what PhoneRenderTest
 * shows with a `between` of its own, through JobContext.yieldToQueued and GetRunner's pdf stage. */
class PhoneRenderJobTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    /** A case's fixture from vectors/viewer/render.jsonl, in [database] and [library]. */
    private fun load(database: Database, library: File, case: String) {
        val record = Corpus.records("viewer/render.jsonl").first { it.extra["case"] == JsonPrimitive(case) }
        database.writeBlocking { db -> Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, library) }
    }

    @Test fun aLookupQueuedWhileTheRenderJobRunsRunsBetweenTwoSongsAndMakesItsSongsPagesItself() {
        val scope = CoroutineScope(SupervisorJob())
        try {
            TestDb.fresh(tmp.root).use { database ->
                val library = tmp.newFolder("library")
                load(database, library, "own_versions") // three songs, the render job's order newest first
                val deps = PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress,
                                     secret = "s".repeat(64), csrf = "tok", transport = { RefusingTransport })
                val said = CopyOnWriteArrayList<String>()
                var phone: Phone? = null
                var lookup: Int? = null
                // The render job's own `between`, the queue's yieldToQueued, with a lookup queued before the first
                // (Hotel California, the oldest: the job's last song), as the library page's Get it would.
                val render = object : PhoneRender(deps.database, deps.libraryDir, deps.mirror, deps.version) {
                    override fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit): RenderStats =
                        super.renderStale(between = {
                            val queue = phone!!.queue
                            if (lookup == null) {
                                lookup = queue.submit(JobSpec("Look it up", "eagles/hotel california", "song",
                                                              emptyList(),
                                                              commands = JobCommands.lookupSteps("Eagles", "Hotel California")))
                                    .first.id
                            }
                            between()
                            said += "between: the lookup ${queue.snapshot().first { it.id == lookup }.state}"
                        }) { done, total ->
                            said += "$done of $total"
                            progress(done, total)
                        }
                }
                phone = Phone(deps, render)
                assertTrue(render.stale())
                val job = phone.renderAgain()
                val over = runBlocking { withTimeout(120_000) { phone.queue.await(job.id) } }
                assertEquals(Job.DONE, over.state, "${over.stages.single().detail}")
                assertEquals(listOf("0 of 3", "1 of 3", "between: the lookup ${Job.DONE}", "2 of 3",
                                    "between: the lookup ${Job.DONE}", "3 of 3"), said)
                // the lookup made its song's pages in its pdf stage; the job passed over it, made the other two
                val looked = runBlocking { phone.queue.await(lookup!!) }
                val pdf = looked.stages.first { it.name == "pdf" }
                assertEquals("done" to LookupWords.PAGES_MADE, pdf.state to pdf.detail)
                assertEquals("Pages remade · 2 songs", over.stages.single().detail)
                assertTrue(File(library, "Eagles/Hotel California/sheet.html").isFile)
                val hotel = database.read { db -> db.one("SELECT id FROM songs WHERE title = 'Hotel California'") { it.long(0)!! }!! }
                assertTrue(database.read { db -> WrittenPages.current(db, hotel, "sheet.html") })
                assertTrue(database.read { db -> render.owed(db).isEmpty() })
                assertTrue(!render.stale())
            }
        } finally {
            scope.cancel()
        }
    }
}
