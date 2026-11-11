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
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import io.github.danielhp95.caracole.core.testing.sync.InlineSource
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Take against Python's peer_sync.apply_units: every case of vectors/sync/take.jsonl (§5.6's rules, the
 * compare-and-swap, a unit left whole), every fixture of vectors/sync taken into an empty phone, checked_name (their
 * loops SyncReplay's, which the device runs too); and the backup before a sync, which restore puts back.
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
        Misses("sync/checked_name.jsonl").also { SyncReplay.checkedName(it) }.assertNone()
        assertEquals("a kept file named '../sheet.txt', which no song's folder holds",
                     assertFailsWith<UnitError> { Take.checkedName("../sheet.txt") }.message)
    }

    // --- apply_units ----------------------------------------------------------------------------------------------

    @Test fun eachTakeDoesWhatPythonsDoes() = Misses(SyncReplay.TAKE).also { SyncReplay.takes(it) }.assertNone()

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
                            "nonsense/x" to "we don't know entries of kind 'nonsense'"), done.left)
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

    /** A `now` whose UTC is before year 1: Python's take raises on it only once a song unit reads it (`_when`); the
     * re-keying before any unit stamps its records with the clock, as for a `now` that names no time. */
    @Test fun aNowOutsideTheYearsADatetimeHoldsStopsNoUnitButASongs() {
        val phone = phone()
        val (source, wanted) = documents("alias/soda" to json("""{"slugs": ["soda-stereo"]}"""),
                                         "block/4242" to json("""{"tab": 4242}"""))
        for (now in listOf("0001-01-01T00:00:00+01:00", "soon")) {
            val done = phone.write { db -> Take.applyUnits(db, phone.store, source, wanted, emptyMap(), now) }
            assertEquals(listOf("alias/soda", "block/4242"), done.taken.sorted(), now)
            assertEquals(emptyList(), done.left, now)
        }
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
                            "songbook/road" to "its entry can't be read (TypeError: check_setting() got an unexpected " +
                                "keyword argument 'tempo')"), done.left)
        phone.write { db -> assertEquals(listOf("Home"), io.github.danielhp95.caracole.core.library.SongbookStore.all(db).map { it.name }) }
    }

    @Test fun everyFixtureTakenIntoAnEmptyPhoneIsItsValuesAndDigests() =
        Misses("sync fixtures taken").also { SyncReplay.fixturesTaken(it) }.assertNone()

    @Test fun everyTakesFixtureCopiedUnitByUnitIntoAnEmptyPhoneIsTheSameLibrary() =
        Misses("take.jsonl's fixtures copied").also { SyncReplay.takesCopied(it) }.assertNone()

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
        assertEquals(emptyList(), SyncReplay.filesOf(phone.library))
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
        val backup = assertNotNull(phone.write { db -> Take.backupBeforeSync(db, phone.state, NOW, phone.store) })
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
        val backup = phone.write { db -> Take.backupBeforeSync(db, phone.state, NOW, phone.store) }!!
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
        val made = (1..5).map { day -> phone.write { db -> Take.backupBeforeSync(db, phone.state, "2026-11-0${day}T08:00:00Z", phone.store)!! } }
        assertEquals(made.takeLast(3).map { it.name }, File(phone.state, "backups").list()!!.filter { it.endsWith(".sqlite") }.sorted())
        val room = Backups.freeSpace
        try {
            Backups.freeSpace = { 1024L }
            assertNull(phone.write { db -> Take.backupBeforeSync(db, phone.state, "2026-11-09T00:00:00Z", phone.store) })
        } finally {
            Backups.freeSpace = room
        }
        assertEquals(made.takeLast(3).map { it.name }, File(phone.state, "backups").list()!!.filter { it.endsWith(".sqlite") }.sorted(), "nothing deleted")
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
        assertEquals("Radiohead/ is a symbolic link or no folder: we don't follow it", refused.message)
        assertFailsWith<UnitError> { folders.moveFolder("Radiohead", "radiohead") }
        folders.undo()
        assertEquals(emptyList(), elsewhere.list()!!.toList())
    }

    companion object {
        const val NOW = "2026-10-31T00:00:00Z"
        val LYRICS = setOf("lyrics.txt", "lyrics.lrc")
    }
}
