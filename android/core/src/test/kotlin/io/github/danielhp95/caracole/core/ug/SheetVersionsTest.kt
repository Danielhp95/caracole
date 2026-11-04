package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.RankReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * sheet_versions.py as Python answers it over the fixture library (vectors/sites/ug_sheet_versions.jsonl), and what
 * tests/test_sheet_versions.py says by hand: the rank order, the pages, many songs read as each, the kv lists.
 */
class SheetVersionsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val policy = RankPolicy()

    @Test fun sheetVersionsAreSheetVersionsPys() {
        val misses = Misses("rank: sheet_versions.py")
        RankReplay.sheetVersions(misses)
        misses.assertNone()
    }

    private fun <T> library(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { database ->
        database.writeBlocking { db ->
            Fixtures.load(db, RankReplay.FIXTURE)
            block(db)
        }
    }

    private fun id(db: Db, key: String): Long = Songs.byKey(db, key)!!.id

    @Test fun theListIsInRankOrderWithTheOneAndTheKeptPagesNamed() {
        library { db ->
            val listed = SheetVersions.inLibrary(db, id(db, "oasis/wonderwall"), policy)
            assertEquals(listOf("3", "2", "8", "1", "40"), listed.take(5).map { it.tabId })  // complete first
            assertEquals((1..listed.size).toList(), listed.map { it.rank })
            val one = listed.single { it.chosen }
            assertEquals("2" to "sheet.html", one.tabId to one.page)
            assertEquals("version-1.html", listed.single { it.tabId == "1" }.page)
            val gone = listed.last()
            assertTrue(gone.gone && gone.kept && gone.page == "version-7.html")  // kept until the next fetch drops it
            assertTrue(listed.none { it.tabId == "lc" || it.tabId == "900" })  // another site's, a text tab
        }
    }

    @Test fun theTabbersNoteIsFoldedAndCut() {
        library { db ->
            val notes = SheetVersions.inLibrary(db, id(db, "oasis/wonderwall"), policy).associate { it.tabId to it.note }
            assertEquals("Capo 2 slowly", notes["1"])
            assertEquals("x".repeat(200), notes["3"])
            assertEquals("a b c d", notes["8"])  // Python's whitespace: an ideographic space, NBSP, U+2028
            assertNull(notes["4"])  // a note that is no text
            assertNull(notes["5"])  // whitespace alone
            assertNull(notes["30"])  // a raw SQLite can't read as JSON (NaN)
            assertEquals(200, notes["9"]!!.codePointCount(0, notes["9"]!!.length))  // code points, not UTF-16 units
        }
    }

    @Test fun manySongsReadAsEachOne() {
        library { db ->
            val ids = db.query("SELECT id FROM songs ORDER BY id") { it.long(0)!! }
            val each = ids.associateWith { SheetVersions.inLibrary(db, it, policy) }.filterValues { it.isNotEmpty() }
            val all = SheetVersions.inLibraryOf(db, ids.reversed() + 9999L, policy)
            assertEquals(each, all)
            assertEquals(all.keys.sorted(), all.keys.toList())
            assertEquals(emptyMap(), SheetVersions.inLibraryOf(db, emptyList(), policy))
        }
    }

    @Test fun aUkuleleSheetListsTheUkuleleVersions() {
        library { db ->
            val riptide = id(db, "vance-joy/riptide")
            assertEquals("ukulele", SheetVersions.sheetKind(db, riptide))
            assertEquals("301" to emptyList<String>(), SheetVersions.libraryState(db, riptide))
            assertEquals(listOf("301", "302"), SheetVersions.inLibrary(db, riptide, policy).map { it.tabId })
            val georgia = id(db, "vance-joy/georgia")
            val listed = SheetVersions.inLibrary(db, georgia, policy)
            assertEquals(listOf("201", "202"), listed.map { it.tabId })
            assertEquals(emptyList(), SheetVersions.mayKeep(db, georgia, listed, emptySet()))  // a keep keeps chords
        }
    }

    @Test fun mayKeepLeavesOutTheKeptTheBlockedTheUnkeepableAndWhatRobotsCloses() {
        library { db ->
            val wall = id(db, "oasis/wonderwall")
            val listed = SheetVersions.inLibrary(db, wall, policy)
            assertEquals(listOf("3", "4", "30", "9"), SheetVersions.mayKeep(db, wall, listed, emptySet()).map { it.tabId })
            assertEquals(listOf("3", "30", "9"), SheetVersions.mayKeep(db, wall, listed, setOf(4L)).map { it.tabId })
        }
    }

    @Test fun mayKeepReadsATabIdAsANumberOnlyForAVersionStillInTheRunning() {
        library { db ->
            val wall = id(db, "oasis/wonderwall")
            val listed = SheetVersions.inLibrary(db, wall, policy)
            // Python's `not (kept or chosen or gone) and int(tab_id) not in block …` never calls int() on these
            val out = listed.map { if (it.kept || it.chosen || it.gone) it.copy(tabId = "no number") else it }
            assertEquals(listOf("3", "4", "30", "9"), SheetVersions.mayKeep(db, wall, out, setOf(99L)).map { it.tabId })
            // but on one still in the running it does, and its ValueError is Kotlin's IllegalArgumentException
            val running = listed.map { if (it.tabId == "4") it.copy(tabId = "four") else it }
            assertFailsWith<IllegalArgumentException> { SheetVersions.mayKeep(db, wall, running, emptySet()) }
        }
    }

    @Test fun theKvListsAreNotedOnceAsPythonWritesThem() {
        library { db ->
            val wall = id(db, "oasis/wonderwall")
            assertEquals(listOf("3", "10"), SheetVersions.keptByYou(db, wall))
            SheetVersions.noteKeptByYou(db, wall, 10L)
            SheetVersions.noteKeptByYou(db, wall, "4")
            assertEquals("[\"3\", \"10\", \"4\"]", db.kvGet(SheetVersions.yoursKey(wall)))
            val soda = id(db, "soda-stereo/de-musica-ligera")
            SheetVersions.noteUnkeepable(db, soda, 11L)
            SheetVersions.noteUnkeepable(db, soda, "11")
            assertEquals(listOf("11"), SheetVersions.unkeepable(db, soda))
        }
    }

    @Test fun thePagesJsonKeepsPythonsOrderAndFloats() {
        library { db ->
            val listed = SheetVersions.inLibrary(db, id(db, "oasis/wonderwall"), policy)
            val text = PyJson.dumps(SheetVersions.asData(listed, 13))
            assertTrue(text.startsWith("{\"total\": 13, \"list\": [{\"tab\": \"3\", \"number\": 3, \"rating\": 4.8, " +
                                           "\"votes\": 300, \"label\": null, \"note\": \"xxx"), text.take(200))
        }
    }

    @Test fun namesRoundTrip() {
        assertEquals(Triple("version-39144.txt", "version-39144.json", "version-39144.html"),
                     SheetVersions.versionNames("39144"))
        assertEquals("39144", SheetVersions.tabOf("version-39144.json"))
        for (name in listOf("sheet.txt", "version-.txt", "version-12.pdf", "version-1a.txt", "version-12.txt.bak",
                            "version-١٢.txt")) {
            assertNull(SheetVersions.tabOf(name), name)
        }
    }
}
