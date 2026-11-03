package io.github.danielhp95.caracole.core.db

import androidx.sqlite.SQLiteConnection
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** core.db.Database is db.py on the phone: its schema to the byte (vectors/schema/, tests/test_conformance_schema.py),
 * its migrations and their backup rule, the bundled SQLite and its FTS5, savepoints, kv and the bound values. */
class DatabaseTest {
    @get:Rule val tmp = TemporaryFolder()

    private val file get() = File(tmp.root, "caracole.sqlite")

    private fun raw(path: File = file): SQLiteConnection = BundledSQLiteDriver().open(path.path)

    private fun SQLiteConnection.long(sql: String): Long = prepare(sql).use { it.step(); it.getLong(0) }

    /** A database db.py's migrations took to [version] alone, as an older caracole left it. */
    private fun migratedTo(version: Int, path: File = file) {
        raw(path).use { c ->
            for ((v, statements) in Database.migrations.filterKeys { it <= version }) {
                c.execSQL("BEGIN IMMEDIATE")
                for (statement in statements) c.prepare(statement).use { while (it.step()) Unit }
                c.execSQL("PRAGMA user_version = $v")
                c.execSQL("COMMIT")
            }
            c.execSQL("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                "VALUES ('radiohead|creep', 'Radiohead', 'Creep', '[\"Radiohead\"]', 'x', 'x', 'x')")
        }
    }

    private fun backups(): List<String> = tmp.root.list()!!.filter { ".bak" in it || it.endsWith(".part") }.sorted()

    @Test fun theMigratedSchemaIsPythonsToTheByte() {
        val want = Corpus.json("schema/sqlite_master.json").getValue("objects").jsonArray.map { o ->
            listOf("type", "name", "tbl_name", "sql").map { o.jsonObject.getValue(it).jsonPrimitive.contentOrNull }
        }
        TestDb.fresh(tmp.root).use { database ->
            val got = database.read { db ->
                db.query("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name") { r ->
                    listOf(r.text(0), r.text(1), r.text(2), r.text(3))
                }
            }
            // The phone's own tables are phone.sql's, beside caracole's; nothing else differs.
            val phones = got.filter { it[2]!!.startsWith("phone_") }
            assertEquals(setOf("phone_overrides", "phone_songbooks"), phones.map { it[2] }.toSet())
            assertEquals(want, got - phones.toSet())
        }
    }

    @Test fun everyTablesColumnsArePythons() {
        val want = Corpus.json("schema/pragmas.json").getValue("tables").jsonObject
        TestDb.fresh(tmp.root).use { database ->
            val got = database.read { db ->
                val names = db.query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name") { it.text(0)!! }
                names.filterNot { it.startsWith("phone_") }.associateWith { name ->
                    db.query("PRAGMA table_info(\"$name\")") { r ->
                        JsonObject(linkedMapOf(
                            "cid" to JsonPrimitive(r.long(0)), "name" to JsonPrimitive(r.text(1)),
                            "type" to JsonPrimitive(r.text(2)), "notnull" to JsonPrimitive(r.long(3)),
                            "dflt_value" to (r.text(4)?.let { JsonPrimitive(it) } ?: JsonNull),
                            "pk" to JsonPrimitive(r.long(5)),
                        ))
                    }
                }
            }
            assertEquals(want.keys, got.keys)
            for ((name, columns) in got) assertEquals(want.getValue(name).jsonArray.toList(), columns, name)
        }
    }

    @Test fun theSchemaVersionIsMigrationsJsons() {
        val root = Json.parseToJsonElement(Database.resource("caracole/schema/migrations.json")).jsonObject
        assertEquals(Database.SCHEMA_VERSION, root.getValue("schema").jsonPrimitive.int)
        assertEquals((1..Database.SCHEMA_VERSION).toList(), Database.migrations.keys.toList())
        TestDb.fresh(tmp.root).use { database ->
            assertEquals(Database.SCHEMA_VERSION.toLong(), database.read { db -> db.one("PRAGMA user_version") { it.long(0) } })
        }
    }

    @Test fun itIsTheBundledSqliteWithFts5() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                assertEquals(Database.SQLITE_SOURCE_ID, db.one("SELECT sqlite_source_id()") { it.text(0) })
                assertEquals("3.50.1", db.one("SELECT sqlite_version()") { it.text(0) })
                val options = db.query("PRAGMA compile_options") { it.text(0)!! }
                assertTrue("ENABLE_FTS5" in options, "compile options: $options")
                assertTrue("THREADSAFE=2" in options, "compile options: $options")
                assertEquals(listOf("1", "a", null), db.query("SELECT value FROM json_each('[1, \"a\", null]')") { it.text(0) })
            }
        }
    }

    @Test fun everyConnectionKeepsDbPysPragmasAndTheBusyTimeout() {
        TestDb.fresh(tmp.root).use { database ->
            fun pragmas(db: Db) = listOf("foreign_keys", "journal_mode", "synchronous", "busy_timeout")
                .map { p -> db.one("PRAGMA $p") { it.text(0) } }
            val want = listOf("1", "wal", "1", Database.BUSY_TIMEOUT_MS.toString())
            assertEquals(want, database.writeBlocking { pragmas(it) })
            // The four readers, each lent at once.
            val seen = database.read { a -> database.read { b -> database.read { c -> database.read { d ->
                listOf(a, b, c, d).map { it.raw }.toSet().size.also { listOf(a, b, c, d).forEach { db -> assertEquals(want, pragmas(db)) } }
            } } } }
            assertEquals(4, seen)
        }
    }

    @Test fun aNewerDatabaseIsTooNewAndUntouched() {
        raw().use { it.execSQL("PRAGMA user_version = ${Database.SCHEMA_VERSION + 1}") }
        val error = assertFailsWith<DatabaseTooNew> { Database(file) }
        assertTrue("schema version ${Database.SCHEMA_VERSION + 1}" in error.message!!, error.message)
        assertEquals((Database.SCHEMA_VERSION + 1).toLong(), raw().use { it.long("PRAGMA user_version") })
        assertEquals(0L, raw().use { it.long("SELECT count(*) FROM sqlite_master") })
        assertEquals(emptyList(), backups())
    }

    @Test fun aTooNewDatabaseNamesTheCopyToRestoreWhenThereIsOne() {
        migratedTo(Database.SCHEMA_VERSION)
        raw().use { it.execSQL("PRAGMA user_version = ${Database.SCHEMA_VERSION + 1}") }
        File(file.path + ".v${Database.SCHEMA_VERSION}.bak").writeText("")
        val error = assertFailsWith<DatabaseTooNew> { Database(file) }
        assertTrue("caracole.sqlite.v${Database.SCHEMA_VERSION}.bak" in error.message!!, error.message)
    }

    @Test fun aFreshDatabaseIsMigratedWithNoCopyAndOneAtTheLatestIsLeftAlone() {
        TestDb.fresh(tmp.root).close()
        assertEquals(emptyList(), backups())
        val id = TestDb.fresh(tmp.root).use { d -> d.read { it.kvGet("sync:id") } }
        assertEquals(emptyList(), backups())
        assertEquals(16, id!!.length)
        assertEquals(id, TestDb.fresh(tmp.root).use { d -> d.read { it.kvGet("sync:id") } })
    }

    @Test fun anOlderDatabaseIsCopiedAsItWasThenMigrated() {
        migratedTo(7)
        Database(file).use { database ->
            assertEquals(Database.SCHEMA_VERSION.toLong(), database.read { db -> db.one("PRAGMA user_version") { it.long(0) } })
            assertEquals("Creep", database.read { db -> db.one("SELECT title FROM songs") { it.text(0) } })
        }
        assertEquals(listOf("caracole.sqlite.v7.bak"), backups())
        raw(File(file.path + ".v7.bak")).use { copy ->
            assertEquals(7L, copy.long("PRAGMA user_version"))
            assertEquals(1L, copy.long("SELECT count(*) FROM songs"))
            assertEquals(0L, copy.long("SELECT count(*) FROM sqlite_master WHERE name = 'ug_artists_fts'"))
        }
        // At the latest, opened again, nothing is copied again.
        Database(file).close()
        assertEquals(listOf("caracole.sqlite.v7.bak"), backups())
    }

    @Test fun aMigrationThatFailsLeavesTheDatabaseAtTheVersionBefore() {
        migratedTo(13)
        // What migration 14 drops is gone: its DROP TRIGGER fails, and its transaction with it.
        raw().use { it.execSQL("DROP TRIGGER ug_keys_words") }
        assertFailsWith<Exception> { Database(file) }
        raw().use { c ->
            assertEquals(13L, c.long("PRAGMA user_version"))
            assertEquals(0L, c.long("SELECT count(*) FROM sqlite_master WHERE name = 'ug_keys_words'"))
        }
        assertEquals(listOf("caracole.sqlite.v13.bak"), backups())
    }

    @Test fun databasesOpenedAtOnceOnOnePathMigrateItOnce() {
        val pool = Executors.newFixedThreadPool(6)
        val start = CountDownLatch(1)
        try {
            val opened = (1..6).map { pool.submit<String?> { start.await(); Database(file, readers = 1).use { d -> d.read { it.kvGet("sync:id") } } } }
            start.countDown()
            val ids = opened.map { it.get(60, TimeUnit.SECONDS) }
            assertEquals(1, ids.toSet().size, "one sync:id: $ids")
        } finally {
            pool.shutdownNow()
        }
        raw().use { assertEquals(1L, it.long("SELECT count(*) FROM kv WHERE key = 'sync:id'")) }
    }

    @Test fun nestedSavepointsRollBackAlone() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.savepoint("outer") {
                    db.kvSet("a", "1")
                    assertFailsWith<IllegalStateException> {
                        db.savepoint("inner") {
                            db.kvSet("b", "2")
                            assertEquals("2", db.kvGet("b"))
                            error("undone")
                        }
                    }
                    assertNull(db.kvGet("b"))
                    assertEquals("1", db.kvGet("a"))
                    // One of the same name nests too.
                    db.savepoint("outer") { db.kvSet("c", "3") }
                }
                assertEquals(listOf("1", null, "3"), listOf("a", "b", "c").map { db.kvGet(it) })
                assertFailsWith<IllegalStateException> {
                    db.savepoint("whole") {
                        db.kvSet("d", "4")
                        db.savepoint("part") { db.kvSet("e", "5") }
                        error("undone")
                    }
                }
                assertEquals(listOf(null, null), listOf("d", "e").map { db.kvGet(it) })
                assertFalse(db.raw.inTransaction())
                assertFailsWith<IllegalArgumentException> { db.savepoint("not a name; DROP TABLE kv") {} }
            }
        }
    }

    @Test fun kvIsDbPys() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.kvSet("k", "one")
                db.kvSet("k", "two")
                assertEquals("two", db.kvGet("k"))
                db.kvSet("j", "{\"a\": [1, 2.5, null]}")
                assertEquals(Json.parseToJsonElement("{\"a\":[1,2.5,null]}"), db.kvGetJson("j"))
                db.kvDelete("k")
                assertNull(db.kvGet("k"))
                assertNull(db.kvGetJson("k"))
            }
        }
    }

    @Test fun everyKindOfValueBindsAsSqliteHoldsIt() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                val kinds = db.one("SELECT typeof(?), typeof(?), typeof(?), typeof(?), typeof(?), typeof(?), typeof(?)",
                    5L, 6, 2.5, "text", byteArrayOf(1, 2), true, null) { r -> (0 until 7).map { r.text(it) } }
                assertEquals(listOf("integer", "integer", "real", "text", "blob", "integer", "null"), kinds)
                assertEquals(listOf(1L, 0L), db.one("SELECT ?, ?", true, false) { listOf(it.long(0), it.long(1)) })
                assertEquals("0102FF", db.one("SELECT hex(?)", byteArrayOf(1, 2, -1)) { it.text(0) })
                assertEquals(Long.MAX_VALUE, db.one("SELECT ?", Long.MAX_VALUE) { it.long(0) })
                assertEquals("宋冬野 😀", db.one("SELECT ?", "宋冬野 😀") { it.text(0) })
                assertTrue(db.one("SELECT ? IS NULL", null) { it.long(0) } == 1L)
                assertFailsWith<IllegalArgumentException> { db.one("SELECT ?", listOf(1)) { it.text(0) } }
            }
        }
    }

    @Test fun aListOfValuesIsKeptUnderSqlitesVariables() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                // The numbers 0 to 69,999, and how many of them a list of values holds.
                fun counted(values: Array<Any?>) = db.one("WITH RECURSIVE n(x) AS (SELECT 0 UNION ALL SELECT x + 1 FROM n " +
                    "WHERE x < 69999) SELECT count(*) FROM n WHERE x IN (${values.joinToString(",") { "?" }})", *values) { it.long(0)!! }!!
                val most = Array<Any?>(Db.MAX_VARIABLES) { it.toLong() }
                assertEquals(Db.MAX_VARIABLES.toLong(), counted(most))
                val more = Array<Any?>(Db.MAX_VARIABLES + 1) { it.toLong() }
                val error = assertFailsWith<IllegalArgumentException> {
                    db.one("SELECT ${more.joinToString(",") { "?" }}", *more) { it.long(0) }
                }
                assertTrue("${Db.MAX_VARIABLES}" in error.message!!, error.message)
                // Db.chunks keeps a long list in lists SQLite takes.
                val ids = (0L until 70_000L).toList()
                assertEquals(70_000L, Db.chunks(ids).sumOf { part -> counted(part.toTypedArray()) })
                assertEquals(listOf(32_766, 32_766, 4_468), Db.chunks(ids).map { it.size })
                assertTrue(Db.chunks(ids).all { it.size <= Db.MAX_VARIABLES })
            }
        }
    }

    @Test fun executeCountsTheRowsItChangedAndLastRowidTheRowItAdded() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                assertEquals(1, db.execute("INSERT INTO removed (key, artist, title, removed_at) VALUES (?, ?, ?, ?)",
                    "a|b", "A", "B", "x"))
                val rowid = db.lastRowid()
                assertEquals(rowid, db.one("SELECT rowid FROM removed WHERE key = 'a|b'") { it.long(0) })
                db.execute("INSERT INTO removed (key, artist, title, removed_at) VALUES ('c|d', 'C', 'D', 'x')")
                assertEquals(2, db.execute("UPDATE removed SET removed_at = 'y'"))
                assertEquals(0, db.execute("DELETE FROM removed WHERE key = 'none'"))
            }
        }
    }

    @Test fun integrityHoldsAfterRowsGoInThroughTheTriggers() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.savepoint("rows") {
                    for ((id, artist, song) in listOf(Triple(1, "radiohead", "creep"), Triple(2, "radiohead", "karma-police"),
                        Triple(3, "song-dongye", "an-he-qiao"), Triple(4, "los-del-rio", "macarena"))) {
                        db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                            "VALUES (?, ?, ?, 'Chords', 'tabs1.xml', 'x', ?)", id, artist, song, "tab/$artist/$song-chords-$id")
                    }
                    db.execute("UPDATE ug_index SET song_key = 'creep-acoustic' WHERE tab_id = 1")
                    db.execute("DELETE FROM ug_index WHERE tab_id = 4")
                }
            }
            database.read { db ->
                assertEquals("ok", db.one("PRAGMA integrity_check") { it.text(0) })
                assertEquals("ok", db.one("PRAGMA foreign_key_check") { "a row" } ?: "ok")
                for (fts in listOf("ug_artists_fts", "ug_index_fts", "ug_keys_fts")) {
                    db.execute("INSERT INTO $fts($fts) VALUES ('integrity-check')")
                }
                assertEquals(listOf("radiohead", "song-dongye"), db.query("SELECT artist_key FROM ug_artists ORDER BY id") { it.text(0) })
                assertEquals(listOf("an", "creep", "dongye", "he", "karma", "macarena", "police", "qiao", "radiohead", "song", "acoustic", "los", "del", "rio").sorted(),
                    db.query("SELECT term FROM ug_key_words ORDER BY term") { it.text(0) })
            }
        }
    }

    @Test fun aBackupIsAWholeCopyMadeUnderANameOfItsOwn() {
        val target = File(tmp.root, "backups/before-sync.sqlite")
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { it.kvSet("kept", "yes") }
            database.backupTo(target)
            // A second copy takes the first one's place.
            database.writeBlocking { it.kvSet("kept", "again") }
            database.backupTo(target)
        }
        assertEquals(listOf("before-sync.sqlite"), target.parentFile.list()!!.toList())
        raw(target).use { copy ->
            assertEquals(Database.SCHEMA_VERSION.toLong(), copy.long("PRAGMA user_version"))
            assertEquals("again", copy.prepare("SELECT value FROM kv WHERE key = 'kept'").use { it.step(); it.getText(0) })
            assertEquals("ok", copy.prepare("PRAGMA integrity_check").use { it.step(); it.getText(0) })
        }
    }

    @Test fun anotherFileAttachesAndDetaches() {
        val other = File(tmp.root, "other.sqlite")
        raw(other).use { c ->
            c.execSQL("CREATE TABLE t (x TEXT)")
            c.execSQL("INSERT INTO t VALUES ('there')")
        }
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.attach(other, "peer")
                assertEquals("there", db.one("SELECT x FROM peer.t") { it.text(0) })
                db.detach("peer")
                assertFailsWith<Exception> { db.one("SELECT x FROM peer.t") { it.text(0) } }
            }
        }
    }

    @Test fun thePhonesTablesAreMadeOnceInOneTransaction() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                assertEquals("1", db.kvGet("phone:schema"))
                PhoneSchema.migrate(db)  // nothing: at its version
                db.kvSet("phone:schema", "${PhoneSchema.VERSION + 1}")
                assertFailsWith<DatabaseTooNew> { PhoneSchema.migrate(db) }
            }
        }
        // A database whose phone tables half exist (one made by hand): PhoneSchema fails whole, nothing written.
        val half = File(tmp.root, "half")
        half.mkdirs()
        migratedTo(Database.SCHEMA_VERSION, File(half, "caracole.sqlite"))
        raw(File(half, "caracole.sqlite")).use { it.execSQL("CREATE TABLE phone_songbooks (key TEXT)") }
        assertFailsWith<Exception> { TestDb.fresh(half) }
        raw(File(half, "caracole.sqlite")).use { c ->
            assertEquals(0L, c.long("SELECT count(*) FROM sqlite_master WHERE name = 'phone_overrides'"))
            assertEquals(0L, c.long("SELECT count(*) FROM kv WHERE key = 'phone:schema'"))
        }
    }

    @Test fun aReaderIsLentToOneBlockAtATime() {
        TestDb.fresh(tmp.root).use { database ->
            val lent = database.read { a -> database.read { b -> a.raw !== b.raw } }
            assertTrue(lent)
        }
    }

}
