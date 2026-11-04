package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.OverridesReplay
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
 * The phone's overrides.toml read as overrides.load_overrides reads it: every field of Overrides from
 * `phone_overrides` (vectors/library/overrides_read.jsonl, each refusal's words too, and artist_url_entry), and what
 * no record shows: no row, a table the phone doesn't know, checks the caller leaves out.
 */
class OverridesReadTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }

    @After fun close() = database.close()

    private fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)

    private fun row(db: Db, table: String, key: String, written: String, value: String) =
        db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)", table, key, written, value)

    @Test fun everyFieldIsReadAsPythonReadsTheSameEntries() =
        Misses(OverridesReplay.READ).also { OverridesReplay.reads(it) }.assertNone()

    @Test fun noRowIsNoOverride() {
        val read = write { Overrides.read(it) }
        assertEquals(Overrides(), read)
        assertFalse(read.hasTable("match"))
    }

    @Test fun aTableIsThereWhileAnEntryIsInIt() {
        val read = write { db ->
            row(db, "transpose", "radiohead/creep", "Radiohead - Creep", "-2")
            Overrides.read(db)
        }
        assertEquals(setOf("transpose"), read.tables)
        assertTrue(read.hasTable("transpose"))
        assertFalse(read.hasTable("pin"))
        assertEquals(mapOf("radiohead/creep" to -2), read.transpose)
    }

    @Test fun aTableThePhoneDoesntKnowIsRefusedAsPythonRefusesOne() {
        val e = assertFailsWith<OverridesError> {
            write { db ->
                row(db, "zebra", "a/b", "A - B", "1")
                row(db, "spotify", "a/b", "A - B", "1")
                Overrides.read(db)
            }
        }
        assertEquals("unknown table(s): spotify, zebra", e.message)
    }

    @Test fun withoutTheViewersChecksAVersionAndAReadingAreTakenAsWritten() {
        // Every writer of the phone checked them: a caller with no viewer (:core's) reads them as they are.
        val read = write { db ->
            row(db, "version", "radiohead/creep", "Radiohead - Creep", "\"key=H\"")
            row(db, "harmonica", "a/b", "A - B", """{"harmonica-1.txt":"staff"}""")
            Overrides.read(db)
        }
        assertEquals(mapOf("radiohead/creep" to "key=H"), read.version)
        assertEquals(mapOf("a/b" to mapOf("harmonica-1.txt" to JsonPrimitive("staff"))), read.harmonica)
        // With them, as Python reads it.
        val e = assertFailsWith<OverridesError> {
            write { db -> Overrides.read(db, keyVersion = { throw IllegalArgumentException("key must be a key") }) }
        }
        assertEquals("[version] 'Radiohead - Creep': key must be a key", e.message)
    }

    @Test fun whatTheWritersWriteIsReadBack() {
        val read = write { db ->
            OverrideWriters.addMatch(db, "Radiohead - Creep", "Radiohead/Creep")
            OverrideWriters.addPin(db, "Radiohead - Creep", listOf("tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169?x=1"))
            OverrideWriters.addReject(db, "Radiohead - Creep", listOf("radiohead/karma-police"))
            OverrideWriters.addLacuerda(db, "Estopa - Como Camarón", "acordes.lacuerda.net/estopa/como_camaron-2.shtml")
            OverrideWriters.addHarptabs(db, "Billy Joel - Piano Man", "harptabs.com/tab/25/piano-man")
            OverrideWriters.addGametabs(db, "Yuzo Koshiro - Fillmore", "gametabs.net/tabs/actraiser/fillmore")
            OverrideWriters.addAlias(db, "Soda Stereo", "Soda-Stereo")
            OverrideWriters.addIgnore(db, "Nobody - Nothing")
            OverrideWriters.addVersion(db, "Radiohead - Creep", "#t=2") { null }
            OverrideWriters.addHarmonica(db, "A - B", "harmonica-1.txt", buildJsonObject { put("as", "signs") }) {}
            Overrides.read(db)
        }
        assertEquals(mapOf("radiohead/creep" to ("radiohead" to "creep")), read.match)
        assertEquals(mapOf("radiohead/creep" to listOf(4169L)), read.pin)
        assertEquals(listOf("https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"),
                     read.pinUrls["radiohead/creep"])
        assertEquals(setOf("radiohead" to "karma-police"), read.reject["radiohead/creep"])
        assertEquals(LaCuerdaPick("estopa", "como_camaron", 2), read.lacuerda["estopa/como-camaron"])
        assertEquals(HarpTabsPick(25, "piano-man"), read.harptabs["billy-joel/piano-man"])
        assertEquals(GameTabsPick("actraiser", "fillmore"), read.gametabs["yuzo-koshiro/fillmore"])
        assertEquals(mapOf("soda-stereo" to listOf("soda-stereo")), read.alias)
        assertEquals(setOf("nobody/nothing"), read.ignore)
        assertEquals(mapOf("radiohead/creep" to "t=2"), read.version)
        assertEquals(buildJsonObject { put("as", "signs") }, read.harmonica["a/b"]!!["harmonica-1.txt"])
    }

    @Test fun anArtistsPageIsFoundByAnyFormOfTheirName() {
        val read = write { db ->
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('artist_url', ?, ?, ?)",
                       "song-dongye", "Song Dongye (宋冬野)", "\"https://www.ultimate-guitar.com/artist/634073\"")
            Overrides.read(db)
        }
        val page = "https://www.ultimate-guitar.com/artist/634073"
        assertEquals("song-dongye" to page, read.artistUrlEntry(listOf("宋冬野")))
        assertEquals("song-dongye" to page, read.artistUrlEntry(listOf("", "song-dongye")))
        assertEquals(null, read.artistUrlEntry(listOf("radiohead")))
    }
}
