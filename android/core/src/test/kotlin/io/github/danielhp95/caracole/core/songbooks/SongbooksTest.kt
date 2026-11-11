package io.github.danielhp95.caracole.core.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.UnitSource
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SongbookReplay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** songbook.py's names, entries and writers on the phone: the corpus's songbook area replayed (SongbookReplay), and
 * what the vectors can't show: a refusal writes nothing, the stored key follows a rename, a take refuses as
 * put_songbook does. */
class SongbooksTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }

    @After fun close() = database.close()

    private fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)

    private fun songs(vararg entries: String): JsonArray = Json.parseToJsonElement(
        entries.joinToString(",", "[", "]") { """["$it", {}]""" }) as JsonArray

    private fun rows(): List<List<String?>> = database.read { db ->
        db.query("SELECT key, name, songs, position FROM phone_songbooks ORDER BY position") {
            listOf(it.text(0), it.text(1), it.text(2), it.text(3))
        }
    }

    @Test fun everyRecordOfTheSongbookAreaIsAnsweredAsPythonAnswers() {
        val misses = Misses("songbook")
        SongbookReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked > 400, "${misses.checked} answers checked")
    }

    @Test fun aRefusalWritesNothing() {
        write { db ->
            Songbooks.make(db, "Campfire", listOf("Radiohead - Creep", "Oasis - Wonderwall"))
            Songbooks.make(db, "Camp/Fire", emptyList())
        }
        val before = rows()
        val refusals = listOf<(Db) -> Unit>(
            { Songbooks.make(it, "campfire", listOf("A - B")) },
            { Songbooks.make(it, "Camp-Fire", listOf("A - B")) },
            { Songbooks.add(it, "Campfire", listOf("A - B", "Creep")) },
            { Songbooks.move(it, "Campfire", "Muse - Hysteria", 1) },
            { Songbooks.rename(it, "Camp/Fire", "CAMPFIRE") },
            { Songbooks.delete(it, "Picnic") },
            { SongbookStore.put(it, "Camp-Fire", songs("A - B")) },
        )
        for (refusal in refusals) assertFailsWith<SongbookError> { write(refusal) }
        assertEquals(before, rows())
    }

    @Test fun aRenameKeepsTheRowItsPlaceAndWritesItsKeyAfresh() {
        write { db ->
            Songbooks.make(db, "Campfire", listOf("Radiohead - Creep"))
            Songbooks.make(db, "Weddings", emptyList())
            Songbooks.make(db, "Road trip", emptyList())
            assertEquals("Fireside", Songbooks.rename(db, "WEDDINGS", "  Fireside ").name)
            Songbooks.rename(db, "campfire", "CAMPFIRE")
        }
        assertEquals(listOf(listOf("campfire", "CAMPFIRE", """[["Radiohead - Creep",{}]]""", "0"),
                            listOf("fireside", "Fireside", "[]", "1"), listOf("road trip", "Road trip", "[]", "2")),
                     rows())
        assertTrue(database.read { db -> Units.libraryState(db).keys.filter { it.startsWith("songbook/") } } ==
            listOf("songbook/campfire", "songbook/fireside", "songbook/road trip"))
    }

    @Test fun aSongsSettingIsKeptByEveryWriterThatMovesIt() {
        write { db ->
            SongbookStore.put(db, "Gig", Json.parseToJsonElement(
                """[["Oasis - Wonderwall", {}], ["Radiohead - Creep", {"key": "G", "capo": 2, "mode": "dorian",
                   "instrument": "ukulele"}]]""") as JsonArray)
            assertEquals(1, Songbooks.move(db, "gig", "radiohead - creep", 1))
            assertEquals(listOf("A - B"), Songbooks.add(db, "Gig", listOf("A - B")))
        }
        val gig = database.read { db -> Songbooks.find(Songbooks.all(db), " GIG ") }!!
        assertEquals(listOf(SongbookSong("Radiohead - Creep", Setting("G", "dorian", 2, "ukulele")),
                            SongbookSong("Oasis - Wonderwall"), SongbookSong("A - B")), gig.songs)
        assertEquals(listOf("Radiohead - Creep", "Oasis - Wonderwall", "A - B"), gig.texts)
        assertEquals(Canonical.write(Json.parseToJsonElement(
            """{"name": "Gig", "songs": [["Radiohead - Creep", {"capo": 2, "instrument": "ukulele", "key": "G",
               "mode": "dorian"}], ["Oasis - Wonderwall", {}], ["A - B", {}]]}""")), Canonical.write(Songbooks.value(gig)))
        val deleted = write { db -> Songbooks.delete(db, "gig") }
        assertEquals(gig, deleted)
        assertNull(database.read { db -> Songbooks.find(Songbooks.all(db), "Gig") })
    }

    @Test fun anEntrysKeysAreInPythonsOrderSoTheFirstCutTheLibraryHasIsItsSong() {
        // "a-b/c" sorts before "a/b-c" ('-' is U+002D, '/' U+002F); a key beyond the BMP after U+FF61, as Python sorts.
        assertEquals(listOf("a-b/c", "a/b-c"), Songbooks.entryKeys("A - B - C").toList())
        val store = LibraryStore(tmp.newFolder("library"))
        write { db ->
            store.add(db, "A", "B - C", now = NOW)
            store.add(db, "A - B", "C", now = NOW)
            assertEquals("a-b/c", Songbooks.findEntrySong(db, "A - B - C")?.key)
            assertEquals("a/b-c", Songbooks.findEntrySong(db, "A - B C")?.key) // punctuation is no part of a key
            assertNull(Songbooks.findEntrySong(db, "A - C"))
            assertTrue(Songbooks.sameEntry("A - B - C", "a - b - c"))
        }
    }

    @Test fun aTakeLeavesASongbookPutSongbookWouldRefuse() {
        write { db -> Songbooks.make(db, "Camp/Fire", listOf("Oasis - Wonderwall")) }
        val docs = mapOf(
            "songbook/camp-fire" to obj("""{"name": "Camp-Fire", "songs": [["A - B", {}]]}"""),
            "songbook/late night" to obj("""{"name": "  Late   night ", "songs": [["A - B", {}]]}"""),
            "songbook/.x" to obj("""{"name": ".x", "songs": []}"""),
        )
        val source = object : UnitSource {
            override fun unit(id: String): JsonObject? = docs[id]
            override fun file(songKey: String, name: String, sha256: String): ByteArray = error("no file")
        }
        val wanted = docs.map { (id, doc) -> id to Canonical.digest(Units.valueOfDocument(id, doc)!!) }
        val done = write { db -> Take.applyUnits(db, LibraryStore(tmp.root), source, wanted, emptyMap(),
                                                 NOW) }
        assertEquals(listOf("songbook/late night"), done.taken)
        assertEquals(listOf(
            "songbook/.x" to "A songbook's name can't start with a dot (its folder would hide): '.x'",
            "songbook/camp-fire" to "\"Camp-Fire\" would share the folder _songbooks/Camp-Fire with the songbook " +
                "\"Camp/Fire\": pick another name"), done.left.sortedBy { it.first })
        assertEquals(listOf("Camp/Fire", "Late night"), database.read { db -> Songbooks.all(db).map { it.name } })
    }

    @Test fun aPutChecksTheNameFirstAsPutSongbookDoesAndATakeTheSettingFirstAsApplyUnitsDoes() {
        val badEntry = Json.parseToJsonElement("""[["A - B", {"tempo": 90}]]""") as JsonArray
        val e = assertFailsWith<SongbookError> { write { db -> SongbookStore.put(db, ".x", badEntry) } }
        assertEquals("A songbook's name can't start with a dot (its folder would hide): '.x'", e.message)
        assertFailsWith<IllegalArgumentException> { write { db -> SongbookStore.put(db, "Campfire", badEntry) } }

        val docs = mapOf("songbook/.x" to obj("""{"name": ".x", "songs": [["A - B", {"capo": 99}]]}"""))
        val source = object : UnitSource {
            override fun unit(id: String): JsonObject? = docs[id]
            override fun file(songKey: String, name: String, sha256: String): ByteArray = error("no file")
        }
        val wanted = docs.map { (id, doc) -> id to Canonical.digest(Units.valueOfDocument(id, doc)!!) }
        val done = write { db -> Take.applyUnits(db, LibraryStore(tmp.root), source, wanted, emptyMap(), NOW) }
        // apply_units' words for this very unit (peer_sync._apply checks the setting before put_songbook the name)
        assertEquals(listOf("songbook/.x" to "a setting: capo must be a fret from 0 to 11, got 99"), done.left)
        assertEquals(emptyList(), rows())
    }

    @Test fun aSettingIsCheckedFirstThenGivenToTheFirstSongOfThatEntryInItsPlace() {
        write { db -> Songbooks.make(db, "Gig", listOf("Radiohead - Creep", "Oasis - Wonderwall")) }
        val asked = ArrayList<Setting>()
        val problem = { s: Setting -> asked += s; if (s.capo == 99) "capo must be a fret from 0 to 11, got 99" else null }
        val refused = assertFailsWith<SongbookError> {
            write { db -> Songbooks.set(db, "Nowhere", "Oasis - Wonderwall", Setting(capo = 99), problem) }
        }
        assertEquals("a setting: capo must be a fret from 0 to 11, got 99", refused.message) // before the songbook
        val missing = assertFailsWith<SongbookError> {
            write { db -> Songbooks.set(db, "gig", "Muse - Hysteria", Setting(key = "G"), problem) }
        }
        assertEquals("\"Muse - Hysteria\" isn't in the songbook \"Gig\": caracole songbook show lists its songs",
                     missing.message)
        write { db -> Songbooks.set(db, "GIG", "oasis - WONDERWALL", Setting("G", "dorian", 0, "ukulele"), problem) }
        assertEquals(listOf(Setting(capo = 99), Setting(key = "G"), Setting("G", "dorian", 0, "ukulele")), asked)
        val gig = database.read { db -> Songbooks.find(Songbooks.all(db), "Gig")!! }
        assertEquals(listOf(SongbookSong("Radiohead - Creep"), SongbookSong("Oasis - Wonderwall",
                                                                            Setting("G", "dorian", 0, "ukulele"))),
                     gig.songs)  // as written, its setting's parts in songbook_value's order
        assertEquals(Canonical.write(Json.parseToJsonElement(
            """{"name": "Gig", "songs": [["Radiohead - Creep", {}], ["Oasis - Wonderwall", {"capo": 0,
               "instrument": "ukulele", "key": "G", "mode": "dorian"}]]}""")), Canonical.write(Songbooks.value(gig)))
        // None, or an empty setting, takes it off: the song says nothing again
        write { db -> Songbooks.set(db, "Gig", "Oasis - Wonderwall", Setting(), problem) }
        assertEquals(3, asked.size)  // a setting that says nothing is no setting to check, as check_setting's caller has it
        assertEquals(listOf(null, null), database.read { db -> Songbooks.all(db).single().songs.map { it.setting } })
        write { db -> Songbooks.set(db, "Gig", "Radiohead - Creep", Setting(capo = 2), problem) }
        write { db -> Songbooks.set(db, "Gig", "Radiohead - Creep", null, problem) }
        assertEquals(listOf(null, null), database.read { db -> Songbooks.all(db).single().songs.map { it.setting } })
    }

    @Test fun theSongbooksThatListASongAreFoundByItsEntryAloneItsKeysMadeCurrentFirst() {
        val store = LibraryStore(tmp.newFolder("library"))
        val (creep, police) = write { db ->
            store.add(db, "Radiohead", "Creep", now = NOW) to store.add(db, "Radiohead", "Karma Police", now = NOW)
        }
        write { db ->
            Songbooks.make(db, "Gig", listOf("radiohead - CREEP", "Radiohead - Karma Police Live"))
            Songbooks.make(db, "Picnic", listOf("Radiohead - Karma Police"))
            Songbooks.make(db, "Empty", emptyList())
            // a song keyed a KEY_VERSION behind: found once the library is re-keyed, in the same write
            db.execute("UPDATE songs SET key = ? WHERE id = ?", "stale/creep", creep.id)
            db.kvSet("songs:key_version", "0")
        }
        val (gig, picnic) = write { db ->
            val books = Songbooks.all(db)
            Songbooks.listing(db, books, creep).map { it.name } to Songbooks.listing(db, books, police).map { it.name }
        }
        assertEquals(listOf("Gig"), gig)
        assertEquals(listOf("Picnic"), picnic)  // "Karma Police Live" names no song: never by a search
        assertEquals("radiohead/creep", database.read { db -> db.one("SELECT key FROM songs WHERE id = ?", creep.id) {
            it.text(0) } })
    }

    private fun obj(text: String): JsonObject = Json.parseToJsonElement(text).jsonObject

    private companion object {
        const val NOW = "2026-11-03T12:00:00Z"
    }
}
