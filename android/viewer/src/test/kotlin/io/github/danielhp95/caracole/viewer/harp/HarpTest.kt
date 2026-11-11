package io.github.danielhp95.caracole.viewer.harp

import io.github.danielhp95.caracole.viewer.testing.replays.ShapesReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harp.Harp answers as viewer/harp.py: every record of vectors/viewer/harp_play.jsonl, harp_choices.jsonl and
 * harp_tables.jsonl (ShapesReplay), and test_viewer_harp.py's own cases, by hand. */
class HarpTest {
    @Test fun everyPlayRecordIsHarpPys() = ShapesReplay.harpPlay()
    @Test fun everyChoicesRecordIsHarpPys() = ShapesReplay.harpChoices()
    @Test fun everyTablesRecordIsHarpPys() = ShapesReplay.harpTables()

    private val C = 0
    private val sharps = Theory.spelling(null)

    private fun ch(name: String) = Theory.parseChord(name)!!
    private fun chords(text: String) = text.split(" ").map(::ch)

    @Test fun aCHarpBlowsItsTriadAndDrawsTheRestOfItsScale() {
        val c = Harp.layout(C)
        assertEquals(listOf(60, 64, 67, 72, 76, 79, 84, 88, 91, 96), c.blow)
        assertEquals(listOf(62, 67, 71, 74, 77, 81, 83, 86, 89, 93), c.draw)
        for (key in 0 until 12) {
            val one = Harp.layout(key)
            assertEquals(55 + Math.floorMod(key - 7, 12), one.blow[0])
            assertEquals(Harp.HARP_KEYS[key], one.name)
        }
        assertEquals(listOf("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"), Harp.HARP_KEYS)
        assertEquals(listOf(listOf(61), listOf(66, 65), listOf(70, 69, 68), listOf(73), emptyList(), listOf(80),
                            emptyList(), listOf(87), listOf(90), listOf(95, 94)), c.bends)
    }

    @Test fun positionsAreNumberedRoundTheCircleOfFifths() {
        assertEquals(listOf("ionian", "mixolydian", "dorian", "aeolian", "phrygian", "locrian", null, null, null, null,
                            null, "lydian"), Harp.POSITIONS.map(Harp::positionMode))
        assertEquals(0, Harp.harpFor(7, 2))  // a song in G: a C harp in the 2nd
        for (tonic in 0 until 12) for (harp in 0 until 12) assertEquals(harp, Harp.harpFor(tonic, Harp.positionOf(tonic, harp)))
        assertEquals(listOf("1st", "2nd", "3rd", "4th", "11th", "12th"), listOf(1, 2, 3, 4, 11, 12).map(Harp::ordinal))
    }

    @Test fun aCHarpPlaysTheseChords() {
        for ((name, text) in listOf("C" to "blow 1–3", "G" to "draw 2–4", "G7" to "draw 2–5", "G9" to "draw 2–6",
                                     "Dm" to "draw 4–6", "Dm6" to "draw 4–7", "Bdim" to "draw 3–5", "Bm7b5" to "draw 3–6",
                                     "G/D" to "draw 1–3", "C/E" to "blow 2–4", "G/B" to "draw 2–4")) {
            val found = Harp.play(ch(name), C)
            assertEquals("yes" to text, found.kind to found.text(sharps), name)
        }
        for (name in listOf("Am", "F", "Em", "E", "Gm", "Fmaj7", "Bb", "A7", "Gsus4", "Caug")) {
            assertEquals(Playing("no", null, null, null), Harp.play(ch(name), C), name)
            assertEquals("not on this harp", Harp.play(ch(name), C).text(sharps))
        }
        for ((name, text) in listOf("Cmaj7" to "blow 1–3 (as C)", "Dm7" to "draw 4–6 (as Dm)",
                                     "Bdim7" to "draw 3–5 (as Bdim)", "C/D" to "blow 1–3 (as C)")) {
            val found = Harp.play(ch(name), C)
            assertEquals("part" to text, found.kind to found.text(sharps), name)
        }
        for (name in listOf("D", "D7", "D9", "D6")) {
            val found = Harp.play(ch(name), C)
            assertEquals("minor" to "draw 4–6 (as Dm, minor substitute)", found.kind to found.text(sharps))
            assertEquals(Chord(2, "m"), found.played)
        }
    }

    @Test fun theHarpsForASongByItsModeThenTheChordsTheyPlay() {
        fun names(key: Key, progression: String) = Harp.choices(key, chords(progression)).map { it.name to it.position }
        assertEquals(listOf("G" to 1, "C" to 2), names(Key(7, "ionian"), "G C D"))
        assertEquals(listOf("C" to 2), names(Key(7, "mixolydian"), "G F C").take(1))
        assertEquals("G" to 3, names(Key(9, "aeolian"), "Am G F E").first())
        assertEquals("Harmonica: G harp (1st position) · C harp (2nd)", Harp.headerLine(Key(7, "ionian"), chords("G C D")))
        assertEquals(Harp.choices(Key(7, "ionian"), chords("G C D")),
                     Harp.choices(Key(7, "ionian"), chords("G C D G") + null))  // a chord again, or none: once or never
    }

