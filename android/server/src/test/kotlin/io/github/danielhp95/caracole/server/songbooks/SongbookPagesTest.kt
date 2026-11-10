package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions as LibraryVersions
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.testing.replays.SongbookTabReplay
import io.github.danielhp95.caracole.viewer.pages.SongbookPage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** render_songbooks on the phone: each songbook's songbook.html written only when what it is made from changed or it
 * is no longer as written, recorded in kv `songbook:<folder>` as songbook.py's `_record`, and the files of the
 * songbooks gone taken away as `_remove_gone` takes them; and every songbook page of the corpus (songbook_pages.jsonl),
 * the songbook-tab area's. */
class SongbookPagesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }
    private val library: File by lazy { tmp.newFolder("library") }
    private val store: LibraryStore by lazy { LibraryStore(library) }
    private val pages: SongbookPagesImpl by lazy { SongbookPagesImpl(database, store) }

    @After fun close() = database.close()

    private fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)

    @Test fun everySongbookPageIsBookPys() {
        val misses = Misses("songbook-tab pages")
        SongbookTabReplay.pages(misses)
        misses.assertNone()
        assertTrue(misses.checked >= 15, "${misses.checked} pages checked")
    }

    @Test fun theWholeAreaReplays() {
        val misses = Misses("songbook-tab")
        SongbookTabReplay.replay(misses)
        misses.assertNone()
    }

    private fun rendered(db: Db, artist: String, title: String, cho: String): SongRow {
        val song = store.add(db, artist, title, now = NOW)
        val version = LibraryVersions.upsert(db, "ug", "1${song.id}", song.id, "sheet", "chords", 4.5, 3, 1, null, "",
                                             JsonObject(emptyMap()), NOW)
        Kept.keepFile(db, store, song, version, "sheet.txt", "words".toByteArray(), 1, NOW)
        val data = cho.toByteArray()
        Kept.writeAtomic(File(store.folderOf(song), "sheet.cho").toPath(), data)
        db.kvSetJson("render:files:${song.id}", JsonObject(linkedMapOf(
            "sheet.cho" to JsonObject(linkedMapOf("sha256" to JsonPrimitive(Canonical.sha256Hex(data)),
                                                  "size" to JsonPrimitive(data.size))))))
        return song
    }

    private fun record(db: Db, folder: String): JsonObject = PyJson.loads(db.kvGet("songbook:$folder")!!).jsonObject

    @Test fun aSongbooksPageIsWrittenRecordedAndMadeAgainOnlyWhenItChangedOrIsNoLongerAsWritten() {
        val page = File(library, "_songbooks/Camp Fire/songbook.html")
        write { db ->
            rendered(db, "Radiohead", "Creep", "{title: Creep}\n{artist: Radiohead}\n[G]Words [B]here\n")
            Songbooks.make(db, "Camp Fire", listOf("Radiohead - Creep", "Muse - Hysteria"))
            Songbooks.make(db, "Picnic", emptyList())
        }
        assertEquals(SongbookStats(rendered = 2), write { db -> pages.render(db, null) })
        val bytes = page.readBytes()
        val entries = database.read { db ->
            SongbookEntries.entries(db, library, Overrides(), Songbooks.find(Songbooks.all(db), "camp fire")!!, rekey = false)
        }
        assertEquals(SongbookPage.build("Camp Fire", SongbookPagesImpl.bookSongs(entries)), String(bytes))
        val record = database.read { db -> record(db, "Camp Fire") }
        assertEquals(listOf("inputs", "files"), record.keys.toList())
        assertEquals(JsonObject(linkedMapOf("songbook.html" to JsonObject(linkedMapOf(
            "sha256" to JsonPrimitive(Canonical.sha256Hex(bytes)), "size" to JsonPrimitive(bytes.size))))), record["files"])
        // nothing changed: nothing written
        assertEquals(SongbookStats(skipped = 2), write { db -> pages.render(db, null) })
        // only the songbooks asked for, by their names in any case
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, setOf("PICNIC")) })
        // a setting moves its song: the page again
        write { db -> Songbooks.set(db, "Camp Fire", "Radiohead - Creep", Setting(key = "A")) { null } }
        assertEquals(SongbookStats(rendered = 1, skipped = 1), write { db -> pages.render(db, null) })
        assertFalse(bytes.contentEquals(page.readBytes()))
        // changed on a device: written again, as it was
        val now = page.readBytes()
        page.writeBytes("a page of someone else's".toByteArray())
        assertEquals(SongbookStats(rendered = 1), write { db -> pages.render(db, setOf("Camp Fire")) })
        assertTrue(now.contentEquals(page.readBytes()))
    }

    @Test fun aSongbookGoneTakesItsPageAndItsFolderButNeverAFileOfYours() {
        write { db ->
            Songbooks.make(db, "Gig", listOf("Muse - Hysteria"))
            Songbooks.make(db, "Picnic", listOf("Muse - Hysteria"))
            pages.render(db, null)
        }
        val gig = File(library, "_songbooks/Gig")
        val picnic = File(library, "_songbooks/Picnic")
        File(picnic, "notes.txt").writeText("mine")
        write { db ->
            Songbooks.delete(db, "Gig")
            Songbooks.delete(db, "Picnic")
        }
        assertEquals(SongbookStats(removed = 2), write { db -> pages.render(db, null) })
        assertFalse(gig.exists())
        assertEquals(listOf("notes.txt"), picnic.list()!!.toList())  // its folder stays, with your file
        assertNull(database.read { db -> db.kvGet("songbook:Gig") ?: db.kvGet("songbook:Picnic") })
    }

    @Test fun aPageChangedOnADeviceIsNeverTakenAwayAndALinkIsNeverFollowed() {
        write { db ->
            Songbooks.make(db, "Gig", emptyList())
            pages.render(db, null)
        }
        val page = File(library, "_songbooks/Gig/songbook.html")
        page.writeText("yours now")
        write { db -> Songbooks.delete(db, "Gig") }
        assertEquals(SongbookStats(removed = 1), write { db -> pages.render(db, null) })
        assertEquals("yours now", page.readText())

        // a link in place of _songbooks: no page through it, the songbook failed and the others go on
        val elsewhere = tmp.newFolder("elsewhere")
        Files.delete(page.toPath())
        Files.delete(page.parentFile.toPath())
        Files.delete(File(library, "_songbooks").toPath())
        Files.createSymbolicLink(File(library, "_songbooks").toPath(), elsewhere.toPath())
        write { db -> Songbooks.make(db, "Road", emptyList()) }
        assertEquals(SongbookStats(failed = listOf("Road")), write { db -> pages.render(db, null) })
        assertEquals(emptyList(), elsewhere.list()!!.toList())
        assertNull(database.read { db -> db.kvGet("songbook:Road") })
    }

    @Test fun aSongsIdAndWhereItStartsAreSongbookPys() {
        val entry = Entry("Radiohead - Creep", "Creep", "Radiohead")
        assertEquals(Canonical.sha256Hex("Radiohead - Creep".toByteArray()).take(10), SongbookPagesImpl.songId(entry))
        assertNull(SongbookPagesImpl.start(entry))
        assertNull(SongbookPagesImpl.start(entry.copy(version = entry.version.copy(t = 3))))
        assertEquals("t=0&mode=dorian", SongbookPagesImpl.start(entry.copy(version = entry.version.copy(mode = "dorian"))))
        assertEquals("t=2&inst=guitar", SongbookPagesImpl.start(entry.copy(version = entry.version.copy(t = 2),
                                                                           setting = Setting(instrument = "guitar"))))
        assertEquals("t=-1&capo=0&inst=piano", SongbookPagesImpl.start(entry.copy(
            version = entry.version.copy(t = -1, capo = 0, inst = "piano"), setting = Setting(instrument = "piano"))))
    }

    @Test fun theLookupsSeamWaitsForThePhoneToServeItsPages() {
        assertSame(SongbookPages.NONE, pages.seam)
    }

    private companion object {
        const val NOW = "2026-11-03T12:00:00Z"
    }
}
