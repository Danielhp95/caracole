package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.testing.BigIndex
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** FTS5's optimize of UG's full-text indexes after a merge (Warmup.optimizes): after an import's many rows, never after
 * a merge of a few, which FTS5's own automerge keeps, nor of UG's artist pages alone. */
class OptimizeTest {
    @get:Rule val tmp = TemporaryFolder()

    private var was = false

    @Before fun timed() {
        was = Timings.enabled
        Timings.enabled = true
        Timings.take()
    }

    @After fun asItWas() {
        Timings.enabled = was
        Timings.take()
    }

    private fun optimized(): List<String> = Timings.take().map { it.name }.filter { it.startsWith("optimize ") }

    private fun merged(rows: Int, optimizeAfter: Long): List<String> {
        val export = BigIndex(rows).export(File(tmp.newFolder(), "export.sqlite"))
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            Timings.take()
            val merged = database.writeBlocking { db -> IndexTransfer.merge(db, export, "2026-11-03T12:00:00Z",
                                                                             optimizeAfter = optimizeAfter) }
            assertTrue(merged.changed)
            assertEquals(rows.toLong(), database.read { db -> db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } })
        }
        return optimized()
    }

    @Test fun aMergeOfManyOfUgsRowsMakesEachFullTextIndexOneSegment() {
        assertEquals(Warmup.UG_FTS.map { "optimize $it" }, merged(500, optimizeAfter = 1))
    }

    @Test fun aMergeOfAFewIsLeftToFtsOwnMerging() {
        assertEquals(emptyList(), merged(500, optimizeAfter = Warmup.OPTIMIZE_AFTER))
    }

    @Test fun onlyTheSitemapsRowsPastTheThresholdCount() {
        assertTrue(Warmup.optimizes(mapOf("sitemap" to 1), Warmup.OPTIMIZE_AFTER))
        assertFalse(Warmup.optimizes(mapOf("sitemap" to 1), Warmup.OPTIMIZE_AFTER - 1))
        assertFalse(Warmup.optimizes(mapOf("tab of its artist pages" to 400_000), 10_000_000))
        assertFalse(Warmup.optimizes(null, 10_000_000))
    }
}
