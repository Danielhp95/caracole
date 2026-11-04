package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.testing.replays.ShapesReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.shapes.Voicings answers as viewer/voicings.py: every record of vectors/viewer/voicings.jsonl
 * (ShapesReplay), and test_viewer_voicings.py's own cases, by hand. */
class VoicingsTest {
    @Test fun everyRecordIsVoicingsPys() = ShapesReplay.voicings()

    private fun ch(name: String) = Theory.parseChord(name)!!
    private fun p(frets: String, fingers: String = "000000", base: Int = 1, barres: List<Int> = emptyList()) =
        Voicings.position(frets, fingers, base, barres)

    @Test fun theTuningIsTheDatas() {
        val data = ViewerData.table("instruments").getValue("voicings").jsonObject
        assertEquals(data.getValue("TUNING").jsonArray.map { it.jsonPrimitive.int }, Voicings.TUNING)
        assertEquals(4, Voicings.MAX_POSITIONS)
    }

    @Test fun positionsAreReadAsTheNotesTheySound() {
        assertEquals(listOf(48, 52, 55, 60, 64), Voicings.notesOf(p("x32010", "032010")))
        assertEquals(listOf(48, 55, 60, 64, 67), Voicings.notesOf(p("x13331", "012341", 3, listOf(1))))
        assertEquals(listOf(48, 52, 55, 60, 64), Voicings.notesOf(p("x３２０１０")))  // fullwidth digits are digits
        assertFailsWith<IllegalArgumentException> { Voicings.notesOf(p("x320100")) }  // seven strings: zip(strict)
    }

    @Test fun theOpenShapesComeFirstAndEveryQualityHasSomeFingering() {
        val data = Voicings.loadVoicings()
        assertEquals("x32010", Voicings.frets(data.getValue("")[0][0]))
        assertEquals("320003", Voicings.frets(data.getValue("")[7][0]))
        assertEquals("x02210", Voicings.frets(data.getValue("m")[9][0]))
        for (quality in Theory.QUALITIES.keys) assertTrue(Voicings.voicingKeys(Chord(0, quality)).first in data, quality)
        assertTrue(data.values.all { it.size == 12 })
    }

    @Test fun aChordWithoutFingeringsShowsTheNearestOneItHas() {
        for ((name, keys) in listOf("Am7" to ("m7" to false), "CM7" to ("maj7" to false), "Cmaj7#11" to ("maj7" to true),
                                     "Cm9b5" to ("m7b5" to true), "C7sus2" to ("sus2" to true), "C(b5)" to ("" to true),
                                     "Cfoo" to ("" to true))) {
            val (q, nearest) = Voicings.voicingKeys(Theory.parseChord(name, strict = false)!!)
            assertEquals(keys, q to nearest, name)
        }
        assertEquals(Triple("", false, "/4"), Voicings.voicingKeys(ch("C/E")))
        assertEquals(Triple("m", false, "m/10"), Voicings.voicingKeys(ch("Am/G")))
        assertEquals(Triple("", false, null), Voicings.voicingKeys(ch("C")))
    }

    @Test fun aFingeringAsATabWritesItBecomesAPosition() {
        for ((written, want) in listOf(
            "x32033" to p("x32033"), "(x32033)" to p("x32033"), "X32033" to p("x32033"), "x-3-2-0-3-3" to p("x32033"),
            "x 3 2 0 3 3" to p("x32033"), "( 022033 )" to p("022033"), "8 10 10 9 8 8" to p("133211", base = 8),
            "(0-7-9-9-8-0)" to p("013320", base = 7), "x24442" to p("x24442"), "x٣٢٠٣٣" to p("x32033"),
        )) assertEquals(want, Voicings.parseFingering(written), written)
        for (written in listOf("x2", "(x4)", "x3203", "1234567", "x-3-2-0-3", "xxxxxx", "", "Cadd9", "12 1 1 1 1 1",
                               "(x32033", "x32033)", "0 2 2 0 3 30")) {
            assertNull(Voicings.parseFingering(written), written)
        }
    }

