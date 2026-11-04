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
}