    @Test fun theRankingIsOneRuleAndAListHandedOutIsACopy() {
        val choice = HarpChoice(3, 7, "dorian", 2.5, 3, 2, 1)
        assertEquals(listOf(0.0), Harp.ranking(Key(7, "ionian"), 0, choice))
        assertEquals(listOf(-2.5, 1.0, 1.0), Harp.ranking(Key(9, "aeolian"), 1, choice))
        val first = Harp.choices(Key(7, "ionian"), chords("G C D")) as MutableList<HarpChoice>
        first.clear()
        assertTrue(Harp.choices(Key(7, "ionian"), chords("G C D")).isNotEmpty())
        assertFailsWith<UnsupportedOperationException> { (Harp.layout(C).blow as MutableList<Int>).add(1) }
    }

    @Test fun theTablesHoldTheHarpsForEveryModeAndNoKeyNoHarps() {
        assertEquals(emptySet(), Harp.tables(null, emptyMap()).keys)
        val key = Key(9, "aeolian")
        val am = chords("Am G F E")
        val tables = Harp.tables(key, mapOf("aeolian" to am))
        assertEquals(listOf("harpKeys", "harpForms", "harpChords", "harpAlts", "harpRing", "harpHoles", "harpScales",
                            "harpOutside", "harpNotes", "harpAltNotes", "harps").sorted(), tables.keys.sorted())
        assertEquals(listOf("aeolian"), tables.getValue("harps").jsonObject.keys.toList())
        val forms = tables.getValue("harpForms").jsonArray
        assertEquals(4, forms.size)  // each chord its own form
        assertEquals(12, forms[0].jsonArray.size)
    }

    @Test fun aHolesNoteBlownDrawnBentAndOverblown() {
        assertEquals(Harp.BLOW.map { 60 + it }, (1..10).map { Harp.holeNote(C, it, "blow") })
        assertEquals(Harp.DRAW.map { 60 + it }, (1..10).map { Harp.holeNote(C, it, "draw") })
        assertEquals(70, Harp.holeNote(C, 3, "draw", 1))
        assertEquals(68, Harp.holeNote(C, 3, "draw", 3))
        assertNull(Harp.holeNote(C, 3, "draw", 4))
        assertEquals(94, Harp.holeNote(C, 10, "blow", 2))
        assertNull(Harp.holeNote(C, 5, "draw", 1))
        assertNull(Harp.holeNote(C, 3, "blow", 1))
        assertEquals(82, Harp.holeNote(C, 6, "blow", over = true))
        assertEquals(85, Harp.holeNote(C, 7, "draw", over = true))
        assertNull(Harp.holeNote(C, 11, "blow"))
        assertNull(Harp.holeNote(C, 0, "draw"))
        assertEquals(90, Harp.holeNote(2, 8, "blow"))
        assertEquals(69, Harp.holeNote(C, 3, "draw", -1))  // Python's index from the end: bends[-2]
        assertFailsWith<IndexOutOfBoundsException> { Harp.holeNote(C, 1, "draw", -1) }
    }

    @Test fun theHoleTablesHoldEveryNoteAHolePlays() {
        for ((key, table) in Harp.holeTables().withIndex()) {
            val t = table.jsonObject
            for (hole in 1..10) for (breath in listOf("blow", "draw")) {
                val listed = t.getValue(breath).jsonArray[hole - 1].jsonArray.map { it.jsonPrimitive.int }
                for (bend in 0 until 4) assertEquals(Harp.holeNote(key, hole, breath, bend), listed.getOrNull(bend))
                val over = t.getValue("over").jsonArray[hole - 1].jsonArray
                assertEquals(Harp.holeNote(key, hole, breath, over = true),
                             if (over[0].jsonPrimitive.content == breath) over[1].jsonPrimitive.int else null)
            }
        }
    }

    @Test fun aPositionInWordsAndTheRing() {
        assertEquals("4th position, aeolian", Harp.positionText(11, 2))
        assertEquals("2nd position", Harp.positionText(7, 0))
        assertEquals("3rd position, dorian", Harp.positionText(2, 0))
        assertEquals("8th position", Harp.positionText(1, 0))
        assertEquals(listOf(0, 5, 10, 3, 8, 1, 6, 11, 4, 9, 2, 7), Harp.ring().map { it.jsonArray[0].jsonPrimitive.int })
    }

    @Test fun theKeyCardsScalesAndTheLineUnderTheHoles() {
        val minor = Harp.keyScales("aeolian").map { it.jsonArray[0].jsonPrimitive.content }
        assertEquals(listOf("Scale", "Minor pentatonic", "Blues"), minor)
        assertEquals(listOf(0, 3, 5, 7, 10), Harp.keyScales("aeolian")[1].jsonArray[1].jsonArray.map { it.jsonPrimitive.int })
        // a D harp in B minor (Hotel California, offset 3) blows and draws B minor's notes; an A harp (10) a G#
        assertEquals("Every note it plays is in ", Harp.outside("aeolian", 3)[0].jsonPrimitive.content)
        val line = Harp.outside("aeolian", 10)
        assertEquals("Outside ", line[0].jsonPrimitive.content)
        assertEquals(" minor: ", line[2].jsonPrimitive.content)
        assertEquals(9, line[3].jsonPrimitive.int)
        assertEquals("Every note it plays is in ", Harp.outside("ionian", 0)[0].jsonPrimitive.content)
    }
}
