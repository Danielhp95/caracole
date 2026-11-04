package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.OverridesReplay
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * overrides.py's add_* writers on the phone: `phone_overrides` after each as overrides.song_entries reads
 * overrides.toml after the same add (vectors/library/overrides_writes.jsonl, refusals' words too), and what no record
 * shows: a refusal inside a caller's write leaves the rest of it, the checks a writer is given, the store's own reading.
 */
class OverrideWritersTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }

    @After fun close() = database.close()

    private fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)

    private fun rows(): List<List<String?>> = database.read { db ->
        db.query("SELECT tbl, key, written, value FROM phone_overrides ORDER BY tbl, key") {
            listOf(it.text(0), it.text(1), it.text(2), it.text(3))
        }
    }

    @Test fun eachWriterLeavesTheRowsAsPythonsSongEntries() =
        Misses(OverridesReplay.WRITES).also { OverridesReplay.writes(it) }.assertNone()

    @Test fun aRefusalWritesNothingAndLeavesTheCallersOtherWrites() {
        write { db ->
            OverrideWriters.addIgnore(db, "Nobody - Nothing")
            assertFailsWith<OverridesError> { OverrideWriters.addPin(db, "Radiohead - Creep", listOf("85053", "nope")) }
            assertFailsWith<IllegalArgumentException> { OverrideWriters.addPin(db, "Radiohead - Creep", listOf("²")) }
        }
        assertEquals(listOf(listOf("ignore", "nobody/nothing", "Nobody - Nothing", "true")), rows())
    }

    @Test fun aVersionKeptByItsKeyIsCheckedAsGivenWithoutItsHash() {
        val checked = mutableListOf<String>()
        write { db ->
            OverrideWriters.addVersion(db, "Radiohead - Creep", "  #key=Gm&capo=0 ") { checked += it }
            OverrideWriters.addVersion(db, "Radiohead - Creep", "t=2") { checked += it }  // no key: no check
        }
        assertEquals(listOf("key=Gm&capo=0"), checked)
        assertEquals(listOf(listOf("version", "radiohead/creep", "Radiohead - Creep", "\"t=2\"")), rows())
        val e = assertFailsWith<OverridesError> {
            write { db ->
                OverrideWriters.addVersion(db, "Blur - Song 2", "key=H") {
                    throw IllegalArgumentException("key must be a key as a sheet names it")
                }
            }
        }
        assertEquals("[version] 'Blur - Song 2': key must be a key as a sheet names it", e.message)
    }

    /**
     * add_version drops one mark and writes the rest, which overrides.toml's next load reads again: the phone keeps
     * what that load reads, so a row reads as itself. The vectors hold `##t=2`; Python gives no record of these, as
     * its add_version writes a file its own load reads otherwise (`###t=2`: `#t=2`, which put_song_entries refuses)
     * or refuses whole (`##key=H`, whose key add_version never checks).
     */
    @Test fun aVersionIsKeptAsTheComputerReadsWhatAddVersionWrites() {
        val checked = mutableListOf<String>()
        write { db ->
            OverrideWriters.addVersion(db, "Radiohead - Creep", "###t=2") { checked += it }
            OverrideWriters.addVersion(db, "Blur - Song 2", " ##key=Gm&capo=0") { checked += it }
        }
        assertEquals(listOf("key=Gm&capo=0"), checked)  // the key the file's load would check, once
        assertEquals(listOf(listOf("version", "blur/song-2", "Blur - Song 2", "\"key=Gm&capo=0\""),
                            listOf("version", "radiohead/creep", "Radiohead - Creep", "\"t=2\"")), rows())
        val before = rows()
        val e = assertFailsWith<OverridesError> {
            write { db ->
                OverrideWriters.addVersion(db, "Blur - Song 2", "##key=H") {
                    throw IllegalArgumentException("key must be a key as a sheet names it")
                }
            }
        }
        assertEquals("[version] 'Blur - Song 2': key must be a key as a sheet names it", e.message)
        assertEquals(before, rows())
    }

    @Test fun aKeyCheckThatAnswersFalseIsAMistakeThatWritesNothing() {
        assertFailsWith<IllegalStateException> {
            write { db -> OverrideWriters.addVersion(db, "Blur - Song 2", "key=H") { false } }
        }
        assertEquals(emptyList(), rows())
        write { db -> OverrideWriters.addVersion(db, "Blur - Song 2", "key=G") { true } }  // any other answer passes
        assertEquals(listOf(listOf("version", "blur/song-2", "Blur - Song 2", "\"key=G\"")), rows())
    }

    @Test fun aHarmonicaReadingIsCheckedAndTheEntryGoesWithItsLastTab() {
        val checked = mutableListOf<JsonElement>()
        val signs = buildJsonObject { put("as", "signs"); put("*", "bend") }
        write { db ->
            OverrideWriters.addHarmonica(db, "A - B", "harmonica-1.txt", signs) { checked += it }
            OverrideWriters.addHarmonica(db, "a - b", "harmonica-2.txt", JsonPrimitive("letters")) { checked += it }
        }
        assertEquals(listOf<JsonElement>(signs, JsonPrimitive("letters")), checked)
        assertEquals(listOf(listOf("harmonica", "a/b", "A - B",
                                   """{"harmonica-1.txt":{"*":"bend","as":"signs"},"harmonica-2.txt":"letters"}""")),
                     rows())
        write { db ->
            OverrideWriters.addHarmonica(db, "A - B", "harmonica-1.txt", null) { error("no check for a tab taken out") }
            OverrideWriters.addHarmonica(db, "A - B", "harmonica-2.txt", null) { error("no check for a tab taken out") }
        }
        assertEquals(emptyList(), rows())
    }

    @Test fun aPinTakenOutIsFoundByItsTabWhateverItsAddress() {
        write { db ->
            OverrideWriters.addPin(db, "Radiohead - Creep",
                                   listOf("4169", "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4170"))
        }
        assertTrue(write { db -> OverrideWriters.removePin(db, "radiohead - creep", setOf(4170L)) })
        assertEquals(listOf(listOf("pin", "radiohead/creep", "Radiohead - Creep",
                                   "[\"https://tabs.ultimate-guitar.com/tab/4169\"]")), rows())
        assertFalse(write { db -> OverrideWriters.removePin(db, "Radiohead - Creep", setOf(1L)) })
        assertTrue(write { db -> OverrideWriters.removePin(db, "Radiohead - Creep", null) })
        assertEquals(emptyList(), rows())
        assertFalse(write { db -> OverrideWriters.removePin(db, "Radiohead - Creep", null) })
    }

    @Test fun theStoresOwnReadingIsTheWritersValue() {
        write { db ->
            OverrideWriters.addReject(db, "Radiohead - Creep", listOf("Radiohead/Karma-Police", "/x", "𠀀/y"))
            OverrideWriters.addMatch(db, "Radiohead - Creep", "radiohead/creep")
        }
        val entries = database.read { OverridesStore.songEntries(it, "radiohead/creep") }
        assertEquals(JsonPrimitive("radiohead/creep"), entries["match"])
        // In code-point order: U+E000 before U+20000, which UTF-16's order puts first.
        assertEquals(JsonArray(listOf("radiohead/karma-police", "\uE000/x", "\uD840\uDC00/y").map { JsonPrimitive(it) }),
                     entries["reject"])
        assertEquals(setOf("match", "reject"), entries.keys)
    }
}
