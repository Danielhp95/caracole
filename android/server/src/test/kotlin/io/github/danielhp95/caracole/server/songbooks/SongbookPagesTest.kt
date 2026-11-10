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
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.testing.replays.SongbookTabReplay
import io.github.danielhp95.caracole.viewer.pages.SongbookPage
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
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
    private var stamp = "build-1"
    private val pages: SongbookPagesImpl by lazy { SongbookPagesImpl(database, store, null) { stamp } }

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
        // each file's entry names the songbook unit's digest it was made at, as WrittenPages.noteSongbook writes it
        val unit = database.read { db -> Units.digestOf(db, WrittenPages.songbookUnit(db, "Camp Fire")!!) }!!
        assertEquals(JsonObject(linkedMapOf("songbook.html" to JsonObject(linkedMapOf(
            "sha256" to JsonPrimitive(Canonical.sha256Hex(bytes)), "size" to JsonPrimitive(bytes.size),
            "unit" to JsonPrimitive(unit))))), record["files"])
        assertTrue(database.read { db -> WrittenPages.songbookCurrent(db, "Camp Fire", "songbook.html") })
        // nothing changed: nothing written
        assertEquals(SongbookStats(skipped = 2), write { db -> pages.render(db, null) })
        // only the songbooks asked for, by their names in any case
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, setOf("PICNIC")) })
        // a setting moves its song: the page again, current at the unit's digest now
        write { db -> Songbooks.set(db, "Camp Fire", "Radiohead - Creep", Setting(key = "A")) { null } }
        assertFalse(database.read { db -> WrittenPages.songbookCurrent(db, "Camp Fire", "songbook.html") })
        assertEquals(SongbookStats(rendered = 1, skipped = 1), write { db -> pages.render(db, null) })
        assertFalse(bytes.contentEquals(page.readBytes()))
        assertTrue(database.read { db -> WrittenPages.songbookCurrent(db, "Camp Fire", "songbook.html") })
        // a change to the songbook its page doesn't show (a song's setting that says what it played already): the
        // page stays as written, recorded at the digest now
        val shown = page.readBytes()
        write { db -> Songbooks.set(db, "Camp Fire", "Muse - Hysteria", Setting(key = "A")) { null } }
        assertFalse(database.read { db -> WrittenPages.songbookCurrent(db, "Camp Fire", "songbook.html") })
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, setOf("camp fire")) })
        assertTrue(shown.contentEquals(page.readBytes()))
        assertTrue(database.read { db -> WrittenPages.songbookCurrent(db, "Camp Fire", "songbook.html") })
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

    @Test fun theLookupsSeamIsTheSongbooksPages() {
        assertSame<SongbookPages>(pages, pages.seam)
    }

    @Test fun aNewBuildMakesAnOtherwiseUnchangedPageAgain() {
        write { db -> Songbooks.make(db, "Gig", listOf("Muse - Hysteria")) }
        assertEquals(SongbookStats(rendered = 1), write { db -> pages.render(db, null) })
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, null) })
        val before = database.read { db -> record(db, "Gig") }.getValue("inputs")
        stamp = "build-2"  // the app updated: the page's inputs name the build that makes it now, so it is made again
        // (here the same bytes, which aren't written again: a build whose viewer changed writes its own)
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, null) })
        assertFalse(before == database.read { db -> record(db, "Gig") }.getValue("inputs"))
        assertEquals(SongbookStats(skipped = 1), write { db -> pages.render(db, null) })
    }

    @Test fun renderOwnMakesAgainTheSongbooksThePhoneMadeAPageOfAndNoOther() {
        write { db ->
            Songbooks.make(db, "Gig", listOf("Muse - Hysteria"))
            Songbooks.make(db, "Picnic", listOf("Muse - Hysteria"))
            pages.render(db, setOf("Gig"))
        }
        val gig = File(library, "_songbooks/Gig/songbook.html")
        val made = gig.readText()
        gig.writeText("changed on a device")
        assertEquals(SongbookStats(rendered = 1), write { db -> pages.renderOwn(db) })
        assertEquals(made, gig.readText())
        assertFalse(File(library, "_songbooks/Picnic").exists())  // the computer's page, the mirror's, stands
        assertNull(database.read { db -> db.kvGet("songbook:Picnic") })
        // one gone: its files go, as render_songbooks' _remove_gone takes them
        write { db -> Songbooks.delete(db, "Gig") }
        assertEquals(SongbookStats(removed = 1), write { db -> pages.renderOwn(db) })
        assertFalse(gig.exists())
    }

    @Test fun eachSongPlaysInItsOwnVersionAsItPlaysNowAsRenderSongbooksUpgradesItFirst() {
        // own_versions' fixture: Hotel California kept by `key=B&capo=2`, made while caracole read its UG key "B"
        // as major; its sheet reads as minor now, so render_songbooks first rewrites the entry in the minor key
        // that plays it where it did (render.own_versions_upgraded)
        val record = Corpus.records("viewer/render.jsonl").first { it.extra["case"] == JsonPrimitive("own_versions") }
        write { db -> Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, library) }
        val render = PhoneRender(database, library, null, "0.1.0")
        write { db -> render.render(db, listOf(1L), null) }  // its sheet.cho, written and recorded
        val upgraded = database.read { db -> Overrides.read(db).version.getValue("eagles/hotel-california") }
        assertFalse(upgraded == "key=B&capo=2")
        write { db ->  // as before the upgrade: the entry as it was kept, never rewritten yet
            db.execute("UPDATE phone_overrides SET value = ? WHERE tbl = 'version' AND key = ?", "\"key=B&capo=2\"",
                       "eagles/hotel-california")
            db.kvDelete("keys:own_versions")
            Songbooks.make(db, "Gig", listOf("Eagles - Hotel California"))
        }
        val (asKept, asNow) = database.read { db ->
            val book = Songbooks.find(Songbooks.all(db), "Gig")!!
            listOf(Overrides.read(db), Overrides.read(db).let { it.copy(version = it.version + ("eagles/hotel-california" to upgraded)) })
                .map { SongbookPagesImpl.bookSongs(SongbookEntries.entries(db, library, it, book, rekey = false)) }
        }
        assertFalse(asKept == asNow, "the upgrade moves where the songbook plays it")
        assertEquals(SongbookStats(rendered = 1), write { db -> pages.render(db, null) })
        assertEquals(upgraded, database.read { db -> Overrides.read(db).version.getValue("eagles/hotel-california") })
        assertEquals(SongbookPage.build("Gig", asNow), File(library, "_songbooks/Gig/songbook.html").readText())
    }

    private companion object {
        const val NOW = "2026-11-03T12:00:00Z"
    }
}
