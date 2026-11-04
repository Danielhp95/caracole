package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** A kept file's number as inbox.py gives it (vectors/library/writes.jsonl), and numbers past a Long. */
class NumberingTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun numbersAreInboxPysNumbers() {
        val misses = Misses("library-writes: inbox.py's numbering")
        LibraryWritesReplay.replay(misses) { it.startsWith("caracole.inbox.") }
        misses.assertNone()
    }

    @Test fun aNumberPastALongTakesNothingBelowIt() {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "library/writes_fixture_library.jsonl", library)
                val wall = Songs.byKey(db, "oasis/wonderwall")!!
                val folder = LibraryStore(library).folderOf(wall).apply { mkdirs() }
                for (name in listOf("guitar-1.gp5", "guitar-99999999999999999999999.gp5", "gametab-0.txt",
                                    "harmonica-१.txt", "score-1.MID", "score-2.mid")) {
                    File(folder, name).writeText(name)
                }
                val lib = LibraryStore(library)
                assertEquals(2, Numbering.guitar(db, lib, wall))
                assertEquals(1, Numbering.gametab(db, lib, wall))
                assertEquals(2, Numbering.harmonica(db, lib, wall)) // a Devanagari 1
                assertEquals(3, Numbering.score(db, lib, wall, ".mid"))
            }
        }
    }

    @Test fun aNumberPastPythonsDigitsIsItsValueErrorInItsWords() {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "library/writes_fixture_library.jsonl", library)
                val wall = Songs.byKey(db, "oasis/wonderwall")!!
                val version = db.one("SELECT id FROM versions ORDER BY id LIMIT 1") { it.long(0) }!!
                // A name no folder can hold, kept in a row: 4301 digits, the first a Devanagari 1 (two of Python's
                // digits counted as one each, as int() counts them).
                val name = "guitar-१" + "1".repeat(4300) + ".gp5"
                db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                               "VALUES (?, ?, ?, ?, ?, 1, ?)", version, wall.id, name, "Oasis/Wonderwall/x", "0",
                           "2026-11-03T12:00:00Z")
                val raised = assertFailsWith<IllegalArgumentException> { Numbering.guitar(db, LibraryStore(library), wall) }
                assertEquals("Exceeds the limit (4300 digits) for integer string conversion: value has 4301 digits; " +
                                 "use sys.set_int_max_str_digits() to increase the limit", raised.message)
            }
        }
    }
}
