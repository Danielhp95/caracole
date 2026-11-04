package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.IndexExportReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * IndexExport, the phone's index pages for the computer: every record of vectors/index/export.jsonl replayed
 * (IndexExportReplay, which the device runs too), and what a vector can't say: an export is a file a merge takes, it
 * refuses a file there already, the database itself and a folder that isn't one, leaving nothing behind, and it runs
 * on the writer in no transaction, the file detached after.
 */
class ExportTest {
    @get:Rule val tmp = TemporaryFolder()

    private val pages = mapOf(
        "ug" to listOf("https://www.ultimate-guitar.com/artist/634073"),
        "lacuerda" to listOf("estopa/", "busca.php"),
        "harptabs" to listOf("artist/1178/billy-joel"),
    )

    @Test fun everyRecordOfExportJsonlIsPythons() {
        val misses = Misses("index/export.jsonl")
        IndexExportReplay.replay(misses)
        misses.assertNone()
        assertEquals(6, Corpus.records("index/export.jsonl").size)
    }

    @Test fun thePhonesExportIsAFileAMergeTakesWholeAndAgainTakesNothing() {
        val phoneDir = tmp.newFolder()
        val export = File(tmp.newFolder(), "reads.sqlite")
        TestDb.fresh(phoneDir).use { phone ->
            phone.writeBlocking { Fixtures.load(it, "index/fixtures/reads-before.jsonl") }
            val exported = phone.writeBlocking { IndexExport.export(it, export, pages, "2026-11-03T12:00:00Z") }
            assertEquals(listOf("ug", "lacuerda", "harptabs"), exported.sites)
            assertEquals(mapOf("ug_index" to 0, "ug_artist_tabs" to 2, "lacuerda_index" to 2, "harptabs_index" to 0,
                               "harptabs_artists" to 1, "harptabs_artist_tabs" to 1), exported.rows)
            // The writer is left with its own database alone.
            assertEquals(listOf("main"), phone.writeBlocking { db ->
                db.query("PRAGMA database_list") { it.text(1)!! }.filter { it != "temp" }
            })
        }
        TestDb.fresh(tmp.newFolder()).use { computer ->
            computer.writeBlocking { IndexTransfer.seedFresh(it) }
            val merged = computer.writeBlocking { IndexTransfer.merge(it, export, "2026-11-03T12:00:00Z") }
            assertTrue(merged.changed)
            assertEquals(mapOf("tab of its artist pages" to 2), merged.sites["ug"])
            assertEquals(mapOf("artist page" to 1, "row of its search's answers" to 1), merged.sites["lacuerda"])
            assertEquals(mapOf("artist page" to 1), merged.sites["harptabs"])
            assertEquals(2L, computer.read { db -> db.one("SELECT COUNT(*) FROM ug_artist_tabs") { it.long(0) } })
            assertFalse(computer.writeBlocking { IndexTransfer.merge(it, export, "2026-11-03T12:00:00Z") }.changed)
        }
    }

    @Test fun aFileThereAlreadyTheDatabaseItselfAndNoFolderAreRefusedLeavingNothing() {
        val dir = tmp.newFolder()
        val there = File(dir, "there.sqlite").apply { writeBytes("mine".toByteArray()) }
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/reads-before.jsonl") }
            val exists = assertFailsWith<TransferError> { database.writeBlocking { IndexExport.export(it, there, pages) } }
            assertTrue(exists.message!!.endsWith("already exists: name a new file, or remove that one first"))
            assertEquals("mine", there.readText())
            val itself = assertFailsWith<TransferError> {
                database.writeBlocking { IndexExport.export(it, database.path, pages) }
            }
            assertTrue(itself.message!!.endsWith("is the database itself: name a new file"))
            val nowhere = assertFailsWith<TransferError> {
                database.writeBlocking { IndexExport.export(it, File(dir, "nowhere/reads.sqlite"), pages) }
            }
            assertTrue(nowhere.message!!.endsWith("is no folder: name a file in one"))
            val sitemaps = assertFailsWith<TransferError> {
                database.writeBlocking { IndexExport.export(it, File(dir, "x.sqlite"), mapOf("musescore" to listOf("x"))) }
            }
            assertEquals("MuseScore's index has no pages a lookup reads, its sitemaps alone: pages are of ug, " +
                             "lacuerda, harptabs, gametabs", sitemaps.message)
        }
        assertEquals(listOf("caracole.sqlite", "there.sqlite"),
                     dir.list()!!.filter { !it.startsWith("caracole.sqlite-") }.sorted())
    }

    @Test fun anExportRunsInNoTransactionOfTheCallers() {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            assertFailsWith<IllegalStateException> {
                database.writeBlocking { db ->
                    db.savepoint("callers") { IndexExport.export(db, File(dir, "reads.sqlite"), pages) }
                }
            }
            assertFalse(File(dir, "reads.sqlite").exists())
        }
    }

    /** Export.kt's contract with the site lanes (IndexExport.PAGES): a page noted as its store writes it (UG's
     * address whole, LaCuerda's "<slug>/" and "busca.php", harptabs.com's and gametabs.net's paths) sends its rows,
     * through Reads.since; another spelling of the same page (a path for UG's address, a slug without its slash)
     * sends none. */
    @Test fun aPageNotedAsItsStoreWritesItIsSentAndAnotherSpellingIsNot() {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "index/fixtures/reads-before.jsonl")
                db.execute("DELETE FROM kv WHERE key LIKE 'phone:%'")
                Reads.note(db, "ug", "https://www.ultimate-guitar.com/artist/634073", "2026-11-03T10:00:00Z")
                Reads.note(db, "lacuerda", "estopa/", "2026-11-03T10:00:01Z")
                Reads.note(db, "lacuerda", "busca.php", "2026-11-03T10:00:02Z")
                Reads.note(db, "harptabs", "artist/1178/billy-joel", "2026-11-03T10:00:03Z")
                Reads.note(db, "gametabs", "tabs/actraiser", "2026-11-03T10:00:04Z")
            }
            val rows = database.writeBlocking { db ->
                IndexExport.export(db, File(dir, "as-stored.sqlite"), Reads.since(db, "pc"), "2026-11-03T12:00:00Z").rows
            }
            for (table in listOf("ug_artist_tabs", "lacuerda_index", "harptabs_artists", "harptabs_artist_tabs",
                                 "gametabs_games", "gametabs_game_tabs")) {
                assertTrue(rows.getValue(table) > 0, "$table: no row of a page noted as its store writes it")
            }
            val other = database.writeBlocking { db ->
                IndexExport.export(db, File(dir, "other.sqlite"), mapOf(
                    "ug" to listOf("/artist/634073"), "lacuerda" to listOf("estopa"),
                    "harptabs" to listOf("/artist/1178/billy-joel"), "gametabs" to listOf("actraiser"),
                ), "2026-11-03T12:00:00Z").rows
            }
            assertEquals(setOf(0), other.values.toSet(), "another spelling of the same page sends no row")
        }
    }

    @Test fun anExportOfNoPageIsOfNoSite() {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            val exported = database.writeBlocking { IndexExport.export(it, File(dir, "none.sqlite"), emptyMap()) }
            assertEquals(emptyList(), exported.sites)
            assertEquals(emptyMap(), exported.rows)
            assertEquals(listOf("""{"sql":"CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"}""",
                                """{"sql":"CREATE TABLE caracole_export (key TEXT PRIMARY KEY, value TEXT NOT NULL)"}"""),
                         IndexExportReplay.rawLines(File(dir, "none.sqlite")).take(2))
        }
    }
}
