package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Dumps
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.IndexReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** IndexTransfer.merge's progress: what it tells as it goes (before planning, before each site and action, and after
 * each chunk of UG's sitemaps' rows), and that the chunks take exactly what one statement took. */
class MergeProgressTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = "2026-11-03T12:00:00Z"

    private fun export(name: String): File =
        File(tmp.newFolder(), "export.sqlite").also { Fixtures.loadRaw(it, "index/fixtures/$name.jsonl") }

    @Test fun aMergeSaysEachStepAsItGoes() {
        val export = export("full-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val said = ArrayList<MergeProgress>()
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, progress = { p -> said += p }) }
            assertEquals(MergeProgress("", MergeProgress.PLAN, 0, merged.sites.size.toLong()), said.first())
            // Each site in caracole's order, its start before its actions, each action as Merged names it.
            val sites = said.filter { it.action == "" }.map { it.site }
            assertEquals(merged.sites.keys.toList(), sites)
            for ((site, taken) in merged.sites) {
                val actions = said.filter { it.site == site && it.action != "" && it.done == 0L }.map { it.action }
                assertEquals(taken.keys.toList(), actions, site)
                assertEquals(MergeProgress(site, "", 0, taken.size.toLong()), said.first { it.site == site })
            }
            // UG's sitemaps by their rows: none taken yet, then all five.
            val rows = said.filter { it.site == "ug" && it.action == "sitemap" }
            assertEquals(listOf(MergeProgress("ug", "sitemap", 0, 5), MergeProgress("ug", "sitemap", 5, 5)), rows)
            // Every other action before it runs, by its own count.
            val harp = said.first { it.site == "harptabs" && it.action == "artist page" }
            assertEquals(merged.sites.getValue("harptabs").getValue("artist page").toLong(), harp.total)
        }
    }

    @Test fun ugsSitemapsAreTakenInChunksExactlyAsOneStatementTookThem() {
        val export = export("full-export")
        fun merged(chunk: Int, said: MutableList<MergeProgress>): List<String> = TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            database.writeBlocking { IndexTransfer.merge(it, export, now, chunk = chunk, progress = { p -> said += p }) }
            database.read { Dumps.lines(it) }
        }
        val whole = merged(IndexTransfer.UG_CHUNK, ArrayList())
        for (chunk in listOf(1, 2, 3, 4, 5, 6)) {
            val said = ArrayList<MergeProgress>()
            assertEquals(whole, merged(chunk, said), "chunks of $chunk")
            val done = said.filter { it.site == "ug" && it.action == "sitemap" }.map { it.done }
            val steps = (0L..5L step chunk.toLong()).toList().let { if (it.last() == 5L) it else it + 5L }
            assertEquals(steps, done, "chunks of $chunk")
        }
    }

    @Test fun aMergeOfNothingNewerSaysItPlannedAndNothingMore() {
        val export = export("partial-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.merge(it, export, now) }
            val said = ArrayList<MergeProgress>()
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, progress = { p -> said += p }) }
            assertTrue(!merged.changed)
            assertEquals(listOf(MergeProgress("", MergeProgress.PLAN, 0, 2)), said)
        }
    }

    @Test fun anImportThatOptimizesSaysSoLast() {
        val export = export("full-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val said = ArrayList<MergeProgress>()
            database.writeBlocking { IndexTransfer.merge(it, export, now, optimizeAfter = 0, progress = { p -> said += p }) }
            assertEquals(MergeProgress("ug", MergeProgress.OPTIMIZE, 0, 0), said.last())
        }
    }

    @Test fun theVectorsReplayInChunksOfOneRowToo() {
        // Every merge of merge.jsonl, UG's sitemaps taken a row a statement: Python's database after, all the same.
        Misses(IndexReplay.MERGE).also { misses -> IndexReplay.mergeAll(misses, chunk = 1) }.assertNone()
    }
}
