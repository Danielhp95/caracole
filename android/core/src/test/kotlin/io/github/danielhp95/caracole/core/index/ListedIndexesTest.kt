package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.UgDirectory
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ListedIndexes.newest: how fresh a phone's site indexes are by their sitemap and listing records alone (the app's
 * Settings row for a phone whose indexes came from a `.caracole` file or an index import), never the pages a phone
 * reads itself, which IndexTransfer.newest counts too. Each record written through Merge's own keys, so a key renamed
 * in core is renamed here.
 */
class ListedIndexesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = "2026-11-03T12:00:00Z"
    private val merged = "2026-10-28T03:30:00Z"  // every record of the full export is of that time

    private fun export(name: String): File =
        File(tmp.newFolder(), "export.sqlite").also { Fixtures.loadRaw(it, "index/fixtures/$name.jsonl") }

    @Test fun aFreshPhoneHasNone() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            assertNull(database.read { ListedIndexes.newest(it) })
        }
    }

    @Test fun anIndexMergedIsDatedByItsSitemapsAndListingsNeverThePhonesOwnPageReads() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            database.writeBlocking { IndexTransfer.merge(it, export("full-export"), now) }
            assertEquals(merged, database.read { ListedIndexes.newest(it) })
            // Pages the phone reads itself, later: a lookup's UG artist page, an artist's Songs on harptabs.com, a
            // game page, a directory artist's page. IndexTransfer.newest moves with them; this doesn't.
            val later = "2026-11-20T09:00:00Z"
            database.writeBlocking { db ->
                for (table in listOf("ug_artist_tabs", "harptabs_artists", "gametabs_games")) {
                    db.execute("UPDATE $table SET read_at = ?", later)
                }
                db.execute("UPDATE ug_directory SET read_at = ? WHERE read_at <> ''", later)
            }
            assertTrue(database.read { IndexTransfer.newest(it) }.values.contains(later), "the reads are newer")
            assertEquals(merged, database.read { ListedIndexes.newest(it) })
        }
    }

    @Test fun eachSitemapAndListingRecordCounts() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            database.writeBlocking { IndexTransfer.merge(it, export("full-export"), now) }
            var day = 1
            /** [write] a record a day later than the last: the newest is it. */
            fun later(what: String, write: (Db, String) -> Unit) {
                val at = "2026-11-%02dT00:00:00Z".format(day++)
                database.writeBlocking { write(it, at) }
                assertEquals(at, database.read { ListedIndexes.newest(it) }, what)
            }
            fun records(field: String, at: String) = """{"a-sitemap.xml": {"$field": "$at", "etag": "x"}}"""
            later("UG's sitemaps") { db, at -> db.kvSet(Merge.UG_SITEMAPS, records("indexed_at", at)) }
            later("UG's index refreshed") { db, at -> db.kvSet(Merge.UG_REFRESHED, at) }
            later("UG's index built") { db, at -> db.kvSet(Merge.UG_BUILT, at) }
            later("UG's directory's listings seen") { db, at -> db.execute("UPDATE ug_directory SET seen_at = ?", at) }
            later("a directory listing's round begun") { db, at ->
                db.kvSet(UgDirectory.LETTERS_KEY, """{"t": {"pages": 1, "started": "$at", "next": 2}}""")
            }
            later("a directory listing's round done") { db, at ->
                db.kvSet(UgDirectory.LETTERS_KEY, """{"t": {"pages": 1, "done": "$at"}}""")
            }
            later("LaCuerda's listing pages") { db, at -> db.kvSet(Merge.LC_PAGES, records("checked_at", at)) }
            later("LaCuerda's listings read whole") { db, at -> db.kvSet(Merge.LC_COMPLETE, at) }
            for (site in listOf("gtptabs", "musescore", "harptabs", "gametabs")) {
                later("$site's sitemaps") { db, at -> db.kvSet(Merge.sitemapsKey(site), records("checked_at", at)) }
                later("$site's index read whole") { db, at -> db.kvSet(Merge.completeKey(site), at) }
            }
            // A record that isn't a time, or isn't a record, counts for nothing.
            val last = database.read { ListedIndexes.newest(it) }
            database.writeBlocking { db ->
                db.kvSet(Merge.sitemapsKey("gtptabs"), """{"a.xml": {"checked_at": "soon"}, "b.xml": 3}""")
                db.kvSet(Merge.UG_REFRESHED, "not a time")
            }
            assertEquals(last, database.read { ListedIndexes.newest(it) })
        }
    }
}
