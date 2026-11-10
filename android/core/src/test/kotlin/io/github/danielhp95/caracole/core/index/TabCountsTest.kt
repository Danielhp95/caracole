package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** TabCounts: the tabs each site's index tracks, the rows of its first table, in caracole's order. */
class TabCountsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun eachSiteCountsTheRowsOfItsFirstTable() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/reads-before.jsonl") }
            database.read { db ->
                val counts = TabCounts.of(db)
                assertEquals(listOf("ug", "lacuerda", "gtptabs", "musescore", "harptabs", "gametabs"), counts.keys.toList())
                for (site in Sites.ALL) {
                    assertEquals(db.one("SELECT COUNT(*) FROM ${site.tables.first()}") { it.long(0) }, counts[site.name], site.name)
                }
                assertTrue(counts.getValue("lacuerda") > 0, "the fixture's LaCuerda rows")
                assertEquals(0L, counts.getValue("musescore"), "a site with no row")
            }
        }
    }
}