    @Test fun aChordLegendsLineGivesEachChordItsFingering() {
        fun given(line: String) = Voicings.chordLegend(line).map { (c, pos) -> listOf(c.root, c.suffix, c.bass, Voicings.frets(pos)) }
        assertEquals(listOf(listOf(2, "sus4", null, "xx0233")), given("Dsus4   (xx0233)"))
        assertEquals(listOf(listOf(2, "sus4", 6, "2x0233")), given("Dsus4/F#(2x0233)"))
        assertEquals(listOf(listOf(0, "add9", null, "x32033")), given("Cadd9: x32033"))
        assertEquals(listOf(listOf(4, "m7", null, "022033"), listOf(7, "", null, "320033")), given("Em7 022033 | G 320033"))
        assertEquals(listOf(listOf(4, "5", null, "022xxx")), given("E5 0 2 2 x x x"))  // not an E with a 5th fret
        assertEquals(listOf(listOf(10, "", null, "133211")), given("Bb 6 8 8 7 6 6"))
        for (line in listOf("Capo 2. fret", "EADGBe", "Cadd9 (x32033) in the chorus", "G (x2)", "Em7", "x32033",
                            "Cadd9 x3203", "Em7 (022033) foo", "Cfoo x32033", "", "   ")) {
            assertEquals(emptyList(), Voicings.chordLegend(line), line)
        }
    }

    @Test fun aDefineDirectiveGivesItsChordAPosition() {
        assertEquals(ch("Cadd9") to p("x32033", "021034"),
                     Voicings.parseDefine("Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 2 1 0 3 4"))
        assertEquals(ch("Ab") to p("133211", base = 4), Voicings.parseDefine("Ab base-fret 4 frets 1 3 3 2 1 1"))
        assertEquals(ch("D/F#") to p("2x0232"), Voicings.parseDefine("D/F# frets 2 N 0 2 3 2 base-fret 1"))
        assertEquals(ch("G") to p("320033", "210034"), Voicings.parseDefine("G frets 3 2 0 0 3 3 fingers 2 1 - - 3 4"))
        assertEquals(ch("Em") to p("x22000"), Voicings.parseDefine("Em frets -1 2 2 0 0 0"))
        for (value in listOf("Cadd9", "Cadd9 base-fret 1", "Cadd9 frets x 3 2", "Hm frets x 0 2 2 1 0",
                             "Cfoo frets x 3 2 0 3 3", "C frets x 3 2 0 1 12", "C frets x x x x x x", "C keys 0 4 7",
                             "C copy D", "")) {
            assertNull(Voicings.parseDefine(value), value)
        }
    }

    @Test fun aFingeringPlaysAChordWhenItSoundsItsNotesAlone() {
        assertTrue(Voicings.plays(Voicings.parseFingering("x32033")!!, ch("Cadd9")))
        assertTrue(Voicings.plays(Voicings.parseFingering("2x0233")!!, ch("Dsus4/F#")))
        assertFalse(Voicings.plays(Voicings.parseFingering("x32033")!!, ch("G")))
        assertFalse(Voicings.plays(Voicings.parseFingering("xx0233")!!, ch("Dsus4/F#")))
    }

    @Test fun aSheetsOwnShapesComeFirstAndEachShapeOnce() {
        val shapes = Voicings.sheetShapes(listOf(ch("C") to p("x32010"), ch("Cadd9") to p("x32033", "021034"),
                                                 ch("G") to p("x32033")))  // a shape that doesn't play G: left out
        assertEquals(listOf("0,,", "0,add9,"), shapes.keys.toList())
        val c = shapes.getValue("0,,").jsonObject
        assertEquals(1, c.getValue("mine").jsonPrimitive.int)
        val first = c.getValue("list").jsonArray[0].jsonArray
        assertEquals("x32010", Voicings.frets(first))
        assertEquals("032010", Voicings.fingers(first))  // chords-db's, with its fingers: the sheet gave none
        assertEquals(1, c.getValue("list").jsonArray.count { Voicings.fretsFromNut(it.jsonArray) == listOf(null, 3, 2, 0, 1, 0) })
        assertEquals("021034", Voicings.fingers(shapes.getValue("0,add9,").jsonObject.getValue("list").jsonArray[0].jsonArray))
    }

    @Test fun thePageGetsTheFingeringsFiledUnderItsKeysInOrder() {
        val page = Voicings.pageVoicings(setOf("m7", "", "nope", "/4"))
        assertEquals(listOf("", "/4", "m7"), page.keys.toList())
        assertEquals(Voicings.rawVoicings().getValue("m7"), page.getValue("m7"))
    }
}
