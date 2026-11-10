package io.github.danielhp95.caracole.viewer.progressions

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.testing.replays.VersionReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.progressions answers as progressions.py does: every record of vectors/viewer/progressions.jsonl
 * (VersionReplay), and tests/test_progressions.py's cases, by hand. */
class ProgressionsTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun everyRecordIsProgressionsPys() {
        val misses = Misses("progressions")
        VersionReplay.progressions(misses)
        misses.assertNone()
        assertTrue(misses.checked > 150, "only ${misses.checked} answers checked")
    }

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(folder.newFolder()).use { it.writeBlocking(block) }

    private fun sections(cho: String, key: String? = null): List<JsonObject> =
        Progressions.sheetProgressions(cho, key)!!.getValue("sections").jsonArray.map { it.jsonObject }

    private fun strings(xs: List<String>) = JsonArray(xs.map(::JsonPrimitive))

    @Test fun aSheetsSectionsAreReadAsNumeralsInTheKeyOfItsViewer() {
        val found = Progressions.sheetProgressions(CHO, null)!!
        assertEquals(JsonPrimitive("C major"), found["key"])
        val (verse, chorus, outro) = sections(CHO)
        assertEquals(JsonObject(linkedMapOf(
            "section" to JsonPrimitive("Verse"), "numerals" to strings(listOf("vi", "IV", "I", "V")),
            "repeats" to JsonPrimitive(2), "name" to JsonPrimitive("the pop progression"),
            "ending" to JsonPrimitive("half"), "key" to JsonPrimitive(POP), "contains" to JsonArray(emptyList()))), verse)
        assertEquals(JsonPrimitive(POP), chorus["key"])
        assertEquals(JsonPrimitive("I"), outro["key"])
        // its members in Python's order, as kv_set_json writes them
        assertTrue(PyJson.dumps(found).startsWith("{\"key\": \"C major\", \"sections\": [{\"section\": \"Verse\", \"numerals\""))
    }

    @Test fun theKeyGivenWinsAndASheetWithNoKeyHasOneEstimated() {
        assertEquals(JsonPrimitive("A minor"), Progressions.sheetProgressions(CHO, "Am")!!["key"])
        assertEquals(strings(listOf("i", "♭VI", "♭III", "♭VII")), sections(CHO, "Am")[0]["numerals"])
        val estimated = Progressions.sheetProgressions(CHO.replace("{key: C}\n", ""), null)!!["key"]!!.jsonPrimitive.content
        assertTrue(estimated in setOf("C major", "A minor"))
    }

    @Test fun aSheetWithNoHeadingsNoChordsItCanReadOrOnlyAChordLegend() {
        val only = sections("{title: X}\n[G]one [D]two\n[Em]three [C]four\n", "G").single()
        assertEquals(JsonNull, only["section"])
        assertEquals(JsonPrimitive(POP), only["key"])
        val verse = sections("{title: X}\nCadd9 (x32033)\n{comment: Verse}\n[N.C.]hey [G]one [N.C.]two [D]three\n", "G").single()
        assertEquals(strings(listOf("I", "V")), verse["numerals"])
        assertNull(Progressions.sheetProgressions("{title: X}\nwords alone\n", null))
        assertNull(Progressions.sheetProgressions("{title: X}\n{comment: Intro}\n[N.C.]hey\n", "G"))
    }

    @Test fun aProgressionTypedAsNumeralsInAnyRotationOrSpelling() {
        for (typed in listOf("vi IV I V", "vi–IV–I–V", "I V vi IV", "vi, IV, I, V", "  IV I V vi ")) {
            val wanted = Progressions.read(typed)!!
            assertEquals(POP, wanted.key, typed)
            assertEquals("the pop progression", wanted.name)
            assertEquals(setOf(POP, POP_MINOR), wanted.keys)
            assertEquals("I–V–vi–IV", wanted.label)
        }
        assertEquals("the double-plagal progression", Progressions.read("I bVII IV")!!.name)
        val unnamed = Progressions.read("I ii iii")!!
        assertEquals(Triple(setOf("I ii iii"), null, "I–ii–iii"), Triple(unnamed.keys, unnamed.name, unnamed.label))
        val twoFive = Progressions.read("ii V I")!!
        assertEquals(Triple("I ii V", "ii–V–I", "ii–V–I"), Triple(twoFive.key, twoFive.name, twoFive.label))
        assertEquals("the ragtime progression", Progressions.read("III7 VI7 II7 V7")!!.name)
        assertNull(Progressions.read("i bIII bVII IV")!!.name)
        assertEquals("the Aeolian shuttle", Progressions.read("i VII VI VII")!!.name)
    }

    @Test fun aProgressionNamedFromTheCatalogue() {
        val andalusian = Progressions.read("andalusian")!!
        assertEquals("the Andalusian cadence", andalusian.name)
        assertEquals(setOf(ANDALUSIAN, "IV V/vi vi V"), andalusian.keys)
        assertEquals(andalusian.keys, Progressions.read("Andalusian Cadence")!!.keys)
        val blues = Progressions.read("blues")!!
        assertEquals(Triple(5, "the 12-bar blues", "the 12-bar blues or the 8-bar blues"),
                     Triple(blues.keys.size, blues.name, blues.label))
        assertEquals("the minor ii–V–i", Progressions.read("minor ii V i")!!.name)
        assertEquals("the pop progression", Progressions.read("pop progression")!!.name)
    }

    @Test fun wordsThatAreNoProgression() {
        for (text in listOf("", "hello world", "I", "I I I", "V", "vi IV hello", "pop", "progression", "the cadence",
                            "Wonderwall", "via", "The Road", "the bar", "a road", "minor", "Minor", "the minor", "creep",
                            "Creep")) {
            assertNull(Progressions.read(text), text)
        }
    }

    @Test fun theCatalogueByKeyAndAKeysLabel() {
        val names = Progressions.catalogue()
        assertEquals("the pop progression", names[POP])
        assertEquals("the pop progression", names[POP_MINOR])
        assertEquals("the Andalusian cadence", names[ANDALUSIAN])
        assertEquals("I–V–vi–IV", Progressions.label("I V vi IV"))
    }

    @Test fun aRecordIsWrittenOnlyWhenItChangedAndASheetThatPlaysNothingLeavesNone() = db { db ->
        val key = "${Progressions.KV}5"
        assertFalse(Progressions.anyRecorded(db))
        Progressions.record(db, 5, CHO, null)
        val text = db.kvGet(key)!!
        assertEquals(PyJson.dumps(Progressions.sheetProgressions(CHO, null)!!), text)
        assertTrue(Progressions.anyRecorded(db))
        // the same record, written otherwise (as json.loads reads it, it is the same): left as it is
        val spaced = text.replace(", ", ",  ")
        db.kvSet(key, spaced)
        Progressions.record(db, 5, CHO, null)
        assertEquals(spaced, db.kvGet(key))
        Progressions.record(db, 5, CHO, "Am")
        assertEquals(PyJson.dumps(Progressions.sheetProgressions(CHO, "Am")!!), db.kvGet(key))
        Progressions.record(db, 5, "{title: X}\nwords alone\n", null)
        assertNull(db.kvGet(key))
        // a record there that is no JSON is kv_get_json's error
        db.kvSet(key, "not json")
        assertFailsWith<PyJson.DecodeError> { Progressions.record(db, 5, CHO, null) }
        Progressions.forget(db, 5)
        assertNull(db.kvGet(key))
    }

    @Test fun onlyASectionOfTwoChordsOrMoreIsAProgressionForTheLibrary() = db { db ->
        db.kvSet("${Progressions.KV}3", PyJson.dumps(Progressions.sheetProgressions(CHO, null)!!))
        val plays = Progressions.library(db)
        assertEquals(setOf(3L), plays.keys)
        assertEquals(JsonArray(listOf(JsonObject(mapOf("key" to JsonPrimitive(POP), "plays" to JsonPrimitive("vi–IV–I–V"))))),
                     plays[3L])
    }

    @Test fun aRecordADeviceOrAnOlderCaracoleLeftOddIsReadAsNone() = db { db ->
        for (odd in listOf("[]", "\"x\"", "{\"sections\": \"x\"}", "{\"sections\": [1, {\"key\": 2}, {\"numerals\": [\"I\"]}]}")) {
            db.kvSet("${Progressions.KV}1", odd)
            assertEquals(emptyMap(), Progressions.library(db), odd)
        }
    }

    private companion object {
        const val POP = "I V vi IV"
        const val POP_MINOR = "i ♭VI ♭III ♭VII"
        const val ANDALUSIAN = "V i ♭VII ♭VI"
        const val CHO = "{title: Synthetic Song}\n{artist: Placeholder Band}\n{key: C}\n{comment: Verse}\n" +
            "[Am]Words to [F]sing, [C]only for the [G]test\n[Am]more [F]words, [C]still a [G]test\n" +
            "{comment: Chorus}\n[C]la la [G]la, [Am]la la [F]la\n{comment: Outro}\n[C]end\n"
    }
}
