package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.viewer.testing.replays.ShapesReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** viewer.shapes.Instruments answers as viewer/instruments.py: every record of vectors/viewer/instruments.jsonl
 * (ShapesReplay), and test_viewer_instruments.py's own cases, by hand. */
class InstrumentsTest {
    @Test fun everyRecordIsInstrumentsPys() = ShapesReplay.instruments()

    private fun ch(name: String) = Theory.parseChord(name)!!

    @Test fun theInstrumentsTheViewerOffersInItsMenusOrder() {
        val all = Instruments.INSTRUMENTS.values.toList()
        assertEquals(listOf("guitar", "ukulele", "ukulele-low-g", "baritone", "piano", "harmonica", "flute", "recorder"),
                     all.map { it.id })
        assertEquals(listOf(40, 45, 50, 55, 59, 64), Instruments.GUITAR.tuning)
        assertEquals(listOf(67, 60, 64, 69), Instruments.UKULELE.tuning)
        assertEquals(listOf(55, 60, 64, 69), Instruments.UKULELE_LOW_G.tuning)
        assertEquals(listOf(50, 55, 59, 64), Instruments.BARITONE.tuning)
        assertEquals(listOf(true, true, true, true, false, false, false, false), all.map { it.capo })
        assertEquals(List(7) { 0 } + 12, all.map { it.sounds })
        assertEquals(listOf("reed", "flute", "recorder"), all.drop(5).map { it.voice })
        assertEquals("ukulele:", Instruments.BARITONE.shapes)
        assertEquals(5, Instruments.BARITONE.offset)
    }

    @Test fun anAddressNamesAnInstrumentOrGetsTheGuitar() {
        assertSame(Instruments.UKULELE, Instruments.instrument("ukulele"))
        assertSame(Instruments.PIANO, Instruments.instrument("piano"))
        assertSame(Instruments.GUITAR, Instruments.instrument(null))
        assertSame(Instruments.GUITAR, Instruments.instrument("kazoo"))
    }

    @Test fun aQualityTheUkuleleHasNoShapesForShowsItsNearest() {
        assertEquals("6", Instruments.ukuleleQuality("13"))  // the first of the largest it has
        assertEquals("", Instruments.ukuleleQuality("5"))
        assertEquals("m", Instruments.ukuleleQuality("m"))
        val uke = Instruments.chordShapes(Instruments.UKULELE, ch("C/E"))
        assertEquals(Instruments.chordShapes(Instruments.UKULELE, ch("C")), uke)  // the plain chord
        // the baritone plays the ukulele's shapes a fourth lower: its G is the ukulele's C
        assertEquals(Instruments.chordShapes(Instruments.UKULELE, ch("C")), Instruments.chordShapes(Instruments.BARITONE, ch("G")))
    }

    @Test fun aPianoChordIsItsRootPositionThenTwoInversionsWithItsRootInTheBass() {
        assertEquals(listOf(listOf(48, 60, 64, 67), listOf(48, 64, 67, 72), listOf(48, 55, 60, 64)),
                     Instruments.pianoPositions(ch("C")))
        assertEquals(listOf(listOf(45, 57, 60, 64), listOf(45, 60, 64, 69), listOf(45, 64, 69, 72)),
                     Instruments.pianoPositions(ch("Am")))
        assertEquals(listOf(listOf(48, 60, 67), listOf(48, 55, 60)), Instruments.pianoPositions(ch("C5")))
        assertEquals(List(3) { 52 }, Instruments.pianoPositions(ch("C/E")).map { it[0] })
        assertEquals(listOf(43, 57, 60, 64), Instruments.pianoPositions(ch("Am/G"))[0])
    }

    @Test fun aPianistStacksAChordUpFromItsRoot() {
        for ((name, stack) in listOf("C13" to listOf(0, 4, 7, 10, 2, 9), "Cadd9" to listOf(0, 4, 7, 2),
                                      "C6/9" to listOf(0, 4, 7, 9, 2), "Csus2" to listOf(0, 2, 7),
                                      "C9sus4" to listOf(0, 5, 7, 10, 2), "C7#9" to listOf(0, 4, 7, 10, 3),
                                      "Cdim7" to listOf(0, 3, 6, 9), "Cmaj7#11" to listOf(0, 4, 7, 11, 6),
                                      "C11" to listOf(0, 4, 7, 10, 2, 5))) {
            assertEquals(stack, Instruments.stacked(ch(name)), name)
        }
    }

