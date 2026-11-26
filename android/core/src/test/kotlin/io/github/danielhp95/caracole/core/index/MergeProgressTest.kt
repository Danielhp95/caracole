package io.github.danielhp95.caracole.core.index

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
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

/** IndexTransfer.merge's progress, index_transfer.merge's `progress(site, action, done, total)` alike: before it
 * plans, before each site and action once a site changes anything, and after each chunk of UG's sitemaps' rows; and
 * that the chunks take exactly what one statement took. */
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
            val n = merged.sites.size.toLong()
            assertEquals(MergeProgress("", MergeProgress.PLANNING, 0, n), said.first())
            // Each site asked, the i-th from 0 in caracole's order, once any site changes anything.
            assertEquals(merged.sites.keys.mapIndexed { i, site -> MergeProgress(site, "", i.toLong(), n) },
                         said.filter { it.action == "" })
            for ((site, taken) in merged.sites) {
                // Each action before it runs, by its count as Merged says it: UG's sitemaps by their number too.
                val actions = said.filter { it.site == site && it.action != "" && it.action != MergeProgress.TAB }
                assertEquals(taken.map { (noun, count) -> MergeProgress(site, noun, 0, count.toLong()) }, actions, site)
            }
            // UG's sitemaps' rows, after their one chunk: all five, right after the sitemap action's own word.
            val tabs = said.filter { it.action == MergeProgress.TAB }
            assertEquals(listOf(MergeProgress("ug", MergeProgress.TAB, 5, 5)), tabs)
            assertEquals("sitemap", said[said.indexOf(tabs.single()) - 1].action)
        }
    }

    /** Python's chunks: while more than [chunk] rows are left, one of [chunk]; then the rest, its last done == total. */
    private fun chunks(chunk: Long, total: Long): List<Long> {
        val done = ArrayList<Long>()
        var at = 0L
        while (total - at > chunk) {
            at += chunk
            done += at
        }
        return done + total
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
            val done = said.filter { it.action == MergeProgress.TAB }.map { it.done to it.total }
            assertEquals(chunks(chunk.toLong(), 5).map { it to 5L }, done, "chunks of $chunk")
        }
    }

    @Test fun aSitemapOfNoRowsIsOneChunkOfNone() {
        val export = export("full-export")
        BundledSQLiteDriver().open(export.path).let { c ->
            try {
                c.execSQL("DELETE FROM ug_index")
            } finally {
                c.close()
            }
        }
        TestDb.fresh(tmp.newFolder()).use { database ->
            val said = ArrayList<MergeProgress>()
            database.writeBlocking { IndexTransfer.merge(it, export, now, listOf("ug"), progress = { p -> said += p }) }
            assertEquals(listOf(MergeProgress("ug", MergeProgress.TAB, 0, 0)), said.filter { it.action == MergeProgress.TAB })
        }
    }

    /** A file made by hand whose ug_index repeats every tab_id (no primary key): past the chunks the count left
     * promises, no chunk-th row is there, and the rest is the last chunk, never an error; what it takes is what the
     * export's own rows took, its last count done == total. */
    @Test fun aFileThatRepeatsATabIdTakesTheRestInOneLastChunk() {
        fun merged(export: File, chunk: Int, said: MutableList<MergeProgress>): List<String> =
            TestDb.fresh(tmp.newFolder()).use { database ->
                database.writeBlocking { IndexTransfer.seedFresh(it) }
                database.writeBlocking { IndexTransfer.merge(it, export, now, chunk = chunk, progress = { p -> said += p }) }
                database.read { Dumps.lines(it) }
            }
        val whole = merged(export("full-export"), IndexTransfer.UG_CHUNK, ArrayList())
        val twice = export("full-export")
        BundledSQLiteDriver().open(twice.path).let { c ->
            try {
                c.execSQL("ALTER TABLE ug_index RENAME TO ug_once")
                c.execSQL("CREATE TABLE ug_index AS SELECT * FROM ug_once")
                c.execSQL("INSERT INTO ug_index SELECT * FROM ug_once")
                c.execSQL("DROP TABLE ug_once")
            } finally {
                c.close()
            }
        }
        for (chunk in listOf(1, 2, 3, 4)) {
            val said = ArrayList<MergeProgress>()
            assertEquals(whole, merged(twice, chunk, said), "chunks of $chunk")
            val tabs = said.filter { it.action == MergeProgress.TAB }
            assertEquals(10L to 10L, tabs.last().done to tabs.last().total, "chunks of $chunk: $tabs")
            assertTrue(tabs.zipWithNext().all { (a, b) -> a.done < b.done }, "chunks of $chunk: $tabs")
        }
    }

    @Test fun aMergeOfNothingNewerSaysItPlannedAndNothingMore() {
        val export = export("partial-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.merge(it, export, now) }
            val said = ArrayList<MergeProgress>()
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, progress = { p -> said += p }) }
            assertTrue(!merged.changed)
            assertEquals(listOf(MergeProgress("", MergeProgress.PLANNING, 0, 2)), said)
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

    @Test fun eachStepIsSaidInThePhonesWords() {
        assertEquals("Comparing with the phone's index…", MergeProgress("", MergeProgress.PLANNING, 0, 6).words())
        assertEquals("Importing · Ultimate Guitar", MergeProgress("ug", "", 0, 6).words())
        assertEquals("Importing · Ultimate Guitar", MergeProgress("ug", "sitemap", 0, 41).words())
        assertEquals("Importing · Ultimate Guitar · 600,000 of 1,521,145 tabs",
                     MergeProgress("ug", MergeProgress.TAB, 600_000, 1_521_145).words())
        assertEquals("Importing · harptabs.com", MergeProgress("harptabs", "artist page", 0, 12).words())
        assertEquals("Making the search index ready…", MergeProgress("ug", MergeProgress.OPTIMIZE, 0, 0).words())
        assertEquals(MergeProgress("ug", MergeProgress.TAB, 0, 9).step, MergeProgress("ug", MergeProgress.TAB, 5, 9).step)
    }

    @Test fun aSyncsWordsSayWhatIsNewerOnTheComputerOfASiteThePhoneHolds() {
        // index_transfer.MergeWords(held=, there=) alike: of a site the phone held rows of, what is newer there and
        // the rows checked, never "Importing" as if every row were new; a site it held none of, the catalogues' words.
        val words = MergeProgress.Updating(setOf("ug"))
        assertEquals(listOf(
            "Comparing with the phone's index…", "Ultimate Guitar", "Ultimate Guitar · 3 sitemaps newer on the computer",
            "Ultimate Guitar · 3 sitemaps newer on the computer · 50,000 of 117,701 tabs checked",
            "Ultimate Guitar · 12 tabs of its artist pages newer on the computer",
            "Ultimate Guitar · 1 artist of its directory newer on the computer",
            "Importing · gtptabs.com", "Importing · gtptabs.com", "Making the search index ready…",
        ), listOf(
            MergeProgress("", MergeProgress.PLANNING, 0, 2), MergeProgress("ug", "", 0, 2),
            MergeProgress("ug", "sitemap", 0, 3), MergeProgress("ug", MergeProgress.TAB, 50_000, 117_701),
            MergeProgress("ug", "tab of its artist pages", 0, 12), MergeProgress("ug", "artist of its directory", 0, 1),
            MergeProgress("gtptabs", "", 1, 2), MergeProgress("gtptabs", "sitemap", 0, 1),
            MergeProgress("ug", MergeProgress.OPTIMIZE, 0, 0),
        ).map(words::words))
    }

    @Test fun anImportsWordsSayWhatIsNewerInTheFile() {
        val words = MergeProgress.Updating(setOf("ug"), MergeProgress.IN_THE_FILE)
        assertEquals(listOf("Ultimate Guitar · 3 sitemaps newer in the file",
                            "Ultimate Guitar · 3 sitemaps newer in the file · 50,000 of 117,701 tabs checked"),
                     listOf(MergeProgress("ug", "sitemap", 0, 3), MergeProgress("ug", MergeProgress.TAB, 50_000, 117_701))
                         .map(words::words))
    }

    @Test fun aMergeCountsTheRowsOfTheSitemapsItTookAsPythonsDoes() {
        // checked, index_transfer's SiteMerge.checked: the file's rows of each site's first table it took.
        val export = export("full-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now) }
            val counts = database.read { TabCounts.of(it) }
            assertEquals(counts.filterValues { it > 0 }, merged.checked.filterValues { it > 0 },
                         "an empty phone checks every row it takes")
        }
    }

    @Test fun theVectorsReplayInChunksOfOneRowToo() {
        // Every merge of merge.jsonl, UG's sitemaps taken a row a statement: Python's database after, all the same.
        Misses(IndexReplay.MERGE).also { misses -> IndexReplay.mergeAll(misses, chunk = 1) }.assertNone()
    }
}
