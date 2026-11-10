package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFile
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions as LibraryVersions
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.page.SongbookSection
import io.github.danielhp95.caracole.server.testing.replays.SongbookTabReplay
import kotlinx.serialization.json.JsonArray
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
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** songbook.py's entries and plays and songbook_section's data on the phone: the corpus's songbook-tab area replayed
 * (entries.jsonl, tab.jsonl), and what the vectors can't show: a sheet changed on disk, a link in a sheet's place, a
 * read that never re-keys. */
class SongbookEntriesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }
    private val library: File by lazy { tmp.newFolder("library") }
    private val store: LibraryStore by lazy { LibraryStore(library) }

    @After fun close() = database.close()

    @Test fun everyEntryPlaysAsSongbookPyPlaysIt() {
        val misses = Misses("songbook-tab entries")
        SongbookTabReplay.entries(misses)
        misses.assertNone()
        assertTrue(misses.checked > 1500, "${misses.checked} answers checked")
    }

    @Test fun theSongbooksTabIsSongbookSectionsWithThePhonesFiles() {
        val misses = Misses("songbook-tab tab")
        SongbookTabReplay.tab(misses)
        misses.assertNone()
        assertTrue(misses.checked >= 9, "${misses.checked} answers checked")
    }

    @Test fun theGuitarProMarksAreSongbookSectionsForTheFilesInboxGuitarFilesGives() {
        // inbox.guitar_files, as its SQL and its pattern read the files table (GuitarFiles.of is guitar-alphatab's)
        val files = { db: Db ->
            db.query("SELECT f.song_id, f.name, f.path FROM files f JOIN versions v ON v.id = f.version_id " +
                         "WHERE v.kind IN ('guitar-pro', 'power')") { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
                .mapNotNull { (song, name, path) ->
                    val m = Regex("guitar-(\\d+)(\\.[A-Za-z0-9]+)").matchEntire(name) ?: return@mapNotNull null
                    if (m.groupValues[2].lowercase() !in listOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")) null
                    else GuitarFile(song, name, path, m.groupValues[1].toInt())
                }
                .sortedWith(compareBy({ it.songId }, { it.number }, { it.name }))
        }
        val misses = Misses("songbook-tab tab, the marks")
        SongbookTabReplay.tab(misses, files)
        misses.assertNone()
    }

    /** A song with a sheet the phone rendered: sheet.txt kept, sheet.cho written and recorded as render.py records
     * it. */
    private fun rendered(db: Db, artist: String, title: String, cho: String): SongRow {
        val song = store.add(db, artist, title, now = NOW)
        val version = LibraryVersions.upsert(db, provider = "ug", tabId = "1${song.id}", songId = song.id, slot = "sheet",
                                             kind = "chords", rating = 4.5, votes = 3, version = 1, label = null,
                                             url = "", raw = JsonObject(emptyMap()), now = NOW)
        Kept.keepFile(db, store, song, version, "sheet.txt", "words".toByteArray(), 1, NOW)
        val data = cho.toByteArray()
        Kept.writeAtomic(File(store.folderOf(song), "sheet.cho").toPath(), data)
        db.kvSetJson("render:files:${song.id}", JsonObject(linkedMapOf(
            "sheet.cho" to JsonObject(linkedMapOf("sha256" to JsonPrimitive(Canonical.sha256Hex(data)),
                                                  "size" to JsonPrimitive(data.size))))))
        return song
    }

    @Test fun onlyTheSheetCaracoleWroteGoesIntoASongbook() {
        val cho = "{title: Creep}\n{artist: Radiohead}\n[G]Words [B]here\n"
        database.writeBlocking { db ->
            val song = rendered(db, "Radiohead", "Creep", cho)
            val book = Songbook("Gig", listOf(SongbookSong("radiohead - creep", Setting(key = "A"))))
            val (entry) = SongbookEntries.entries(db, library, Overrides(), book)
            assertEquals(cho, entry.cho)
            assertEquals("A Major", SongbookEntries.playsIn(entry))
            // changed on a device: no sheet of caracole's, so none
            val path = File(store.folderOf(song), "sheet.cho").toPath()
            Files.write(path, "{title: changed}\n".toByteArray())
            assertEquals(SongbookEntries.MISSING_SHEET, SongbookEntries.entries(db, library, Overrides(), book).single().missing)
            // a link in its place, to the very bytes recorded: never followed
            val elsewhere = File(tmp.root, "elsewhere.cho").toPath().also { Files.write(it, cho.toByteArray()) }
            Files.delete(path)
            Files.createSymbolicLink(path, elsewhere)
            assertNull(SongbookEntries.sheetOf(db, library, song))
            // a record that says nothing of the file
            Files.delete(path)
            Files.write(path, cho.toByteArray())
            db.kvSet("render:files:${song.id}", """{"sheet.cho": {"sha256": "${Canonical.sha256Hex(cho.toByteArray())}", "size": true}}""")
            assertNull(SongbookEntries.sheetOf(db, library, song))
            db.kvSet("render:files:${song.id}", "not json")
            assertNull(SongbookEntries.sheetOf(db, library, song))
        }
    }

    @Test fun anEntryTheLibraryHasNoSongOfIsNamedByItsTextAndAGetSkipsIt() {
        database.writeBlocking { db ->
            store.add(db, "Muse", "Hysteria", now = NOW)
            val book = Songbook("Gig", listOf(SongbookSong("Nobody -  Nothing  "), SongbookSong("Muse - Hysteria"),
                                              SongbookSong("muse - HYSTERIA"), SongbookSong("Creep")))
            val entries = SongbookEntries.entries(db, library, Overrides(), book)
            assertEquals(listOf("Nothing" to "Nobody", "Hysteria" to "Muse", "Hysteria" to "Muse", "Creep" to "Creep"),
                         entries.map { it.title to it.artist })
            assertEquals(listOf(SongbookEntries.MISSING_SONG, SongbookEntries.MISSING_SHEET, SongbookEntries.MISSING_SHEET,
                                SongbookEntries.MISSING_SONG), entries.map { it.missing })
            assertEquals(listOf("muse/hysteria"), SongbookEntries.songsToGet(entries, Overrides()).map { it.key })
            assertEquals(emptyList(), SongbookEntries.songsToGet(entries, Overrides(ignore = setOf("muse/hysteria"))))
            assertNull(SongbookEntries.playsIn(entries[1]))
            assertEquals(null to null, SongbookEntries.wherePlayed(entries[1]))
        }
    }

    @Test fun theTabsDataInAReadTakesTheKeysAsTheyAreAndNamesThePhonesPageAlone() {
        database.writeBlocking { db ->
            store.add(db, "Muse", "Hysteria", now = NOW)
            Songbooks.make(db, "Camp Fire", listOf("Muse - Hysteria"))
            db.kvSet("songs:key_version", "0")  // a read writes nothing, even with the keys a KEY_VERSION behind
        }
        val folder = File(library, "_songbooks/Camp Fire").also { it.mkdirs() }
        File(folder, "songbook.pdf").writeBytes(byteArrayOf(1))
        val data = database.read { db -> SongbookSection.data(db, store)!! }
        assertEquals(JsonArray(listOf(JsonPrimitive("Phone page"))), data["fileLabels"])
        val book = data.getValue("books").jsonArray.single().jsonObject
        assertEquals(JsonArray(emptyList()), book["files"])  // the computer's PDF is no file of the phone's
        assertEquals(JsonNull, book["changed"])
        File(folder, "songbook.html").writeBytes(byteArrayOf(2))
        val made = database.read { db -> SongbookSection.data(db, store)!! }.getValue("books").jsonArray.single().jsonObject
        assertEquals("_songbooks/Camp%20Fire/songbook.html",
                     made.getValue("files").jsonArray.single().jsonObject.getValue("href").jsonPrimitive.content)
        assertEquals("0", database.read { db -> db.kvGet("songs:key_version") })
    }

    private companion object {
        const val NOW = "2026-11-03T12:00:00Z"
    }
}