    @Test fun everyPianoPositionPlaysItsChordInTheHandsRanges() {
        for (quality in Theory.QUALITIES.keys) for (root in 0 until 12) for (bass in listOf(null, (root + 4) % 12)) {
            val chord = Chord(root, quality, bass)
            val positions = Instruments.pianoPositions(chord)
            assertEquals(minOf(3, chord.intervals.size), positions.size, chord.toString())
            for (position in positions) {
                val low = position[0]
                val right = position.drop(1)
                assertEquals(chord.intervals.map { (root + it) % 12 }.toSet(), right.map { it % 12 }.toSet())
                assertEquals(right.sorted(), right)
                assertTrue(right[0] in 53..64 && low in 41..52 && low < right[0])
                assertEquals(bass ?: root, low % 12)
            }
        }
    }

    @Test fun thePianoFilesAChordBySuffixAndBass() {
        assertEquals("piano:m7|", Instruments.pianoKey(ch("Am7")))
        assertEquals("piano:|4", Instruments.pianoKey(ch("C/E")))
        assertEquals("piano:m|10", Instruments.pianoKey(ch("Dm/C")))
        assertEquals(JsonArray(Instruments.pianoPositions(ch("D")).map { r -> JsonArray(r.map(::JsonPrimitive)) }),
                     Instruments.chordShapes(Instruments.PIANO, ch("C"), 2))
    }

    @Test fun anAnswerKeptIsHandedOutAsACopy() {
        @Suppress("UNCHECKED_CAST")
        val table = Instruments.pianoTable(ch("C")) as MutableList<MutableList<MutableList<Int>>>
        table[0][0].add(99)
        table[1].clear()
        assertEquals(listOf(48, 60, 64, 67), Instruments.pianoTable(ch("C"))[0][0])
        assertEquals(Instruments.pianoPositions(ch("Db")), Instruments.pianoTable(ch("C"))[1])
    }

    @Test fun theEasyKeysCantBeChanged() {
        val (majors, minors) = Instruments.EASY.values.first()
        assertFailsWith<UnsupportedOperationException> { (majors as MutableList<Int>).add(1) }
        assertFailsWith<UnsupportedOperationException> { (minors as MutableList<Int>).clear() }
    }

    @Test fun theUkulelesEasyKeysAndTheBaritones() {
        fun keys(table: String, mode: String) = Instruments.easyKeys(table).getValue(mode).jsonArray.map {
            it.jsonArray[0].jsonPrimitive.int to it.jsonArray[1].jsonPrimitive.content
        }
        assertEquals(listOf(0 to "C", 5 to "F", 7 to "G", 10 to "Bb"), keys("ukulele", "ionian"))
        assertEquals(listOf(2 to "Dm", 9 to "Am"), keys("ukulele", "aeolian"))
        assertEquals(listOf(0 to "C dorian", 2 to "D dorian", 7 to "G dorian", 9 to "A dorian"), keys("ukulele", "dorian"))
        assertEquals(listOf(0 to "C", 2 to "D", 5 to "F", 7 to "G"), keys("baritone", "ionian"))
        assertTrue(Instruments.isEasy("ukulele", Key(9, "aeolian")))
        assertFalse(Instruments.isEasy("ukulele", Key(4, "aeolian")))
        assertFailsWith<NoSuchElementException> { Instruments.isEasy("kazoo", Key(0, "ionian")) }
    }

    @Test fun aPageCarriesTheInstrumentsAndTheirShapesForItsChords() {
        val entries = Instruments.entries(setOf("", "5", "maj9", "/4"))
        assertEquals(Instruments.INSTRUMENTS.keys.toList(), entries.map { it.jsonObject.getValue("id").jsonPrimitive.content })
        val uke = entries[1].jsonObject
        assertEquals(mapOf("5" to "", "maj9" to "maj7"), uke.getValue("near").jsonObject.mapValues { it.value.jsonPrimitive.content })
        assertEquals(listOf("id", "name", "kind", "capo", "shapes", "offset", "easy", "voice", "sounds", "about", "tab",
                            "tuning", "near"), uke.keys.toList())
        assertEquals("Baritone", entries[3].jsonObject.getValue("tab").jsonPrimitive.content)
        assertEquals("Guitar", entries[0].jsonObject.getValue("tab").jsonPrimitive.content)
        val more = Instruments.pageVoicings(setOf("m7", "", "/4"), listOf(ch("Am7"), ch("C/E")))
        assertEquals(listOf("ukulele:", "ukulele:m7", "piano:m7|", "piano:|4"), more.keys.toList())
    }
}
