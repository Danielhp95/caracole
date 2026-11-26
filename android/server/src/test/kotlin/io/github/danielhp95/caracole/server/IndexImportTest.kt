package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.MergedIndexes
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Phone.importIndex, the device tests' and the e2e's way to give the phone the computer's index: its stage says each
 * step of the merge as it goes, as a sync's index stage says them, each with one "…" at most, its line's own. */
class IndexImportTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    /** A job's context that keeps every stage it is told. */
    private class Told : JobContext {
        val stages = ArrayList<Triple<String, String, String>>()
        override fun stage(name: String, state: String, detail: String) {
            stages += Triple(name, state, detail)
        }
        override fun say(line: String) = Unit
        override fun outcome(value: JsonObject) = Unit
        override val isCancelled: Boolean = false
    }

    /** The corpus's partial export (gtptabs.com's and MuseScore's indexes) imported by a phone of its own: what the
     * job's stage was told, and the phone's database after it. */
    private fun imported(check: (Told, File, Database) -> Unit) {
        val scope = CoroutineScope(SupervisorJob())
        try {
            TestDb.fresh(tmp.newFolder("db")).use { database ->
                val state = tmp.newFolder("state")
                val deps = PhoneDeps(database, tmp.newFolder("library"), state, null, scope, NoAddress,
                                     secret = "s".repeat(64), csrf = "tok", transport = { RefusingTransport })
                val phone = Phone(deps)
                val export = File(tmp.newFolder(), "export.sqlite")
                Fixtures.loadRaw(export, "index/fixtures/partial-export.jsonl")
                val told = Told()
                runBlocking { phone.importSpec(export).run!!(told) }
                check(told, export, database)
            }
        } finally {
            scope.cancel()
        }
    }

    @Test fun itsStageSaysEachStepOfTheMerge() = imported { told, export, _ ->
        val running = told.stages.filter { it.second == "running" }.map { it.third }
        assertEquals(listOf("", "Comparing with the phone's index", "Importing · gtptabs.com",
                            "Importing · MuseScore", "Tidying the database"), running)
        assertTrue(running.none { it.endsWith("…") }, "$running")
        assertEquals(Triple("merge", "done", "merged"), told.stages.last())
        assertFalse(export.exists(), "the file is deleted after")
    }

    /** What the file read of each site, recorded (MergedIndexes), so that the next sync with the computer asks it for
     * a site only once its index is newer than the file's. */
    @Test fun itRecordsWhatTheFileReadForTheNextSync() = imported { _, _, database ->
        assertEquals("""{"gtptabs": "2026-10-28T03:30:00Z", "musescore": "2026-10-28T03:30:00Z"}""",
                     database.read { it.kvGet(MergedIndexes.KEY) })
    }
}
