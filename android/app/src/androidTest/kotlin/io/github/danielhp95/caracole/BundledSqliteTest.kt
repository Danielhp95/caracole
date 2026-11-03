package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * caracole's database on the device: the SQLite the app bundles (androidx.sqlite's, 3.50.1 with FTS5), never the
 * system's, with db.py's schema to the byte (vectors/schema/sqlite_master.json, from the test's assets) and the three
 * FTS5 indexes search reads: the keys' trigrams, the artists' words and their vocabulary. The JVM's DatabaseTest and
 * FtsTest hold the same on the computer; the integration step runs this one on the emulator.
 */
@RunWith(AndroidJUnit4::class)
class BundledSqliteTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var dir: File
    private lateinit var database: Database

    @Before
    fun aFreshDatabase() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        dir = File(instrumentation.targetContext.cacheDir, "bundled-sqlite-test").apply { deleteRecursively(); mkdirs() }
        database = Database(File(dir, "caracole.sqlite"))
        database.writeBlocking { db ->
            db.savepoint("tabs") {
                for ((id, artist, song) in listOf(Triple(10, "radiohead", "karma-police"), Triple(11, "police", "roxanne"),
                    Triple(12, "the-police", "message-in-a-bottle"), Triple(13, "song-dongye", "ban-ma-ban-ma"))) {
                    db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                        "VALUES (?, ?, ?, 'Chords', 'tabs1.xml', 'x', ?)", id, artist, song, "tab/$artist/$song-chords-$id")
                }
            }
        }
    }

    @After
    fun closed() {
        database.close()
        dir.deleteRecursively()
    }

    @Test
    fun itIsTheBundledSqliteWithFts5() = database.read { db ->
        assertEquals(Database.SQLITE_SOURCE_ID, db.one("SELECT sqlite_source_id()") { it.text(0) })
        val options = db.query("PRAGMA compile_options") { it.text(0)!! }
        assertTrue("compile options: $options", "ENABLE_FTS5" in options)
        assertTrue("compile options: $options", "THREADSAFE=2" in options)
    }

    @Test
    fun theMigrationsMakePythonsSchema() = database.read { db ->
        assertEquals(Database.SCHEMA_VERSION.toLong(), db.one("PRAGMA user_version") { it.long(0) })
        assertEquals("1", db.kvGet("phone:schema"))
        val want = Corpus.json("schema/sqlite_master.json").getValue("objects").jsonArray.map { o ->
            listOf("type", "name", "tbl_name", "sql").map { o.jsonObject.getValue(it).jsonPrimitive.contentOrNull }
        }
        val got = db.query("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name") { r ->
            listOf(r.text(0), r.text(1), r.text(2), r.text(3))
        }.filterNot { it[2]!!.startsWith("phone_") }
        assertEquals(want, got)
        assertEquals("ok", db.one("PRAGMA integrity_check") { it.text(0) })
        for (fts in listOf("ug_artists_fts", "ug_index_fts", "ug_keys_fts")) {
            db.execute("INSERT INTO $fts($fts) VALUES ('integrity-check')")
        }
    }

    @Test
    fun aTrigramLikeGoesThroughTheKeysIndex() = database.read { db ->
        val sql = "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?) ORDER BY key"
        val plan = db.query("EXPLAIN QUERY PLAN $sql", "%police%") { it.text("detail")!! }
        assertTrue("the plan: $plan", plan.any { "VIRTUAL TABLE INDEX" in it && "ug_keys_fts" in it })
        assertEquals(listOf("karma-police", "police", "the-police"), db.query(sql, "%police%") { it.text(0) })
    }

    @Test
    fun anArtistIsFoundByAWordAndTheWordsAreCounted() = database.read { db ->
        val sql = "SELECT artist_key FROM ug_artists WHERE id IN " +
            "(SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) ORDER BY artist_key"
        assertEquals(listOf("police", "the-police"), db.query(sql, "\"police\"") { it.text(0) })
        assertEquals(listOf("song-dongye"), db.query(sql, "\"song\" AND \"dongye\"") { it.text(0) })
        assertEquals(listOf("dongye" to 1L, "police" to 2L, "radiohead" to 1L, "song" to 1L, "the" to 1L),
            db.query("SELECT term, doc FROM ug_artist_words ORDER BY term") { it.text(0) to it.long(1) })
    }
}
