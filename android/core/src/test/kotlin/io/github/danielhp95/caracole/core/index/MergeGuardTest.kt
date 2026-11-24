package io.github.danielhp95.caracole.core.index

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.testing.Dumps
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** A merge reads the file as anyone's (index_transfer._meta and _attached): a file of anything but tables (a view, a
 * trigger, an index of its own, a virtual table) is refused before any of it is read, its kv's columns are checked
 * as its sites' tables' are, and no function its schema names runs (trusted_schema off while it is attached). */
class MergeGuardTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = "2026-11-03T12:00:00Z"

    /** The corpus's partial export (gtptabs.com's and MuseScore's), with [sql] run in it. */
    private fun export(vararg sql: String): File {
        val file = File(tmp.newFolder(), "export.sqlite")
        Fixtures.loadRaw(file, "index/fixtures/partial-export.jsonl")
        val c = BundledSQLiteDriver().open(file.path)
        try {
            for (statement in sql) c.execSQL(statement)
        } finally {
            c.close()
        }
        return file
    }

    /** [file] refused, its words, the phone as it was and the file detached. */
    private fun refused(file: File): String = TestDb.fresh(tmp.newFolder()).use { database ->
        val before = database.read { Dumps.lines(it) }
        val e = assertFailsWith<TransferError> { database.writeBlocking { IndexTransfer.merge(it, file, now) } }
        assertEquals(before, database.read { Dumps.lines(it) })
        assertEquals(listOf("main"), database.writeBlocking { db ->
            db.query("PRAGMA database_list") { it.text(1)!! }.filter { it != "temp" }
        })
        e.message!!
    }

    @Test fun aViewInPlaceOfATableIsRefusedBeforeItIsRead() {
        // A view whose reading never ends, of musescore_index's columns: refused before it is ever read.
        val file = export(
            "DROP TABLE musescore_index",
            "CREATE VIEW musescore_index (page_id, path, title_key, sitemap) AS " +
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT i, 'p', 't', 's' FROM n",
        )
        val words = refused(file)
        assertEquals("$file holds the view musescore_index, and an index export of caracole's holds tables alone: " +
                         "`caracole index export` makes one", words)
    }

    @Test fun aTriggerAnIndexOfItsOwnOrAVirtualTableIsRefused() {
        for ((sql, said) in listOf(
            "CREATE TRIGGER noisy AFTER INSERT ON kv BEGIN SELECT 1; END" to "the trigger noisy",
            "CREATE INDEX gtptabs_by_title ON gtptabs_index(title_key)" to "the index gtptabs_by_title",
            "CREATE VIRTUAL TABLE words USING fts5(word)" to "the table words",
        )) {
            val words = refused(export(sql))
            assertTrue(words.contains("holds $said, and an index export of caracole's holds tables alone"), words)
        }
    }

    @Test fun aTableOfItsOwnIsNoReasonToRefuseIt() {
        // A plain table no merge reads (a padding, a newer caracole's): taken as Python takes it.
        val file = export("CREATE TABLE padding (bytes BLOB NOT NULL)")
        TestDb.fresh(tmp.newFolder()).use { database ->
            assertTrue(database.writeBlocking { IndexTransfer.merge(it, file, now) }.changed)
        }
    }

    @Test fun itsKvsColumnsAreCheckedAsItsTablesAre() {
        val file = export("ALTER TABLE kv ADD COLUMN extra TEXT")
        val words = refused(file)
        assertEquals("$file's kv has the columns (key, value, extra), and the database's (key, value): nothing changed",
                     words)
    }

    @Test fun noFunctionOfItsSchemaRunsWhileItIsAttached() {
        val file = export()
        TestDb.fresh(tmp.newFolder()).use { database ->
            fun trusted() = database.writeBlocking { db -> db.one("PRAGMA trusted_schema") { it.long(0)!! }!! }
            val before = trusted()
            val during = ArrayList<Long>()
            database.writeBlocking { db ->
                IndexTransfer.merge(db, file, now, progress = { during += db.one("PRAGMA trusted_schema") { it.long(0)!! }!! })
            }
            assertTrue(during.isNotEmpty())
            assertEquals(setOf(0L), during.toSet(), "trusted_schema off while the file is attached")
            assertEquals(before, trusted(), "and as it was after")
            // A refusal sets it back too.
            val odd = export("CREATE TRIGGER noisy AFTER INSERT ON kv BEGIN SELECT 1; END")
            assertFailsWith<TransferError> { database.writeBlocking { IndexTransfer.merge(it, odd, now) } }
            assertEquals(before, trusted())
        }
    }
}
