package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions as LibraryVersions
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.page.SongCards
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
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** songbook.py's entries and plays and songbook_section's data on the phone: the corpus's songbook-tab area replayed
 * (entries.jsonl, tab.jsonl), and what the vectors can't show: a sheet changed on disk, a link in a sheet's place, the
 * mirror's sheet of a song whose pages are the computer's, a line's sheet as its card opens it, a read that never
 * re-keys. */
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

    /** A song taken from the computer: its sheet.txt kept, no page of the phone's (no render record). */
    private fun taken(db: Db, artist: String, title: String): SongRow {
        val song = store.add(db, artist, title, now = NOW)
        val version = LibraryVersions.upsert(db, provider = "ug", tabId = "2${song.id}", songId = song.id, slot = "sheet",
                                             kind = "chords", rating = 4.5, votes = 3, version = 1, label = null,
                                             url = "", raw = JsonObject(emptyMap()), now = NOW)
        Kept.keepFile(db, store, song, version, "sheet.txt", "words".toByteArray(), 1, NOW)
        return song
    }

    /** A mirror holding [files] (path, content, unit, digest), as a sync leaves one: its blobs and its list. */
    private fun mirror(vararg files: List<String?>): Mirror {
        val mirror = Mirror(tmp.newFolder())
        mirror.blobs.mkdirs()
        val start = "index.html"
        val entries = (files.toList() + listOf(listOf(start, "<!doctype html>start", null, null))).map { (path, content, unit, digest) ->
            val bytes = content!!.toByteArray()
            File(mirror.blobs, Canonical.sha256Hex(bytes)).writeBytes(bytes)
            val page = path!!.endsWith(".html")
            JsonObject(buildMap {
                put("path", JsonPrimitive(path)); put("url", JsonPrimitive("/" + PyUrl.quote(path)))
                put("size", JsonPrimitive(bytes.size)); put("sha256", JsonPrimitive(Canonical.sha256Hex(bytes)))
                put("type", JsonPrimitive(if (page) "text/html; charset=utf-8" else "text/plain; charset=utf-8"))
                put("headers", JsonObject(emptyMap()))
                unit?.let { put("unit", JsonPrimitive(it)) }
                digest?.let { put("digest", JsonPrimitive(it)) }
            })
        }
        mirror.manifestFile.writeText(JsonObject(mapOf("format" to JsonPrimitive(1), "start" to JsonPrimitive(start),
                                                       "files" to JsonArray(entries))).toString())
        assertEquals(files.map { it[2] }, mirror.reload()!!.entries.dropLast(1).map { it.unit })
        return mirror
    }

    @Test fun aSongWhosePagesAreTheComputersPlaysFromTheMirrorsSheetWhileItIsOfTheSongAsThePhoneHoldsIt() {
        val cho = "{title: Creep}\n{artist: Radiohead}\n[G]Words [B]here\n"
        database.writeBlocking { db ->
            val song = taken(db, "Radiohead", "Creep")
            val unit = "song/${song.key}"
            val now = Units.digestOf(db, unit)!!
            val book = Songbook("Gig", listOf(SongbookSong("Radiohead - Creep", Setting(key = "A"))))
            // with no mirror, as on the computer: the phone wrote no .cho of it, so no sheet yet, and a get would ask
            val alone = SongbookEntries.entries(db, library, Overrides(), book).single()
            assertEquals(SongbookEntries.MISSING_SHEET, alone.missing)
            assertEquals(listOf(song.key), SongbookEntries.songsToGet(listOf(alone), Overrides()).map { it.key })
            // the computer's sheet.cho of the song as the phone holds it: its sheet, and nothing to get
            val served = mirror(listOf("Radiohead/Creep/sheet.cho", cho, unit, now))
            val (entry) = SongbookEntries.entries(db, library, Overrides(), book, mirror = served)
            assertEquals(cho, entry.cho)
            assertNull(entry.missing)
            assertEquals("A Major", SongbookEntries.playsIn(entry))
            assertEquals(emptyList(), SongbookEntries.songsToGet(listOf(entry), Overrides()))
            // made of the song at another digest (the phone changed it since), of another unit, of none: none
            for (other in listOf(listOf("Radiohead/Creep/sheet.cho", cho, unit, "0".repeat(64)),
                                 listOf("Radiohead/Creep/sheet.cho", cho, "song/someone-else", now),
                                 listOf("Radiohead/Creep/sheet.cho", cho, null, null))) {
                assertNull(SongbookEntries.sheetOf(db, library, song, mirror(other)), other.toString())
            }
            // a blob that isn't the bytes listed: none
            File(served.blobs, Canonical.sha256Hex(cho.toByteArray())).writeText("{title: changed}\n")
            assertNull(SongbookEntries.sheetOf(db, library, song, served))
        }
    }

    @Test fun theSheetThePhoneWroteGoesBeforeTheMirrorsAndOneChangedOnDiskIsNoneEvenWithTheMirrors() {
        val cho = "{title: Creep}\n{artist: Radiohead}\n[G]Words [B]here\n"
        database.writeBlocking { db ->
            val song = rendered(db, "Radiohead", "Creep", cho)
            val unit = "song/${song.key}"
            val served = mirror(listOf("Radiohead/Creep/sheet.cho", "{title: the computer's}\n", unit, Units.digestOf(db, unit)))
            assertEquals("sheet.cho" to cho, SongbookEntries.sheetOf(db, library, song, served))
            Files.write(File(store.folderOf(song), "sheet.cho").toPath(), "{title: changed}\n".toByteArray())
            assertNull(SongbookEntries.sheetOf(db, library, song, served))
        }
    }

    @Test fun aSetListsSheetOpensAsItsLineOpensItAndAnEmptySheetLinksNone() {
        database.writeBlocking { db ->
            rendered(db, "Radiohead", "Creep", "{title: Creep}\n")
            rendered(db, "Muse", "Hysteria", "")
            Songbooks.make(db, "Gig", listOf("Radiohead - Creep", "Muse - Hysteria"))
        }
        File(store.libraryDir, "Radiohead/Creep/sheet.html").writeText("a page")
        fun hrefs(cards: SongCards?) = database.read { db ->
            SongbookSection.data(db, library, Overrides.read(db), rekey = false, cards = cards)
        }.getValue("books").jsonArray.single().jsonObject.getValue("set").jsonArray.map { it.jsonObject["href"] }
        // library_page.sheet_href over the folder; an empty .cho is no sheet to link, as Python's `e.cho` is false
        assertEquals(listOf(JsonPrimitive("Radiohead/Creep/sheet.html"), JsonNull), hrefs(null))
        // the card's primary file, which the song's line opens
        val cards = object : SongCards {
            override fun cards(db: Db, songs: List<SongRow>) = songs.associate { song ->
                song.id to JsonObject(mapOf("files" to JsonArray(listOf(
                    JsonObject(mapOf("href" to JsonPrimitive("Radiohead/Creep/sheet.txt"), "primary" to JsonPrimitive(false))),
                    JsonObject(mapOf("href" to JsonPrimitive("Radiohead/Creep/sheet.pdf"), "primary" to JsonPrimitive(true))),
                ))))
            }
        }
        assertEquals(listOf(JsonPrimitive("Radiohead/Creep/sheet.pdf"), JsonNull), hrefs(cards))
        // a card that names no primary file: the folder's, as on the computer
        val none = object : SongCards {
            override fun cards(db: Db, songs: List<SongRow>) = songs.associate { it.id to JsonObject(emptyMap()) }
        }
        assertEquals(listOf(JsonPrimitive("Radiohead/Creep/sheet.html"), JsonNull), hrefs(none))
    }

    @Test fun theTabsDataForJobsJsonIsTheMirrorsWhileTheKeysAreAKeyVersionBehind() {
        database.writeBlocking { db ->
            store.add(db, "Muse", "Hysteria", now = NOW)
            Songbooks.make(db, "Camp Fire", listOf("Muse - Hysteria"))
        }
        assertEquals("Muse - Hysteria", database.read { db -> SongbookSection.data(db, store, null, null) }!!
            .getValue("books").jsonArray.single().jsonObject.getValue("set").jsonArray.single().jsonObject
            .getValue("entry").jsonPrimitive.content)
        database.writeBlocking { db -> db.kvSet("songs:key_version", "1") }  // an app whose keys moved, not re-keyed yet
        assertNull(database.read { db -> SongbookSection.data(db, store, null, null) })
        database.writeBlocking { db -> store.ensureCurrentKeys(db) }  // the render job its start queues re-keys
        assertEquals(Normalize.KEY_VERSION.toString(), database.read { db -> db.kvGet("songs:key_version") })
        assertNotNull(database.read { db -> SongbookSection.data(db, store, null, null) })
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
        val data = database.read { db -> SongbookSection.data(db, library, Overrides.read(db), rekey = false) }
        assertEquals(JsonArray(listOf(JsonPrimitive("Phone page"))), data["fileLabels"])
        val book = data.getValue("books").jsonArray.single().jsonObject
        assertEquals(JsonArray(emptyList()), book["files"])  // the computer's PDF is no file of the phone's
        assertEquals(JsonNull, book["changed"])
        File(folder, "songbook.html").writeBytes(byteArrayOf(2))
        val made = database.read { db -> SongbookSection.data(db, library, Overrides.read(db), rekey = false) }.getValue("books").jsonArray.single().jsonObject
        assertEquals("_songbooks/Camp%20Fire/songbook.html",
                     made.getValue("files").jsonArray.single().jsonObject.getValue("href").jsonPrimitive.content)
        assertEquals("0", database.read { db -> db.kvGet("songs:key_version") })
    }

    private companion object {
        const val NOW = "2026-11-03T12:00:00Z"
    }
}
