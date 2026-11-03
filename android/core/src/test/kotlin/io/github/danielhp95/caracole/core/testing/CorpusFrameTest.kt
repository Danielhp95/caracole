package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.Songs
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** The frame every lane tests through: a migrated database, and a fixture Python wrote replayed into it. */
class CorpusFrameTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun aFreshDatabaseIsCaracolesSchemaAndThePhonesInTheBundledSqlite() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                assertEquals(Database.SQLITE_SOURCE_ID, db.one("SELECT sqlite_source_id()") { it.text(0) })
                assertEquals(Database.SCHEMA_VERSION.toLong(), db.one("PRAGMA user_version") { it.long(0) })
                assertEquals("1", db.kvGet("phone:schema"))
                val tables = db.query("SELECT name FROM sqlite_master WHERE type = 'table'") { it.text(0)!! }
                assertTrue("phone_overrides" in tables && "phone_songbooks" in tables && "ug_keys_fts" in tables)
                assertEquals(16, db.one("SELECT length(value) FROM kv WHERE key = 'sync:id'") { it.long(0)!!.toInt() })
            }
        }
        // Opened again, nothing is migrated twice.
        TestDb.fresh(tmp.root).use { database -> database.read { assertEquals("1", it.kvGet("phone:schema")) } }
    }

    @Test fun theFixturePythonWroteReplaysThroughTheTriggers() {
        val library = tmp.newFolder("library")
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "corpus/fixtures/library.jsonl", library) }
            database.read { db ->
                assertEquals(listOf("radiohead|creep", "song dongye|an he qiao"), Songs.list(db).map { it.key }.sorted())
                assertEquals(listOf("宋冬野"), Songs.byKey(db, "song dongye|an he qiao")!!.artists)
                assertTrue(Songs.isRemoved(db, "eagles|hotel california"))
                val keys = db.query(
                    "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?)", "%police%",
                ) { it.text(0) }
                assertEquals(listOf("karma-police"), keys)
                assertEquals("ok", db.one("PRAGMA integrity_check") { it.text(0) })
                for (table in listOf("ug_artists_fts", "ug_index_fts", "ug_keys_fts")) {
                    db.execute("INSERT INTO $table($table) VALUES ('integrity-check')")
                }
            }
        }
        assertEquals("[Am]Creep\n", File(library, "Radiohead/Creep/sheet.txt").readText())
    }

    @Test fun aRecordReadsAsPythonWroteIt() {
        val header = Corpus.header("corpus/fixtures/library.jsonl")
        assertEquals(JsonPrimitive("corpus/fixtures/library"), header["corpus"])
        assertFailsWith<AssertionError> { Corpus.records("no/such/vector.jsonl") }
    }
}
