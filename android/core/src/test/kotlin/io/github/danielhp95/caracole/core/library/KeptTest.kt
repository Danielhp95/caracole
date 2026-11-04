package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Kept files as library.py keeps them: keep_file, kept_already, kept_files, keeper_of, holds, drop_file and
 * write_atomic against Python's records (vectors/library/writes.jsonl), and what no record can show: the mode a file
 * is written with, links, a time that is none.
 */
class KeptTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun keptFilesAreWrittenAsLibraryPyWritesThem() {
        val misses = Misses("library-writes: library.py")
        LibraryWritesReplay.replay(misses) { it.startsWith("caracole.library.") }
        misses.assertNone()
    }

    private fun <T> library(block: (Db, LibraryStore) -> T): T {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "library/writes_fixture_library.jsonl", library)
                block(db, LibraryStore(library))
            }
        }
    }

    private fun Db.song(key: String) = Songs.byKey(this, key)!!

    private fun Db.version(provider: String, tab: String) =
        one("SELECT id FROM versions WHERE provider = ? AND tab_id = ?", provider, tab) { it.long(0)!! }!!

    @Test fun aFileIsWrittenWithTheProcesssOwnModeNeverMkstempsAndNoTemporaryIsLeft() {
        val dir = tmp.newFolder().toPath()
        val plain = Files.createFile(dir.resolve("plain"))
        val sha = Kept.writeAtomic(dir.resolve("a/b/kept.txt"), "kept".toByteArray())
        assertEquals(Canonical.sha256Hex("kept".toByteArray()), sha)
        assertEquals(Files.getPosixFilePermissions(plain), Files.getPosixFilePermissions(dir.resolve("a/b/kept.txt")))
        assertEquals(listOf("kept.txt"), Files.list(dir.resolve("a/b")).use { s -> s.map { it.fileName.toString() }.toArray().toList() })
    }

    @Test fun aLinkAtThePathIsReplacedNeverWrittenThrough() {
        val dir = tmp.newFolder().toPath()
        val target = Files.write(dir.resolve("private"), "secret".toByteArray())
        val link = Files.createSymbolicLink(dir.resolve("kept.txt"), target)
        Kept.writeAtomic(link, "kept".toByteArray())
        assertEquals("secret", Files.readString(target))
        assertFalse(Files.isSymbolicLink(link))
        assertEquals("kept", Files.readString(link))
    }

    @Test fun aLinkHoldsNothingThoughItsTargetHoldsTheBytes() {
        val dir = tmp.newFolder().toPath()
        val target = Files.write(dir.resolve("file"), "bytes".toByteArray())
        val link = Files.createSymbolicLink(dir.resolve("link"), target)
        val sha = Kept.writeAtomic(dir.resolve("copy"), "bytes".toByteArray())
        assertTrue(Kept.holds(target, sha, 5))
        assertFalse(Kept.holds(link, sha))
        assertFalse(Kept.holds(dir, sha))
    }

    @Test fun aKeptFileALinkReplacedIsNoLongerKept() {
        library { db, lib ->
            val creep = db.song("radiohead/creep")
            val sheet = db.version("ug", "101")
            assertTrue(Kept.keptAlready(db, lib, creep, sheet, "sheet.txt", "[Am]Creep".toByteArray()))
            val path = lib.libraryDir.toPath().resolve("Radiohead/Creep/sheet.txt")
            val elsewhere = Files.write(lib.libraryDir.toPath().resolve("elsewhere"), "[Am]Creep".toByteArray())
            Files.delete(path)
            Files.createSymbolicLink(path, elsewhere)
            assertFalse(Kept.keptAlready(db, lib, creep, sheet, "sheet.txt", "[Am]Creep".toByteArray()))
            assertFalse(Kept.holds(db, lib, creep, "sheet.txt", Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" }.sha256))
        }
    }

    @Test fun theSongsOwnHoldsReadsItsRowsPath() {
        library { db, lib ->
            val creep = db.song("radiohead/creep")
            val kept = Kept.keptFiles(db, creep.id).first { it.name == "tab.txt" }
            assertTrue(Kept.holds(db, lib, creep, "tab.txt", kept.sha256))
            assertFalse(Kept.holds(db, lib, creep, "notes.txt", kept.sha256)) // in the folder, kept by no row
        }
    }

    @Test fun aTimeThatIsNoneWritesNothing() {
        library { db, lib ->
            val wall = db.song("oasis/wonderwall")
            assertFailsWith<IllegalArgumentException> {
                Kept.keepFile(db, lib, wall, db.version("ug", "101"), "sheet.txt", "x".toByteArray(), 1, "soon")
            }
            assertFalse(Files.exists(lib.folderOf(wall).toPath(), LinkOption.NOFOLLOW_LINKS))
            assertEquals(emptyList(), Kept.keptFiles(db, wall.id))
        }
    }

    @Test fun sharedFolderNamesBothSongsAndWritesNothing() {
        library { db, lib ->
            val songs = Songs.list(db).filter { it.artist == "Joaquín Rodrigo" }.sortedBy { it.id }
            val (one, two) = songs
            val e = assertFailsWith<SharedFolder> {
                Kept.keepFile(db, lib, two, db.version("gtptabs", "8"), "sheet.txt", "B's".toByteArray(), 1,
                              "2026-11-03T12:00:00Z")
            }
            assertEquals(Triple(two.id, one.id, "sheet.txt"), Triple(e.song.id, e.other.id, e.name))
            assertEquals("[Em]Adagio", File(lib.folderOf(one), "sheet.txt").readText())
            assertEquals(one.id, Kept.keeperOf(db, lib, two, "sheet.txt")?.id)
        }
    }

    @Test fun aKeptFileIsStampedWithTheTimeItIsGivenAsCaracoleStoresOne() {
        library { db, lib ->
            val wall = db.song("oasis/wonderwall")
            assertTrue(Kept.keepFile(db, lib, wall, db.version("ug", "101"), "sheet.txt", "x".toByteArray(), 1,
                                     "2026-11-03T14:00:00+02:00"))
            assertEquals("2026-11-03T12:00:00Z",
                         db.one("SELECT created_at FROM files WHERE song_id = ?", wall.id) { it.text(0) })
        }
    }
}
