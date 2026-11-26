package io.github.danielhp95.caracole.core.index

import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.testing.Dumps
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.IndexReplay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** IndexTransfer's seed, newest and refusals, beside IndexMergeTest's merges (tests/conformance/vectors/index/; the
 * records' loops are IndexReplay's, which the device runs too). */
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
        Misses("fresh-before").also { IndexReplay.seedFresh(it) }.assertNone()
        TestDb.fresh(tmp.newFolder()).use { database ->
            // A record the phone holds already stays, and seeding again changes nothing.
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            database.writeBlocking { it.kvSet("lacuerda:index:keys", "1"); IndexTransfer.seedFresh(it) }
            assertEquals("1", database.read { it.kvGet("lacuerda:index:keys") })
        }
        assertEquals(setOf("ug:artist_tabs:keys", "ug:directory:keys", "lacuerda:index:keys", "harptabs:index:keys",
                           "harptabs:artists:keys", "gametabs:games:keys"), freshKv().keys)
    }

    @Test fun aFreshPhoneSeededMergesAnExportAndReKeysNothing() {
        val export = export("full-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now) }
            assertTrue(merged.changed)
            val after = database.read { Dumps.lines(it) }
            Misses("fresh-after").also { IndexReplay.freshMerge(it) }.assertNone()
            // The keys records as seeded, and every row whose keys no reading of its names gives kept as the export
            // holds it: nothing was keyed again.
            val kv = database.read { db ->
                db.query("SELECT key, value FROM kv") { it.text(0)!! to it.text(1)!! }.toMap()
            }
            for ((key, value) in freshKv()) assertEquals(value, kv[key], key)
            val stale = after.filter { "\"stale-key\"" in it }
                .map { Json.parseToJsonElement(it).jsonObject.getValue("table").jsonPrimitive.content }
            assertEquals(setOf("ug_artist_tabs", "ug_directory", "lacuerda_index", "harptabs_index",
                               "harptabs_artist_tabs", "gametabs_game_tabs"), stale.toSet())
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

    @Test fun aMergeInsideTheCallersTransactionIsTheCallersMistakeNotTheFiles() {
        val export = export("partial-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/phone-before.jsonl") }
            val before = database.read { Dumps.lines(it) }
            assertFailsWith<IllegalStateException> {
                database.writeBlocking { db -> db.savepoint("callers") { IndexTransfer.merge(db, export, now) } }
            }
            assertFailsWith<IllegalStateException> {
                database.writeBlocking { db ->
                    db.attach(export, "theirs")
                    try {
                        IndexTransfer.merge(db, export, now)
                    } finally {
                        db.detach("theirs")
                    }
                }
            }
            assertEquals(before, database.read { Dumps.lines(it) })
        }
    }

    @Test fun newestIsWhatIndexTransferNewestSays() = Misses(IndexReplay.NEWEST).also { IndexReplay.newest(it) }.assertNone()

    @Test fun theHaveDocumentIsPythons() = Misses(IndexReplay.HAVE).also { IndexReplay.have(it) }.assertNone()

    /** route.jsonl: the route the phone asks its part over is the one caracole serve answers (method, path, its
     * token's header, JSON), and the statuses after which it asks for the whole are those the record names, no
     * other (a route that answered 404 by mistake falls back; one that answers 400 must show). */
    @Test fun theNewerRouteIsTheOneTheRecordStates() {
        val out = io.github.danielhp95.caracole.core.testing.Corpus.records("index/route.jsonl").single().out!!
            .jsonObject
        fun text(key: String) = out.getValue(key).jsonPrimitive.content
        assertEquals("POST" to "json", text("method") to text("body"))
        assertEquals(text("path"), io.github.danielhp95.caracole.core.sync.PeerClient.INDEX_NEWER_PATH)
        assertEquals(text("token_header"), io.github.danielhp95.caracole.core.sync.PeerClient.TOKEN_HEADER)
        assertEquals(out.getValue("whole_instead").jsonArray.map { it.jsonPrimitive.int }.toSet(),
                     io.github.danielhp95.caracole.core.sync.PeerClient.WHOLE_INSTEAD)
        assertEquals(text("limit").toLong(), 1024L * 1024)
    }

    @Test fun theSitesAreIndexTransfersSites() = Misses(IndexReplay.SITES).also { IndexReplay.sites(it) }.assertNone()

    @Test fun aRecordIsWrittenBackAsJsonDumpsWritesJsonLoadsReading() {
        val text = "{\"a\": 1.50, \"b\": -0, \"c\": 1E2, \"d\": 1e400, \"e\": \"\\u00e9\", \"a\": 2, " +
            "\"f\": [0.1, -0.0, NaN, 10000000000000000.0]}"
        assertEquals("{\"a\": 2, \"b\": 0, \"c\": 100.0, \"d\": Infinity, \"e\": \"\u00e9\", " +
                         "\"f\": [0.1, -0.0, NaN, 1e+16]}",
                     PyJson.dumps(Merge.pyLoaded(Canonical.parse(text))))
        assertEquals(JsonArray(listOf(JsonPrimitive("x"))), Merge.pyLoaded(JsonArray(listOf(JsonPrimitive("x")))))
    }

    /** The phone's clock bound (merge's `notAfter`, a sync's): of UG's artist directory, a row the file says it saw
     * later is left, a new row it says it read later comes as never read, and a listing's round it says it began or
     * ended later is left; a merge with no bound (Python's) takes them all after. */
    @Test fun aDirectoryTheFileDatesInTheFutureIsNeverNewerThanTheClock() {
        val export = export("full-export")
        val c = BundledSQLiteDriver().open(export.path)
        try {
            c.execSQL("UPDATE ug_directory SET seen_at = '2999-01-01T00:00:00Z' WHERE artist_id = 274")
            c.execSQL("UPDATE ug_directory SET read_at = '2999-01-01T00:00:00Z' WHERE artist_id = 13472")
            c.execSQL("UPDATE kv SET value = replace(value, '2026-10-28T03:30:00Z', '2999-01-01T00:00:00Z') " +
                          "WHERE key = 'ug:directory:letters'")
        } finally {
            c.close()
        }
        fun rows(db: Db) =
            db.query("SELECT artist_id, read_at, read_tabs FROM ug_directory ORDER BY artist_id") {
                Triple(it.long(0)!!, it.text(1)!!, it.long(2)!!)
            }
        fun letters(db: Db) =
            Canonical.parse(db.kvGet("ug:directory:letters")!!).jsonObject.keys
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val bound = Stamps.parse(now)!!
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, listOf("ug"), notAfter = bound) }
            assertEquals(3, merged.sites.getValue("ug")["artist of its directory"])
            database.read { db ->
                assertEquals(listOf(Triple(90L, "", 0L), Triple(13472L, "", 0L), Triple(634073L, "", 0L)), rows(db))
                assertEquals(setOf("0-9", "t"), letters(db))
            }
            database.writeBlocking { IndexTransfer.merge(it, export, now, listOf("ug")) }
            database.read { db ->
                assertEquals(listOf(Triple(90L, "", 0L), Triple(274L, "", 0L), Triple(13472L, "2999-01-01T00:00:00Z", 411L),
                                    Triple(634073L, "", 0L)), rows(db))
                assertEquals(setOf("0-9", "s", "t"), letters(db))
            }
        }
    }

    /** What a merge says it read (Merged.newest): each site's newest read in the file, as `newest` reads a database,
     * never the database's after it, which the phone's own reads move; of the sites merged alone. */
    @Test fun aMergeSaysEachSitesNewestReadInTheFileNeverTheDatabases() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            // A whole export into a new phone: the file's newest is what the phone's database says after it.
            val merged = database.writeBlocking { IndexTransfer.merge(it, export("full-export"), now) }
            assertEquals(database.read { IndexTransfer.newest(it) }, merged.newest)
            assertEquals(IndexTransfer.SITES.toSet(), merged.newest.keys, "every site the file holds a read of")
        }
        TestDb.fresh(tmp.newFolder()).use { database ->
            // The phone's own read of gtptabs.com since (a progress record of its own, later than the file's).
            database.writeBlocking { it.kvSet("gtptabs:index:complete_at", "2026-11-02T09:00:00Z") }
            val gtptabs = listOf("gtptabs")
            val merged = database.writeBlocking { IndexTransfer.merge(it, export("partial-export"), now, gtptabs) }
            assertEquals(mapOf("gtptabs" to "2026-10-28T03:30:00Z"), merged.newest, "the file's, of the site merged")
            assertEquals("2026-11-02T09:00:00Z", database.read { IndexTransfer.newest(it) }["gtptabs"])
            // A merge of nothing newer says the file's all the same.
            val again = database.writeBlocking { IndexTransfer.merge(it, export("partial-export"), now, gtptabs) }
            assertEquals(false, again.changed)
            assertEquals(mapOf("gtptabs" to "2026-10-28T03:30:00Z"), again.newest)
            val both = database.writeBlocking { IndexTransfer.merge(it, export("partial-export"), now) }
            assertEquals(mapOf("gtptabs" to "2026-10-28T03:30:00Z", "musescore" to "2026-10-28T03:30:00Z"), both.newest)
        }
    }

    /** A site the file says it read after the clock's bound (`notAfter`) is left out of what it says it read: its
     * records that late were never taken. */
    @Test fun aSiteTheFileDatesAfterTheBoundIsNoReadItSaysItTook() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            val bound = Stamps.parse("2026-10-27T00:00:00Z")!!
            val merged = database.writeBlocking {
                IndexTransfer.merge(it, export("partial-export"), now, notAfter = bound)
            }
            assertEquals(emptyMap(), merged.newest)
            val at = Stamps.parse("2026-10-28T03:30:00Z")!!
            val later = database.writeBlocking { IndexTransfer.merge(it, export("partial-export"), now, notAfter = at) }
            assertEquals(mapOf("gtptabs" to "2026-10-28T03:30:00Z", "musescore" to "2026-10-28T03:30:00Z"),
                         later.newest, "a read at the bound itself is no later than it")
        }
    }

    /** kv `index:merged` (MergedIndexes): each site's latest newest read of the whole exports merged, never moved back
     * by an older file, a site it never merged left as it was; its odd entries none. */
    @Test fun theRecordOfTheExportsMergedKeepsEachSitesLatest() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            assertEquals(emptyMap(), database.read { MergedIndexes.of(it) })
            fun record(vararg sites: Pair<String, String>) = database.writeBlocking {
                MergedIndexes.record(it, Merged(emptyMap(), false, newest = mapOf(*sites)))
            }
            record("ug" to "2026-11-17T03:30:00Z", "gtptabs" to "2026-11-10T03:30:00Z")
            record("ug" to "2026-11-10T03:30:00Z", "lacuerda" to "2026-11-01T00:00:00+01:00")
            assertEquals(mapOf("gtptabs" to "2026-11-10T03:30:00Z", "lacuerda" to "2026-11-01T00:00:00+01:00",
                               "ug" to "2026-11-17T03:30:00Z"), database.read { MergedIndexes.of(it) })
            assertEquals("""{"gtptabs": "2026-11-10T03:30:00Z", "lacuerda": "2026-11-01T00:00:00+01:00", """ +
                             """"ug": "2026-11-17T03:30:00Z"}""", database.read { it.kvGet(MergedIndexes.KEY) },
                         "its sites in code-point order, as kv text")
            database.writeBlocking { it.kvSet(MergedIndexes.KEY, """{"ug": "not a time", "lacuerda": 3}""") }
            assertEquals(mapOf("ug" to "not a time"), database.read { MergedIndexes.of(it) })
            record("ug" to "2026-11-10T03:30:00Z")
            assertEquals(mapOf("ug" to "2026-11-10T03:30:00Z"), database.read { MergedIndexes.of(it) },
                         "a stamp that is no time gives way")
        }
    }

    /** A sitemap the computer re-checked and found unchanged (its record's `checked_at` alone moved: a 304) moves the
     * phone's record on and writes no row of it, and is no site taken: no action told, none in a sync's report; a
     * second merge writes nothing (index_transfer._sitemaps alike, its merge.jsonl's `rechecked` record). */
    @Test fun aSitemapFoundUnchangedMovesItsRecordAloneAndIsNoSiteTaken() {
        val export = export("rechecked-export")
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/phone-after.jsonl") }
            val rows = { database.read { db -> db.query("SELECT * FROM musescore_index ORDER BY path") { it.text(0) } } }
            val before = rows()
            val said = ArrayList<MergeProgress>()
            val (merged, written) = database.writeBlocking { db ->
                val changes = db.one("SELECT total_changes()") { it.long(0)!! }!!
                val merged = IndexTransfer.merge(db, export, now, listOf("musescore"), progress = { said += it })
                merged to db.one("SELECT total_changes()") { it.long(0)!! }!! - changes
            }
            assertTrue(merged.changed)
            assertEquals(mapOf("musescore" to emptyMap()), merged.sites)
            assertEquals(1L, written, "its record alone")
            assertEquals(before, rows())
            val theirs = BundledSQLiteDriver().open(export.path).let { c ->
                try {
                    c.prepare("SELECT value FROM kv WHERE key = 'musescore:sitemaps'").use { it.step(); it.getText(0) }
                } finally {
                    c.close()
                }
            }
            assertTrue(PyJson.equal(Canonical.parse(theirs),
                                    Canonical.parse(database.read { it.kvGet("musescore:sitemaps") }!!)))
            assertTrue(said.none { it.site == "musescore" && it.action == "sitemap" })
            val counts = mapOf("musescore" to 1L)
            assertEquals(emptyList(), SyncEngine.taken(merged, counts, counts, listOf("musescore")) { null })
            val again = database.writeBlocking { IndexTransfer.merge(it, export, now, listOf("musescore")) }
            assertTrue(!again.changed, "a second merge writes nothing")
        }
    }
}
