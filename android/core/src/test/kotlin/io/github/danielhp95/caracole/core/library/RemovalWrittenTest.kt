package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.internal.Removal
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * A removal on the phone takes the pages the phone wrote for the song, by their records (kv `render:files:<id>`,
 * render.py's `{name: {"sha256", "size"}}` with the unit digest each was made at): the phone makes no PDF, so no
 * render record names its sheet's page or .cho, and only those records say they are caracole's. A record that isn't
 * one, or a page no record names, stays as removal.py leaves any file caracole didn't write.
 */
class RemovalWrittenTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun <T> phone(block: (Db, LibraryStore) -> T): T {
        val dir = tmp.newFolder()
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> block(db, LibraryStore(File(dir, "library"))) }
        }
    }

    private fun keep(db: Db, store: LibraryStore, song: SongRow, name: String, text: String) {
        db.execute("INSERT OR IGNORE INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                   "VALUES ('inbox', ?, ?, 'sheet', 'chords', '', ?)", name, song.id, NOW)
        val version = db.one("SELECT id FROM versions WHERE song_id = ? AND tab_id = ?", song.id, name) { it.long(0)!! }!!
        Kept.keepFile(db, store, song, version, name, text.toByteArray(), 0, NOW)
    }

    /** A page the phone wrote beside the song's files, and its record as WrittenPages notes one. */
    private fun write(db: Db, store: LibraryStore, song: SongRow, name: String, text: String) {
        val bytes = text.toByteArray()
        File(store.folderOf(song), name).apply { parentFile.mkdirs() }.writeBytes(bytes)
        val key = "render:files:${song.id}"
        val record = db.kvGet(key)?.let { Canonical.parse(it) as JsonObject }.orEmpty()
        db.kvSetJson(key, JsonObject(record + (name to entry(bytes))))
    }

    private fun entry(bytes: ByteArray) = JsonObject(mapOf(
        "sha256" to JsonPrimitive(Canonical.sha256Hex(bytes)),
        "size" to JsonPrimitive(bytes.size),
        "unit" to JsonPrimitive("a digest"),
    ))

    private fun names(folder: File): List<String> = folder.list()?.sorted().orEmpty()

    @Test fun thePagesThePhoneWroteGoByTheirRecords() {
        phone { db, store ->
            val song = store.add(db, "Soda Stereo", "De Música Ligera", now = NOW)
            keep(db, store, song, "harmonica-1.txt", "4 -4 5")
            // Pages written while the song kept a sheet, which it keeps no longer: no kept sheet names them.
            for (name in listOf("sheet.html", "sheet.cho", "sheet (auto).html", "sheet (auto).cho", "version-39144.html",
                                "harmonica-1.html")) {
                write(db, store, song, name, "<!doctype html>$name")
            }
            val folder = store.folderOf(song)
            File(folder, "notes.html").writeText("mine")
            val plan = Removal.plan(db, store.libraryDir, song)
            assertEquals(listOf("harmonica-1.html", "harmonica-1.txt", "info.json", "sheet (auto).cho",
                                "sheet (auto).html", "sheet.cho", "sheet.html", "version-39144.html")
                             .filter { File(folder, it).exists() }.sortedWith(Canonical.KEY_ORDER), plan.delete)
            assertEquals(listOf("notes.html" to "caracole didn't write it"), plan.keep)
            val done = Removal.remove(db, store.libraryDir, plan, NOW)
            assertEquals(plan.delete, done.deleted.sortedWith(Canonical.KEY_ORDER))
            assertEquals(listOf("notes.html"), names(folder), "a page no record names stays")
            assertFalse(done.folderGone)
            assertEquals(null, db.kvGet("render:files:${song.id}"), "the records go with the song")
        }
    }

    @Test fun aRecordThatIsntOneMakesNoFileCaracoles() {
        phone { db, store ->
            val song = store.add(db, "Soda Stereo", "De Música Ligera", now = NOW)
            keep(db, store, song, "tab.txt", "e|--0--|")
            val folder = store.folderOf(song)
            for (name in listOf("sheet.html", "sheet.cho", "sheet (auto).html", "page.html")) {
                File(folder, name).writeText("mine")
            }
            db.kvSet("render:files:${song.id}",
                     """{"sheet.html": "x", "sheet.cho": {"sha256": 1, "size": 2}, "sheet (auto).html": """ +
                         """{"sha256": "ab", "size": 2.0}, "page.html": {"sha256": "ab", "size": true}}""")
            val plan = Removal.plan(db, store.libraryDir, song)
            assertEquals(listOf("info.json", "tab.txt").filter { File(folder, it).exists() }, plan.delete)
            Removal.remove(db, store.libraryDir, plan, NOW)
            assertEquals(listOf("page.html", "sheet (auto).html", "sheet.cho", "sheet.html"), names(folder))
        }
    }

    @Test fun aFolderTwoSongsShareKeepsWhatTheOtherMayHaveWritten() {
        phone { db, store ->
            val song = store.add(db, "Soda Stereo", "De Música Ligera", now = NOW)
            // Another song of the same names under another key (two spellings the folder's names make one).
            db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                       "VALUES ('soda stereo|de musica ligera (2)', 'Soda Stereo', 'De Música Ligera', " +
                       "'[\"Soda Stereo\"]', ?, ?, ?)", LATER, LATER, LATER)
            val other = Songs.byKey(db, "soda stereo|de musica ligera (2)")!!
            assertEquals(store.folderOf(song), store.folderOf(other), "their names make one folder")
            keep(db, store, song, "tab.txt", "e|--0--|")
            write(db, store, song, "sheet.html", "<!doctype html>the phone's")
            val plan = Removal.plan(db, store.libraryDir, song)
            assertEquals(listOf("tab.txt"), plan.delete)
            Removal.remove(db, store.libraryDir, plan, NOW)
            assertTrue(File(store.folderOf(other), "sheet.html").isFile)
        }
    }

    @Test fun aTakeThatMovesTheSongsFolderTakesThePhonesPagesWithIt() {
        phone { db, store ->
            val song = store.add(db, "Soda Stereo", "De Música Ligera", now = NOW)
            keep(db, store, song, "tab.txt", "e|--0--|")
            write(db, store, song, "sheet.html", "<!doctype html>the phone's")
            assertEquals(listOf("sheet.html", "tab.txt"), Removal.caracolesFiles(db, store.libraryDir, song))
        }
    }

    private companion object {
        const val NOW = "2026-11-01T00:00:00Z"
        const val LATER = "2026-11-02T00:00:00Z"
    }
}
