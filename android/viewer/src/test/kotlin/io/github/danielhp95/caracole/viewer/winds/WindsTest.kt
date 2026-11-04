package io.github.danielhp95.caracole.viewer.winds

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
import kotlin.test.assertTrue

/** viewer.winds.Winds answers as viewer/winds.py: every record of vectors/viewer/winds.jsonl (ShapesReplay), and
 * test_viewer_winds.py's own cases, by hand. */
class WindsTest {
    @Test fun everyRecordIsWindsPys() = ShapesReplay.winds()

    private val names = listOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    private fun midi(name: String) = names.indexOf(name.dropLast(1)) + 12 * (name.last() - '0' + 1)
    private fun ch(name: String) = Theory.parseChord(name)!!

    private fun pressed(wind: Wind, note: String): Set<String> {
        val f = Winds.fingerings(wind, midi(note))[0]
        return wind.keys.zip(f.states).filter { it.second == "x" }.map { it.first }.toSet()
    }

    @Test fun theFluteReadsC4ToC7AtConcertPitch() {
        val flute = Winds.FLUTE
        assertEquals(Triple(midi("C4"), midi("C7"), 0), Triple(flute.low, flute.high, flute.sounds))
        assertTrue((flute.low..flute.high).all { Winds.fingerings(flute, it).isNotEmpty() })
        assertEquals(emptyList(), Winds.fingerings(flute, flute.low - 1))
        val hands = setOf("L1", "L2", "L3", "R1", "R2", "R3")
        assertEquals(setOf("thumb", "C") + hands, pressed(flute, "C4"))
        assertEquals(setOf("thumb", "L2", "L3", "R1", "R2", "R3"), pressed(flute, "D5"))  // the first finger vents
        assertEquals(setOf("Eb"), pressed(flute, "C#5"))
        assertEquals(setOf("thumb", "R1", "trill-D"), pressed(flute, "A#6"))
        val (standard, thumb) = Winds.fingerings(flute, midi("A#4"))
        assertEquals("T 1--|1-- Eb" to "Bb 1--|--- Eb", standard.chart to thumb.chart)
    }

    @Test fun theRecordersBaroqueAndGermanFingerings() {
        val recorder = Winds.RECORDER
        assertEquals(Triple(midi("C4"), midi("D6"), 12), Triple(recorder.low, recorder.high, recorder.sounds))
        assertEquals("xxxxxxxxo", Winds.fingerings(recorder, midi("C4"))[0].text)
        assertEquals("xxxxxoxxo", Winds.fingerings(recorder, midi("F4"))[0].text)  // baroque: forked
        assertEquals("xxxxxoooo", Winds.fingerings(recorder, midi("F4"), "german")[0].text)
        assertEquals(emptyList(), Winds.fingerings(recorder, midi("D#6")))
        assertFailsWith<IllegalArgumentException> { Winds.fingerings(recorder, midi("C5"), "boehm") }
        assertFailsWith<IllegalArgumentException> { Winds.fingerings(Winds.FLUTE, midi("C5"), "german") }
    }

    @Test fun theOctaveAMelodyIsPlayedIn() {
        val flute = Winds.fit(listOf(midi("G4"), midi("E5"), midi("C5")), Winds.FLUTE)
        assertEquals(Fit(0, listOf(midi("G4"), midi("E5"), midi("C5")), emptyList()), flute)
        assertEquals(12 to listOf(midi("G4"), midi("E5")),
                     Winds.fit(listOf(midi("G4"), midi("E5")), Winds.RECORDER).let { it.shift to it.written })
        assertEquals(24, Winds.fit(listOf(midi("C3"), midi("E4")), Winds.RECORDER).shift)
        assertEquals(-12, Winds.fit(listOf(midi("E6"), midi("A6")), Winds.FLUTE).shift)
        assertEquals(0, Winds.fit(listOf(midi("D6")), Winds.FLUTE).shift)
        assertEquals(2, Winds.fit(listOf(midi("C3"), midi("G4"), midi("C5"), midi("G6"), midi("E7")), Winds.RECORDER).outside.size)
    }

    @Test fun aKeysScaleAndAChordsNotes() {
        assertEquals("C4 D4 E4 F4 G4 A4 B4 C5".split(" ").map(::midi), Winds.scaleNotes(Key(0, "ionian")))
        assertEquals("A4 B4 C5 D5 E5 F5 G5 A5".split(" ").map(::midi), Winds.scaleNotes(Key(9, "aeolian")))
        for ((name, notes) in listOf("C" to "C4 E4 G4", "C9" to "C4 E4 G4 A#4 D5", "G/B" to "G4 B4 D5",
                                      "C/D" to "C4 D4 E4 G4", "C11" to "C4 E4 G4 A#4 D5 F4", "B13" to "B4 D#5 F#5 A5 C#6 G#5")) {
            val found = Winds.chordNotes(ch(name))
            assertEquals(notes.split(" ").map(::midi), found, name)
            assertEquals(found.map { it - found[0] }, Winds.chordSteps(ch(name)))
        }
        for (quality in Theory.QUALITIES.keys) {
            val steps = Winds.chordSteps(Chord(0, quality))
            assertTrue(steps[0] == 0 && steps.max() <= 15, quality)
        }
    }

    @Test fun solfegeNamesANoteAsSpanishSpeakingPlayersReadIt() {
        for ((name, said) in listOf("C" to "Do", "G" to "Sol", "Bb" to "Sib", "F#" to "Fa#", "Ebb" to "Mibb")) {
            assertEquals(said, Winds.solfege(name))
        }
        assertFailsWith<NoSuchElementException> { Winds.solfege("H") }
        assertFailsWith<IndexOutOfBoundsException> { Winds.solfege("") }
    }

    @Test fun theFingeringDataIsEachNoteFromC4Up() {
        val data = Winds.fingeringData()
        assertEquals(60, data.getValue("low").jsonPrimitive.int)
        val flute = data.getValue("flute").jsonObject
        assertEquals(Winds.FLUTE.high - 60 + 1, flute.getValue("notes").jsonArray.size)
        assertEquals(listOf("holes", "baroque", "german"), data.getValue("recorder").jsonObject.keys.toList())
        assertEquals(listOf("low", "flute", "recorder", "solfege"), data.keys.toList())
    }

    @Test fun theTablesGiveEachChordsStepsByItsIndexAndEachFormOnce() {
        val chords = listOf(ch("C"), ch("G"), null, ch("C7"))
        val noKey = Winds.tables(chords, null, emptyMap(), emptyMap())
        assertEquals(listOf("windForms", "windChords", "windAlts"), noKey.keys.toList())
        assertEquals(listOf(listOf(0, 4, 7), listOf(0, 4, 7, 10)),
                     noKey.getValue("windForms").jsonArray.map { f -> f.jsonArray.map { it.jsonPrimitive.int } })
        assertEquals("[0,0,null,1]", noKey.getValue("windChords").jsonObject.getValue("").toString())
        val key = Key(0, "ionian")
        val mapped = Theory.MODES.associateWith { m -> chords.map { c -> c?.let { Theory.mapChord(it, key, m) } } }
        val alts = Theory.MODES.associateWith { m -> mapped.getValue(m).map { emptyList<Chord>() } }
        assertEquals(Theory.MODES, Winds.tables(chords, key, mapped, alts).getValue("windChords").jsonObject.keys.toList())
    }
}
