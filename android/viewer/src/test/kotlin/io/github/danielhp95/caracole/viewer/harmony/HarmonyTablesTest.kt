package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonyReplay
import io.github.danielhp95.caracole.viewer.testing.replays.ShapesReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** viewer.harmony.HarmonyTables answers as viewer/harmony_tables.py: every record of vectors/viewer/harmony_tables.jsonl
 * (HarmonyReplay), and tests/test_viewer_numerals.py's table cases, by hand, on its sheets' chords and places. */
class HarmonyTablesTest {
    @Test fun everyRecordIsHarmonyTablesPys() {
        val misses = Misses("harmony tables")
        HarmonyReplay.tables(misses)
        misses.assertNone()
    }

    // test_viewer_numerals.py's IN_C: [C][G][Am][F] twice, then [D][G] [D][C] [Bb][F][C] in its bridge.
    private val inC = listOf("C", "G", "Am", "F", "D", "Bb")
    private val inCPlaces = listOf(0 to 0, 1 to 0, 2 to 0, 3 to 0, 0 to 0, 1 to 0, 2 to 0, 3 to 0, 4 to 1, 1 to 1, 4 to 1,
                                   0 to 1, 5 to 1, 3 to 1, 0 to 1)
    private val c = Key(0, "ionian")

    private fun tables(names: List<String>, key: Key?, places: List<Pair<Int, Int>>): JsonObject {
        val chords = names.map { Theory.parseChord(it, strict = false) }
        if (key == null) return HarmonyTables.tables(chords, null, places, emptyMap(), emptyMap())
        val (_, mapped, alts) = ShapesReplay.mappedAndAlts(names, key)
        return HarmonyTables.tables(chords, key, places, mapped, alts)
    }

    /** A text of the tables on the transposition [s], as viewer.js reads it. */
    private fun textOn(text: JsonElement, key: Key, s: Int): String = when (text) {
        is JsonPrimitive -> text.content
        is JsonObject -> text.getValue("by").jsonArray[s].jsonPrimitive.content
        else -> HarmonyTables.fill(text.jsonArray.map { p -> p.jsonPrimitive.let { if (it.isString) it.content else it.int } },
                                   Theory.spelling(Key(Math.floorMod(key.tonic + s, 12), key.mode)), s)
    }

    private fun JsonObject.mode(member: String, mode: String = "ionian"): JsonArray = getValue(member).jsonObject.getValue(mode).jsonArray

    @Test fun cMajorsChordsAreNumberedAgainstC() {
        val data = tables(inC, c, inCPlaces)
        assertEquals(listOf("I", "V", "vi", "IV", "V/V", "♭VII"), data.mode("numerals").take(6).map { it.jsonArray[0].jsonPrimitive.content })
        assertEquals(listOf("home", "pull", "home", "away"), data.mode("families").take(4).map { it.jsonPrimitive.content })
        assertEquals(JsonNull, data.mode("families")[5])
        assertEquals("borrowed", data.mode("relations")[5].jsonPrimitive.content)
        val parts = JsonArray(listOf("V/V", "", "V", "", "", null, "V").map { it?.let(::JsonPrimitive) ?: JsonNull })
        assertEquals(parts, data.mode("numerals")[4])
    }

    @Test fun aChordReadTwoWaysOnTheSheetHasAReadingForEachPlace() {
        // D goes to G (V/V), then to C (C Lydian's II): the second place has a reading of its own.
        val data = tables(inC, c, inCPlaces)
        val places = data.getValue("places").jsonObject.getValue("ionian").jsonObject
        assertEquals(setOf("10"), places.keys)
        val reading = places.getValue("10").jsonPrimitive.int
        assertEquals("II", data.mode("numerals")[reading].jsonArray[0].jsonPrimitive.content)
        assertTrue("Lydian" in textOn(data.mode("explains")[reading], c, 0))
    }

    @Test fun eachLineNamesTheKeyShownOnEveryTransposition() {
        val data = tables(inC, c, inCPlaces)
        for (mode in listOf("ionian", "aeolian", "dorian")) {
            for (i in inC.indices) for (s in 0 until 12) {
                val shown = Key(s, mode)
                val words = Theory.spelling(shown)[s] + " " + HarmonyChords.modeWord(mode)
                val line = textOn(data.mode("explains", mode)[i], Key(0, mode), s)
                assertTrue(line.startsWith(data.mode("numerals", mode)[i].jsonArray[0].jsonPrimitive.content + ": ") && words in line,
                           "$mode $s: $line")
            }
        }
    }

    @Test fun theLinesAreHarmonysOnEveryTransposition() {
        val names = listOf("Am", "G", "F", "E7")
        val key = Key(9, "aeolian")
        val data = tables(names, key, (0 until 8).map { it % 4 to 0 })
        assertEquals(listOf("i", "♭VII", "♭VI", "V7"), data.mode("numerals", "aeolian").map { it.jsonArray[0].jsonPrimitive.content })
        val chords = names.map { Theory.parseChord(it)!! }
        val goes = listOf(chords[1], chords[2], chords[3], chords[0])  // Am G F E7, round again
        for ((i, chord) in chords.withIndex()) for (s in 0 until 12) {
            assertEquals(Harmony.explain(HarmonyTables.shifted(chord, s)!!, Key(Math.floorMod(9 + s, 12), "aeolian"),
                                         HarmonyTables.shifted(goes[i], s)),
                         textOn(data.mode("explains", "aeolian")[i], key, s))
        }
    }

