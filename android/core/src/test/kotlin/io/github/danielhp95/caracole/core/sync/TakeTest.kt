package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.internal.take.Backups
import io.github.danielhp95.caracole.core.sync.internal.take.Folders
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.util.Base64
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A UnitSource of documents and files held in memory: a take.jsonl record's `source`, or a fixture's documents and
 * kept files, as the phone's tests read them (the corpus's InlineSource). A file it doesn't hold is a UnitError in
 * Python's words.
 */
internal class InlineSource(private val units: Map<String, JsonObject?>, private val files: List<Kept>) : UnitSource {
    data class Kept(val song: String, val name: String, val sha256: String, val bytes: ByteArray)

    val asked = mutableListOf<String>()

    override fun unit(id: String): JsonObject? = units[id].also { asked += id }

    override fun file(songKey: String, name: String, sha256: String): ByteArray =
        files.firstOrNull { it.song == songKey && it.name == name && it.sha256 == sha256 }?.bytes
            ?: throw UnitError("$name: there, no such file is kept")

    companion object {
        /** A take.jsonl record's `source`: `{units: {id: document or null}, files: [{song, name, sha256, base64}]}`. */
        fun of(source: JsonObject): InlineSource = InlineSource(
            source.getValue("units").jsonObject.mapValues { it.value as? JsonObject },
            source.getValue("files").jsonArray.map { it.jsonObject }.map {
                Kept(it.getValue("song").jsonPrimitive.content, it.getValue("name").jsonPrimitive.content,
                     it.getValue("sha256").jsonPrimitive.content,
                     Base64.getDecoder().decode(it.getValue("base64").jsonPrimitive.content))
            },
        )
    }
}

/**
 * Take against Python's peer_sync.apply_units: every case of vectors/sync/take.jsonl (§5.6's rules, the
 * compare-and-swap, a unit left whole), every fixture of vectors/sync taken into an empty phone, checked_name; and
 * the backup before a sync, which restore puts back.
 */
class TakeTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = mutableListOf<Database>()

    @After fun close() = opened.forEach { it.close() }

    private class Phone(val database: Database, val library: File, val state: File) {
        val store = LibraryStore(library)
        fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)
    }

    private fun phone(fixture: String? = null): Phone {
        val dir = tmp.newFolder()
        val phone = Phone(TestDb.fresh(dir).also { opened += it }, File(dir, "library"), File(dir, "state"))
        if (fixture != null) phone.write { Fixtures.load(it, fixture, phone.library) }
        return phone
    }

    private fun text(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content

    // --- checked_name ---------------------------------------------------------------------------------------------

    @Test fun aKeptFilesNameIsOneASongsFolderCanHold() {
        val records = Corpus.records("sync/checked_name.jsonl")
        assertTrue(records.size >= 15)
        for (r in records) {
            val name = r.args[0]
            if (name !is JsonPrimitive || !name.isString) {
                assertEquals("UnitError", r.err, "a name that isn't text is no name: $name") // the take's nameOf
                continue
            }
            if (r.err != null) {
                assertEquals("UnitError", r.err)
                assertFailsWith<UnitError>(name.content) { Take.checkedName(name.content) }
            } else {
                assertEquals(text(r.out), Take.checkedName(name.content))
            }
        }
        assertEquals("a kept file named '../sheet.txt', which no song's folder holds",
                     assertFailsWith<UnitError> { Take.checkedName("../sheet.txt") }.message)
    }

    // --- apply_units ----------------------------------------------------------------------------------------------

    @Test fun eachTakeDoesWhatPythonsDoes() {
        val records = Corpus.records("sync/take.jsonl")
        assertTrue(records.size >= 15)
        for (r in records) {
            val case = text(r.extra["case"])!!
            val phone = phone("sync/fixtures/${text(r.extra["fixture"])}.jsonl")
            val source = InlineSource.of(r.extra.getValue("source").jsonObject)
            val wanted = r.args[0].jsonArray.map { w -> w.jsonArray.let { text(it[0])!! to text(it[1]) } }
            val expected = r.kw.getValue("expected_here").jsonObject.mapValues { text(it.value) }
            val told = mutableListOf<Pair<String, String>>()
            val done = phone.write { db ->
                Take.applyUnits(db, phone.store, source, wanted, expected, text(r.kw["now"])!!) { id, what -> told += id to what }
            }
            val out = r.out!!.jsonObject
            fun strings(name: String) = out.getValue(name).jsonArray.map { it.jsonPrimitive.content }
            assertEquals(strings("taken"), done.taken, case)
            val left = out.getValue("left").jsonArray.map { it.jsonArray.let { p -> text(p[0])!! to text(p[1])!! } }
            assertEquals(left.map { it.first }, done.left.map { it.first }, case)
            for ((want, got) in left.zip(done.left)) {
                if (want.second.startsWith("changed ") || want.second.startsWith("a kept file named") ||
                    want.second.endsWith("no such file is kept") || want.second.contains(" came other than it is there")) {
                    assertEquals(want.second, got.second, case) // the compare-and-swap's and the take's own words
                } else {
                    assertTrue(got.second.isNotEmpty(), "$case: ${got.first} left saying why")
                }
            }
            assertEquals(wanted.size, told.size, case) // each unit told once, as it is done
            assertEquals((done.taken.map { it to "taken" } + done.left.map { it.first to "left" }).toMap(), told.toMap(), case)
            assertEquals(strings("respelled"), done.respelled, case)
            assertEquals(out["songbooks"]?.jsonPrimitive?.content?.toBoolean(), done.songbooksChanged, case)
            assertEquals(out.getValue("songs").jsonArray.map { it.jsonPrimitive.content.toLong() }, done.songs, case)
            phone.write { db ->
                assertEquals(Canonical.write(out.getValue("after")), Canonical.write(after(db)), case)
                // What a song's value leaves out: its record's other columns, its versions' (rating, votes, coverage,
                // fetched_at), its files' kept_rank, the carried kv under the phone's own id.
                val documents = out.getValue("documents").jsonObject
                assertEquals(documents.keys, after(db).keys.filter { it.startsWith("song/") }.toSet(), case)
                for ((id, want) in documents) {
                    assertEquals(Canonical.write(want), Canonical.write(Units.document(db, phone.library, id) ?: JsonNull),
                                 "$case: $id's document")
                }
                assertEquals(out.getValue("ids").jsonObject.mapValues { it.value.jsonPrimitive.content.toLong() },
                             db.query("SELECT id, key FROM songs ORDER BY id") { it.text(1)!! to it.long(0) }.toMap(), case)
                // The render records of a folder moved go; the carried kv is the phone's id's.
                assertEquals(out.getValue("kv").jsonArray.map { kv -> kv.jsonArray.map { it.jsonPrimitive.content } },
                             db.query("SELECT key, value FROM kv WHERE substr(key, 1, 7) = 'render:' " +
                                      "OR substr(key, 1, 15) = 'sheet_versions:' ORDER BY key") {
                                 listOf(it.text(0)!!, it.text(1)!!)
                             }, case)
                assertEquals(strings("paths"), db.query("SELECT path FROM files ORDER BY path") { it.text(0)!! }, case)
            }
            assertEquals(out.getValue("files").jsonArray.map { f -> f.jsonArray.map { it.jsonPrimitive.content } },
                         filesOf(phone.library), case)
        }
    }

    @Test fun unitsAreTakenSongsFirstEachLeftAloneWhenItCantBe() {
        val phone = phone()
        phone.write { db ->
            db.kvSet("songs:key_version", Normalize.KEY_VERSION.toString()) // as fresh_kv.json seeds a new database
            db.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES " +
                       "('oasis/wonderwall', 'Oasis', 'Wonderwall', '{}', '2026-10-01T00:00:00Z')")
        }
        val source = object : UnitSource {
            override fun unit(id: String): JsonObject? =
                if (id == "removed/broken/one") throw java.io.IOException("the computer went away") else null
            override fun file(songKey: String, name: String, sha256: String): ByteArray = error("no file is asked for")
        }
        val told = mutableListOf<Pair<String, String>>()
        val wanted = listOf("nonsense/x" to null, "removed/oasis/wonderwall" to null, "removed/broken/one" to null,
                            "removed/b/c" to "a digest the source had", "song/nobody/here" to null)
        val done = phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, emptyMap(), NOW) { id, what -> told += id to what } }
        assertEquals(listOf("song/nobody/here", "removed/oasis/wonderwall"), done.taken)
        assertEquals(listOf("removed/b/c" to Take.CHANGED_THERE, "removed/broken/one" to "the computer went away",
                            "nonsense/x" to "this caracole doesn't know units of kind 'nonsense'"), done.left)
        assertEquals(listOf("song/nobody/here" to "taken", "removed/b/c" to "left", "removed/broken/one" to "left",
                            "removed/oasis/wonderwall" to "taken", "nonsense/x" to "left"), told)
        assertEquals(Applied(done.taken, done.left, emptyList(), emptyList(), false), done)
        phone.write { db -> assertEquals(emptyList(), Songs.removed(db), "the tombstone the peer has no longer goes") }
    }

    /** A source of [units]' documents alone, each wanted with the digest of its value. */
    private fun documents(vararg units: Pair<String, JsonObject?>): Pair<InlineSource, List<Pair<String, String?>>> =
        InlineSource(units.toMap(), emptyList()) to units.map { (id, doc) ->
            id to doc?.let { Canonical.digest(Units.valueOfDocument(id, it)!!) }
        }

    private fun json(text: String): JsonObject = Canonical.parse(text) as JsonObject

    @Test fun aLibraryThatCantBeReadLeavesEveryUnitTheComparisonNamedSayingWhy() {
        val phone = phone()
        phone.write { db ->
            db.kvSet("songs:key_version", Normalize.KEY_VERSION.toString())
            db.execute("INSERT INTO phone_songbooks (key, name, songs, position) VALUES ('bad', 'Bad', '{}', 0)")
        }
        val (source, wanted) = documents("alias/soda" to json("""{"slugs": ["soda-stereo"]}"""),
                                         "block/4242" to json("""{"tab": 4242}"""))
        // As _digests_here: the units the comparison named are left, the others are taken all the same.
        val done = phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, mapOf("alias/soda" to null), NOW) }
        assertEquals(listOf("alias/soda" to "this library can't be read: the songbook Bad's songs aren't a list"), done.left)
        assertEquals(listOf("block/4242"), done.taken)
    }

    @Test fun theDatabasesOwnFailureStopsTheTakeWhereAUnitsRefusalLeavesThatUnit() {
        val phone = phone()
        phone.write { db ->
            db.kvSet("songs:key_version", Normalize.KEY_VERSION.toString())
            db.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES " +
                       "('oasis/wonderwall', 'Oasis', 'Wonderwall', '{}', '2026-10-01T00:00:00Z')")
            db.execute("DROP TABLE phone_overrides") // every overrides entry's write now fails as SQLite's own error
        }
        val (source, wanted) = documents("alias/soda" to json("""{"slugs": ["soda-stereo"]}"""),
                                         "block/4242" to json("""{"tab": 4242}"""), "removed/oasis/wonderwall" to null)
        val told = mutableListOf<String>()
        val failed = assertFailsWith<androidx.sqlite.SQLiteException> {
            phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, emptyMap(), NOW) { id, _ -> told += id } }
        }
        assertTrue("no such table: phone_overrides" in failed.message!!, failed.message)
        assertTrue(Take.databaseFailed(failed))
        assertEquals(listOf("removed/oasis/wonderwall"), told, "the units before it taken, none tried after it")
        phone.write { db -> assertEquals(emptyList(), Songs.removed(db), "and the unit taken stays taken") }
        // A constraint's refusal (sqlite3's IntegrityError) is the unit's own: take.jsonl's whole_or_nothing leaves it.
        val check = assertFailsWith<androidx.sqlite.SQLiteException> {
            phone.write { db -> db.execute("INSERT INTO versions (song_id, provider, tab_id, slot) VALUES (1, 'ug', '1', 'x')") }
        }
        assertTrue(!Take.databaseFailed(check), check.message)
    }

    @Test fun aSongbooksSettingIsCheckedAsCheckSettingChecksIt() {
        // Python's answers: songbook.check_setting(**parts), its SongbookError's words after "a setting: ".
        val problems = listOf(
            """{"key": "H"}""" to """key must be a tonic such as "G", "F#" or "Bb", got 'H'""",
            """{"key": "g"}""" to """key must be a tonic such as "G", "F#" or "Bb", got 'g'""",
            """{"key": 1}""" to """key must be a tonic such as "G", "F#" or "Bb", got 1""",
            """{"key": ["G"]}""" to """key must be a tonic such as "G", "F#" or "Bb", got ['G']""",
            """{"key": {"a": 1}}""" to """key must be a tonic such as "G", "F#" or "Bb", got {'a': 1}""",
            """{"mode": "major"}""" to "mode must be one of ionian, dorian, phrygian, lydian, mixolydian, aeolian, locrian, got 'major'",
            """{"capo": 12}""" to "capo must be a fret from 0 to 11, got 12",
            """{"capo": -1}""" to "capo must be a fret from 0 to 11, got -1",
            """{"capo": true}""" to "capo must be a fret from 0 to 11, got True",
            """{"capo": 2.0}""" to "capo must be a fret from 0 to 11, got 2.0",
            """{"capo": "2"}""" to "capo must be a fret from 0 to 11, got '2'",
            """{"key": "Bb", "capo": 12}""" to "capo must be a fret from 0 to 11, got 12",
            """{"instrument": "banjo"}""" to "instrument must be one of guitar, ukulele, ukulele-low-g, baritone, piano, harmonica, flute, recorder, got 'banjo'",
        )
        for ((parts, problem) in problems) assertEquals(problem, Take.settingProblem(json(parts)), parts)
        for (parts in listOf("""{"key": "G#"}""", """{"mode": "dorian"}""", """{"instrument": "ukulele-low-g"}""",
                             """{"capo": -0}""", """{"capo": 11, "key": null}""", "{}")) {
            assertNull(Take.settingProblem(json(parts)), parts)
        }
        val phone = phone()
        phone.write { db -> db.kvSet("songs:key_version", Normalize.KEY_VERSION.toString()) }
        val (source, wanted) = documents(
            "songbook/campfire" to json("""{"name": "Campfire", "songs": [["Radiohead - Creep", {"capo": 12}]]}"""),
            "songbook/road" to json("""{"name": "Road", "songs": [["Radiohead - Creep", {"tempo": 90}]]}"""),
            "songbook/home" to json("""{"name": "Home", "songs": [["Radiohead - Creep", {"capo": 2, "key": "G", "mode": null}]]}"""),
        )
        val done = phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, emptyMap(), NOW) }
        assertEquals(listOf("songbook/home"), done.taken)
        assertEquals(listOf("songbook/campfire" to "a setting: capo must be a fret from 0 to 11, got 12",
                            "songbook/road" to "its document can't be read (TypeError: check_setting() got an unexpected " +
                                "keyword argument 'tempo')"), done.left)
        phone.write { db -> assertEquals(listOf("Home"), io.github.danielhp95.caracole.core.library.SongbookStore.all(db).map { it.name }) }
    }

    /** This side's units, as take.jsonl's `after` writes them: `{id: {label, digest, value}}`. */
    private fun after(db: Db): JsonObject = JsonObject(Units.libraryState(db).values.associate { unit ->
        unit.id to JsonObject(mapOf("label" to JsonPrimitive(unit.label), "digest" to JsonPrimitive(unit.digest),
                                    "value" to (Units.value(db, unit.id) ?: JsonNull)))
    })

    /** Every file of the library's song folders (not the library's own top files), [path, sha256], by path as
     * Python sorts its paths (part by part). */
    private fun filesOf(library: File): List<List<String>> {
        if (!library.isDirectory) return emptyList()
        return library.walkTopDown().filter { it.isFile && it.parentFile != library }
            .map { it.relativeTo(library).invariantSeparatorsPath }
            .sortedWith { a, b -> compareParts(a.split('/'), b.split('/')) }
            .map { listOf(it, Canonical.sha256Hex(File(library, it).readBytes())) }
            .toList()
    }

    private fun compareParts(a: List<String>, b: List<String>): Int {
        for (i in 0 until minOf(a.size, b.size)) {
            val c = Canonical.KEY_ORDER.compare(a[i], b[i])
            if (c != 0) return c
        }
        return a.size - b.size
    }

    @Test fun everyFixtureTakenIntoAnEmptyPhoneIsItsValuesAndDigests() {
        val values = Corpus.records("sync/values.jsonl")
        val documents = Corpus.records("sync/documents.jsonl").filter { it.fn.endsWith(".unit_document") }
        for (fixture in listOf("rich", "dense", "plain", "empty")) {
            val units = documents.filter { text(it.extra["fixture"]) == fixture && it.out is JsonObject }
                .associate { text(it.args[0])!! to it.out!!.jsonObject.getValue("unit").jsonObject }
            val want = values.filter { text(it.extra["fixture"]) == fixture }.map { it.out!!.jsonObject }
            val source = InlineSource(units, keptFiles("sync/fixtures/$fixture.jsonl"))
            val phone = phone()
            val done = phone.write { db ->
                Take.applyUnits(db, phone.store, source, want.map { text(it["id"])!! to text(it["digest"]) },
                                want.associate { text(it["id"])!! to null }, NOW)
            }
            assertEquals(emptyList(), done.left, fixture)
            assertEquals(want.map { text(it["id"]) }.toSet(), done.taken.toSet(), fixture)
            phone.write { db ->
                val state = Units.libraryState(db)
                assertEquals(want.map { text(it["id"]) }.toSet(), state.keys, fixture)
                for (unit in want) {
                    val id = text(unit["id"])!!
                    assertEquals(text(unit["label"]), state.getValue(id).label, "$fixture $id")
                    assertEquals(text(unit["digest"]), state.getValue(id).digest, "$fixture $id")
                    assertEquals(Canonical.write(unit.getValue("value")), Canonical.write(Units.value(db, id)!!), "$fixture $id")
                    // And all a document holds beyond the value: the phone's document is the computer's.
                    assertEquals(Canonical.write(units.getValue(id)), Canonical.write(Units.document(db, phone.library, id)!!),
                                 "$fixture $id's document")
                }
            }
        }
    }

    /** A fixture's kept files, by song key, name and SHA-256, with their bytes. */
    private fun keptFiles(fixture: String): List<InlineSource.Kept> {
        val lines = Corpus.lines(fixture).filter { it["header"] != JsonPrimitive(true) }
        val keys = lines.filter { text(it["table"]) == "songs" }.map { it.getValue("row").jsonObject }
            .associate { text(it["id"]) to text(it["key"])!! }
        val bytes = lines.filter { "file" in it }.associate { text(it["file"]) to Base64.getDecoder().decode(text(it["base64"])) }
        return lines.filter { text(it["table"]) == "files" }.map { it.getValue("row").jsonObject }.mapNotNull { f ->
            bytes[text(f["path"])]?.let { InlineSource.Kept(keys.getValue(text(f["song_id"])), text(f["name"])!!, text(f["sha256"])!!, it) }
        }
    }

    @Test fun aUnitChangedOnEitherSideSinceTheComparisonIsLeftAsItIs() {
        val record = Corpus.records("sync/take.jsonl").first { text(it.extra["case"]) == "names_as_written" }
        val source = InlineSource.of(record.extra.getValue("source").jsonObject)
        val wanted = record.args[0].jsonArray.map { w -> w.jsonArray.let { text(it[0])!! to text(it[1]) } }
        val expected = record.kw.getValue("expected_here").jsonObject.mapValues { text(it.value) }
        for ((there, here, why) in listOf(Triple("stale", expected, Take.CHANGED_THERE),
                                          Triple(null, expected.mapValues { "stale" }, Take.CHANGED_HERE))) {
            val phone = phone("sync/fixtures/take_names_as_written.jsonl")
            val before = phone.write { db -> Units.libraryState(db) }
            val done = phone.write { db ->
                Take.applyUnits(db, phone.store, source, wanted.map { it.first to (there ?: it.second) }, here, NOW)
            }
            assertEquals(listOf("song/radiohead/creep" to why), done.left)
            assertEquals(emptyList(), done.taken)
            assertEquals(before, phone.write { db -> Units.libraryState(db) })
        }
    }

    @Test fun aFileTheSourceCantGiveChangesNothingOfThatSong() {
        val record = Corpus.records("sync/take.jsonl").first { text(it.extra["case"]) == "new_here" }
        val full = InlineSource.of(record.extra.getValue("source").jsonObject)
        val units = record.extra.getValue("source").jsonObject.getValue("units").jsonObject.mapValues { it.value as? JsonObject }
        val wanted = record.args[0].jsonArray.map { w -> w.jsonArray.let { text(it[0])!! to text(it[1]) } }
        val phone = phone("sync/fixtures/take_new_here.jsonl")
        val source = object : UnitSource {
            override fun unit(id: String) = units[id]
            override fun file(songKey: String, name: String, sha256: String): ByteArray =
                if (name == "tab.txt") throw java.io.IOException("the network went") else full.file(songKey, name, sha256)
        }
        val done = phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, mapOf(), NOW) }
        assertEquals(listOf("song/radiohead/creep" to "the network went"), done.left)
        phone.write { db -> assertNull(Songs.byKey(db, "radiohead/creep")) }
        assertEquals(emptyList(), filesOf(phone.library))
    }

    // --- the backup before a sync ---------------------------------------------------------------------------------

    /** Every row of the library's tables, each table's rows sorted, as SQLite quotes them. */
    private fun libraryTables(db: Db): Map<String, List<String>> = Backups.TABLES.associateWith { table ->
        val columns = db.query("SELECT name FROM pragma_table_info(?)", table) { it.text(0)!! }
        db.query("SELECT ${columns.joinToString(" || ',' || ") { "quote(\"$it\")" }} FROM $table") { it.text(0)!! }.sorted()
    }

    @Test fun aBackupRestoresTheLibraryTablesExactly() {
        val phone = phone("sync/fixtures/rich.jsonl")
        val before = phone.write { db -> libraryTables(db) }
        assertTrue(before.getValue("songs").size >= 3 && before.getValue("phone_overrides").isNotEmpty())
        val backup = assertNotNull(phone.write { db -> Take.backupBeforeSync(db, phone.state, NOW) })
        assertEquals(File(phone.state, "backups/before-sync-2026-10-31T000000Z.sqlite"), backup)
        phone.write { db ->
            db.execute("DELETE FROM songs WHERE id = (SELECT MIN(id) FROM songs)")
            db.execute("UPDATE versions SET label = 'changed'")
            db.execute("DELETE FROM removed")
            db.kvSet("sheet_versions:yours:999", "{}")
            db.execute("INSERT INTO phone_songbooks (key, name, songs, position) VALUES ('new', 'New', '[]', 9)")
            db.execute("DELETE FROM phone_overrides")
        }
        assertTrue(phone.write { db -> libraryTables(db) } != before)
        phone.write { db -> Take.restore(db, backup) }
        assertEquals(before, phone.write { db -> libraryTables(db) })
        // The backup is a whole database of its own: caracole's schema and the phone's, the index tables empty.
        Database(backup).use { copy ->
            assertEquals(before, copy.read { db -> libraryTables(db) })
            copy.read { db ->
                assertEquals(Database.SCHEMA_VERSION.toLong(), db.one("PRAGMA user_version") { it.long(0) })
                assertEquals(0L, db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) })
            }
        }
    }

    @Test fun aBackupMadeBeforeATakeRestoresTheLibraryTablesExactly() {
        val record = Corpus.records("sync/take.jsonl").first { text(it.extra["case"]) == "respelling" }
        val phone = phone("sync/fixtures/take_respelling.jsonl")
        val before = phone.write { db -> libraryTables(db) }
        val backup = phone.write { db -> Take.backupBeforeSync(db, phone.state, NOW) }!!
        val done = phone.write { db ->
            Take.applyUnits(db, phone.store, InlineSource.of(record.extra.getValue("source").jsonObject),
                            record.args[0].jsonArray.map { w -> w.jsonArray.let { text(it[0])!! to text(it[1]) } },
                            record.kw.getValue("expected_here").jsonObject.mapValues { text(it.value) }, NOW)
        }
        assertEquals(listOf("song/radiohead/creep"), done.taken)
        assertTrue(phone.write { db -> libraryTables(db) } != before)
        phone.write { db -> Take.restore(db, backup) }
        assertEquals(before, phone.write { db -> libraryTables(db) })
    }

    @Test fun threeBackupsAreKeptAndNoneIsMadeWithoutRoom() {
        val phone = phone("sync/fixtures/plain.jsonl")
        val made = (1..5).map { day -> phone.write { db -> Take.backupBeforeSync(db, phone.state, "2026-11-0${day}T08:00:00Z")!! } }
        assertEquals(made.takeLast(3).map { it.name }, File(phone.state, "backups").list()!!.sorted())
        val room = Backups.freeSpace
        try {
            Backups.freeSpace = { 1024L }
            assertNull(phone.write { db -> Take.backupBeforeSync(db, phone.state, "2026-11-09T00:00:00Z") })
        } finally {
            Backups.freeSpace = room
        }
        assertEquals(made.takeLast(3).map { it.name }, File(phone.state, "backups").list()!!.sorted(), "nothing deleted")
    }

    @Test fun aBackupOfAnotherKindIsNeverRestored() {
        val phone = phone()
        val junk = tmp.newFile("junk.sqlite").also { it.writeText("not a database at all, at all, at all......") }
        assertFailsWith<Exception> { phone.write { db -> Take.restore(db, junk) } }
        assertFailsWith<IllegalArgumentException> { phone.write { db -> Take.restore(db, File(tmp.root, "none")) } }
    }

    // --- the folders a take changes -------------------------------------------------------------------------------

    @Test fun anArtistsFolderIsRenamedThroughATemporaryNameAndUndoneWhole() {
        val library = tmp.newFolder("library")
        File(library, "radiohead/Creep").mkdirs()
        File(library, "radiohead/Creep/sheet.txt").writeText("[Am]")
        val folders = Folders(library)
        folders.moveFolder("radiohead", "Radiohead")
        folders.write(listOf("Radiohead", "Creep"), "sheet.txt", "[G]".toByteArray())
        folders.write(listOf("Radiohead", "Karma Police"), "sheet.txt", "[Em]".toByteArray())
        assertEquals(listOf("Radiohead"), library.list()!!.toList())
        assertEquals("[G]", File(library, "Radiohead/Creep/sheet.txt").readText())
        folders.undo()
        assertEquals(listOf("radiohead"), library.list()!!.toList())
        assertEquals(listOf("Creep"), File(library, "radiohead").list()!!.toList())
        assertEquals(listOf("sheet.txt"), File(library, "radiohead/Creep").list()!!.toList())
        assertEquals("[Am]", File(library, "radiohead/Creep/sheet.txt").readText())
    }

    @Test fun aWriteReplacesAFileOnceTheTakeIsDoneAndAFolderEmptiedGoes() {
        val library = tmp.newFolder("library")
        File(library, "Soda Stereo/De Musica Ligera").mkdirs()
        File(library, "Soda Stereo/De Musica Ligera/tab.txt").writeText("e|--3--|")
        val folders = Folders(library)
        folders.moveFiles(listOf("Soda Stereo", "De Musica Ligera"), listOf("Soda Stereo", "De Música Ligera"), listOf("tab.txt"))
        folders.write(listOf("Soda Stereo", "De Música Ligera"), "tab.txt", "e|--5--|".toByteArray())
        folders.done()
        assertEquals(listOf("De Música Ligera"), File(library, "Soda Stereo").list()!!.toList())
        assertEquals(listOf("tab.txt"), File(library, "Soda Stereo/De Música Ligera").list()!!.toList())
        assertEquals("e|--5--|", File(library, "Soda Stereo/De Música Ligera/tab.txt").readText())
    }

    @Test fun aFolderThatIsALinkIsNeverFollowed() {
        val library = tmp.newFolder("library")
        val elsewhere = tmp.newFolder("elsewhere")
        Files.createSymbolicLink(File(library, "Radiohead").toPath(), elsewhere.toPath())
        val folders = Folders(library)
        val refused = assertFailsWith<UnitError> { folders.write(listOf("Radiohead", "Creep"), "sheet.txt", ByteArray(1)) }
        assertEquals("Radiohead/ is a symbolic link or no folder, which caracole doesn't follow", refused.message)
        assertFailsWith<UnitError> { folders.moveFolder("Radiohead", "radiohead") }
        folders.undo()
        assertEquals(emptyList(), elsewhere.list()!!.toList())
    }

    companion object {
        const val NOW = "2026-10-31T00:00:00Z"
    }
}
