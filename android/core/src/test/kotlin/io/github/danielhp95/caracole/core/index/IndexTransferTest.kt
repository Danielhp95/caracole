package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** IndexTransfer's seed, newest and refusals, beside IndexMergeTest's merges (tests/conformance/vectors/index/). */
class IndexTransferTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = "2026-11-03T12:00:00Z"

    private fun export(name: String): File =
        File(tmp.newFolder(), "export.sqlite").also { Fixtures.loadRaw(it, "index/fixtures/$name.jsonl") }

    private fun freshKv(): Map<String, String> {
        val text = javaClass.classLoader.getResourceAsStream("caracole/schema/fresh_kv.json")!!.use {
            it.readBytes().toString(Charsets.UTF_8)
        }
        val kv = Json.parseToJsonElement(text).jsonObject.getValue("kv").jsonObject
        return kv.mapValues { it.value.jsonPrimitive.content }
    }

    @Test fun seedFreshGivesANewPhoneWhatANewPythonDatabaseHolds() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            // Python's fixture was dumped before the phone's tables were made in it: no kv phone:schema.
            val seeded = database.read { Dumps.lines(it) }.filter { !it.startsWith("{\"kv\":\"phone:schema\"") }
            assertEquals(Dumps.fixture("fresh-before"), seeded)
            // A record the phone holds already stays, and seeding again changes nothing.
            database.writeBlocking { it.kvSet("lacuerda:index:keys", "1"); IndexTransfer.seedFresh(it) }
            assertEquals("1", database.read { it.kvGet("lacuerda:index:keys") })
        }
        assertEquals(setOf("ug:artist_tabs:keys", "lacuerda:index:keys", "harptabs:index:keys", "harptabs:artists:keys",
                           "gametabs:games:keys"), freshKv().keys)
    }

    @Test fun aFreshPhoneSeededMergesAnExportAndReKeysNothing() {
        val export = export("full-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val merged = waitingOnLanes { database.writeBlocking { IndexTransfer.merge(it, export, now) } }
            assertTrue(merged.changed)
            val after = database.read { Dumps.lines(it) }
            assertEquals(Dumps.fixture("fresh-after"), after)
            // The keys records as seeded, and every row whose keys no reading of its names gives kept as the export
            // holds it: nothing was keyed again.
            val kv = database.read { db ->
                db.query("SELECT key, value FROM kv") { it.text(0)!! to it.text(1)!! }.toMap()
            }
            for ((key, value) in freshKv()) assertEquals(value, kv[key], key)
            val stale = after.filter { "\"stale-key\"" in it }
                .map { Json.parseToJsonElement(it).jsonObject.getValue("table").jsonPrimitive.content }
            assertEquals(setOf("ug_artist_tabs", "lacuerda_index", "harptabs_index", "harptabs_artist_tabs",
                               "gametabs_game_tabs"), stale.toSet())
        }
    }

    @Test fun theBackupComesOnceBeforeTheFirstChange() {
        val export = export("partial-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/phone-before.jsonl") }
            val seen = ArrayList<Long>()
            database.writeBlocking { db ->
                IndexTransfer.merge(db, export, now) {
                    seen += db.one("SELECT COUNT(*) FROM main.musescore_index") { it.long(0)!! }!!
                }
            }
            assertEquals(listOf(0L), seen) // called once, while the phone had no MuseScore page yet
            database.writeBlocking { db -> IndexTransfer.merge(db, export, now) { seen += -1L } }
            assertEquals(listOf(0L), seen) // nothing to take the second time: no backup
        }
    }

    @Test fun aFileThatIsNoExportOrTheDatabaseItselfIsRefused() {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            val before = database.read { Dumps.lines(it) }
            val text = File(dir, "notes.txt").also { it.writeText("not a database, just words long enough to be read") }
            for (file in listOf(File(dir, "missing.sqlite"), text, File(dir, "caracole.sqlite"), dir)) {
                assertFailsWith<TransferError>(file.name) {
                    database.writeBlocking { IndexTransfer.merge(it, file, now) }
                }
            }
            assertTrue(!File(dir, "missing.sqlite").exists())
            assertEquals(before, database.read { Dumps.lines(it) })
            assertEquals(listOf("main"), database.writeBlocking { db ->
                db.query("PRAGMA database_list") { it.text(1)!! }.filter { it != "temp" }
            })
        }
    }

    @Test fun newestIsWhatIndexTransferNewestSays() {
        val records = Corpus.records("index/newest.jsonl")
        assertTrue(records.size >= 10)
        for (record in records) {
            val fixture = record.extra.getValue("fixture").jsonPrimitive.content
            TestDb.fresh(tmp.newFolder()).use { database ->
                database.writeBlocking { Fixtures.load(it, "index/fixtures/$fixture.jsonl") }
                if (record.err != null) {
                    assertEquals("OverflowError", record.err, fixture)
                    assertFailsWith<ArithmeticException>(fixture) { database.read { IndexTransfer.newest(it) } }
                } else {
                    val expected = record.out!!.jsonObject.mapValues { it.value.jsonPrimitive.content }
                    val newest = database.read { IndexTransfer.newest(it) }
                    assertEquals(expected, newest, fixture)
                    assertEquals(Sites.ALL.map { it.name }.filter { it in newest }, newest.keys.toList(), fixture)
                }
            }
        }
    }

    @Test fun theSitesAreIndexTransfersSites() {
        val records = Corpus.records("index/sites.jsonl")
        assertEquals(records.map { it.args[0].jsonPrimitive.content }, Sites.ALL.map { it.name })
        for ((record, site) in records.zip(Sites.ALL)) {
            val out = record.out!!.jsonObject
            fun strings(key: String) = out.getValue(key).jsonArray.map { it.jsonPrimitive.content }
            assertEquals(out.getValue("title").jsonPrimitive.content, site.title)
            assertEquals(strings("tables"), site.tables)
            assertEquals(strings("kv"), site.kv)
        }
    }

    @Test fun aRecordIsWrittenBackAsJsonDumpsWritesJsonLoadsReading() {
        val text = "{\"a\": 1.50, \"b\": -0, \"c\": 1E2, \"d\": 1e400, \"e\": \"\\u00e9\", \"a\": 2, " +
            "\"f\": [0.1, -0.0, NaN, 10000000000000000.0]}"
        assertEquals("{\"a\": 2, \"b\": 0, \"c\": 100.0, \"d\": Infinity, \"e\": \"\u00e9\", " +
                         "\"f\": [0.1, -0.0, NaN, 1e+16]}",
                     PyJson.dumps(Merge.pyLoaded(Canonical.parse(text))))
        assertEquals(JsonArray(listOf(JsonPrimitive("x"))), Merge.pyLoaded(JsonArray(listOf(JsonPrimitive("x")))))
    }
}