    @Test fun eachChordAndEachAlternativeHasItsNotesAndItsScaleForASolo() {
        val data = tables(inC, c, inCPlaces)
        val tones = data.getValue("tones").jsonObject
        assertEquals("C E G|R 3 5|0 4 7", tones.getValue("C").jsonPrimitive.content)
        assertEquals("D F# A|R 3 5|2 6 9", tones.getValue("D").jsonPrimitive.content)
        assertEquals("Bb D F|R 3 5|10 2 5", tones.getValue("Bb").jsonPrimitive.content)
        val words = data.getValue("scaleWords").jsonArray
        assertEquals("minor", words[data.mode("solo")[2].jsonPrimitive.int].jsonPrimitive.content)
        val scales = data.getValue("scales").jsonObject
        assertEquals("A minor|A B C D E F G", scales.getValue("A minor").jsonPrimitive.content)
        assertEquals("B minor|B C# D E F# G A", scales.getValue("B minor").jsonPrimitive.content)
        assertEquals(data.mode("altNumerals").map { it.jsonArray.size }, data.mode("altSolo").map { it.jsonArray.size })
        assertTrue(data.mode("altNumerals")[0].jsonArray[0].jsonPrimitive.content[0] in "hapbslo")
        assertEquals(listOf(4, 9, 2, 7, 11, 4), data.getValue("tuning").jsonArray.map { it.jsonPrimitive.int })
    }

    @Test fun tonesCarryEachNotesPitchClass() {
        val names = listOf("G", "G7", "C", "Em", "D7")
        val data = tables(names, Key(7, "ionian"), listOf(0 to 0, 1 to 0, 2 to 0, 0 to 0, 0 to 0, 3 to 0, 4 to 0, 0 to 0))
        val tones = data.getValue("tones").jsonObject
        assertEquals("D F# A C|R 3 5 ♭7|2 6 9 0", tones.getValue("D7").jsonPrimitive.content)
        assertEquals("G B D F|R 3 5 ♭7|7 11 2 5", tones.getValue("G7").jsonPrimitive.content)
        for (chord in names.map { Theory.parseChord(it)!! }) for (s in 0 until 12) {
            val shown = Key(Math.floorMod(7 + s, 12), "ionian")
            val (notes, steps, pcs) = tones.getValue(HarmonyTables.pageName(chord, Theory.spelling(shown), s)).jsonPrimitive.content.split("|")
            val found = Harmony.chordTones(HarmonyTables.shifted(chord, s)!!, shown)
            assertEquals(found.map { it.first }, notes.split(" "))
            assertEquals(found.map { it.second }, steps.split(" "))
            assertEquals(HarmonyTables.shifted(chord, s)!!.pitchClasses, pcs.split(" ").map(String::toInt).toSet())
        }
        for (named in tones.values) {
            val (notes, _, pcs) = named.jsonPrimitive.content.split("|")
            assertEquals(notes.split(" ").map(HarmonyTables::pitchClass), pcs.split(" ").map(String::toInt))
        }
    }

    @Test fun aSongWithNoKeyHasNoNumeralsButItsChordsNotes() {
        val data = tables(listOf("N.C.", "Xq", "C"), null, listOf(0 to 0, 1 to 0, 2 to 0))
        assertEquals(setOf("tones"), data.keys)
        assertEquals("C E G|R 3 5|0 4 7", data.getValue("tones").jsonObject.getValue("C").jsonPrimitive.content)
    }

    @Test fun theMembersComeInPythonsOrder() {
        assertEquals(listOf("tones", "numerals", "families", "relations", "explains", "places", "altNumerals", "solo",
                            "altSolo", "keyScale", "pentatonic", "pentatonicName", "progressions", "tuning", "scaleWords",
                            "scales"), tables(inC, c, inCPlaces).keys.toList())
    }

    @Test fun eachSectionsProgressionWithItsChordsAndKey() {
        val rows = tables(inC, c, inCPlaces).mode("progressions")
        val verse = rows[0].jsonArray
        assertEquals(0, verse[0].jsonPrimitive.int)
        assertEquals(listOf("I", "V", "vi", "IV"), verse[1].jsonArray.map { it.jsonPrimitive.content })
        assertEquals(2, verse[2].jsonPrimitive.int)
        assertEquals("the pop progression", verse[3].jsonPrimitive.content)
        assertEquals("I V vi IV", verse[5].jsonPrimitive.content)
        assertEquals(listOf(0, 1, 2, 3), verse[6].jsonArray.map { it.jsonPrimitive.int })
        val bridge = rows[1].jsonArray
        assertEquals(listOf("V/V", "V", "II", "I", "♭VII", "IV", "I"), bridge[1].jsonArray.map { it.jsonPrimitive.content })
        assertEquals("plagal", bridge[4].jsonPrimitive.content)
        assertEquals(listOf(4, 1, 4, 0, 5, 3, 0), bridge[6].jsonArray.map { it.jsonPrimitive.int })
        assertEquals(JsonArray(listOf(JsonArray(listOf(JsonPrimitive("the double-plagal progression"), JsonPrimitive(1),
                                                       JsonPrimitive("I ♭VII IV"))))), bridge[8])
    }

    @Test fun aTextIsWrittenOnceWhereItsNotesAllowIt() {
        assertEquals(JsonPrimitive("the same"), HarmonyTables.textOf(List(12) { "the same" }, c))
        assertEquals(listOf<Any>(0, " Dorian"), HarmonyTables.parts("C Dorian"))
        assertEquals(listOf<Any>("Bbass"), HarmonyTables.parts("Bbass"))  // "Bb" before "ass": no note, nor its B
        assertEquals(listOf<Any>(10, "maj7"), HarmonyTables.parts("Bbmaj7"))
        assertEquals(listOf<Any>("Dorian"), HarmonyTables.parts("Dorian"))
        assertEquals(0, HarmonyTables.pitchClass("B#"))
        assertEquals(3, HarmonyTables.pitchClass("Fbb"))
    }
}
