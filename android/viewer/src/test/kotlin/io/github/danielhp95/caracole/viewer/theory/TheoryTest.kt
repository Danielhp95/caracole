package io.github.danielhp95.caracole.viewer.theory

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.testing.replays.TheoryReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** viewer.theory answers as viewer/theory.py: every record of vectors/viewer/theory.jsonl (TheoryReplay), and
 * test_viewer_theory.py's own cases, by hand. */
class TheoryTest {
    @Test fun everyRecordIsTheoryPys() {
        val misses = Misses("theory")
        TheoryReplay.replay(misses)
        misses.assertNone(required = false)
    }

    private fun chords(vararg names: String): List<Chord> = names.map { Theory.parseChord(it)!! }

    private fun named(chord: Chord, key: Key? = null): String {
        val names = Theory.spelling(key)
        return names[chord.root] + chord.suffix + (chord.bass?.let { "/" + names[it] } ?: "")
    }

    @Test fun aChordNameGivesItsRootQualityAndBass() {
        for ((text, want) in listOf(
            "G" to Triple(7, "", null), "Am7" to Triple(9, "m7", null), "F#m7b5" to Triple(6, "m7b5", null),
            "G/B" to Triple(7, "", 11), "Dsus2/F#" to Triple(2, "sus2", 6), "C♯m" to Triple(1, "m", null),
            "B♭" to Triple(10, "", null),
        )) {
            val c = Theory.parseChord(text)!!
            assertEquals(want, Triple(c.root, c.quality, c.bass), text)
        }
        for ((text, quality) in listOf("CΔ" to "maj7", "C7M" to "maj7", "Cø7" to "m7b5", "C+7" to "aug7",
                                         "C+5" to "aug", "CmMaj7" to "mmaj7", "Csus" to "sus4", "C6/9" to "69",
                                         "C7+5" to "aug7", "C7(#9)" to "7#9", "Cmaj" to "")) {
            assertEquals(quality, Theory.parseChord(text)!!.quality, text)
        }
        assertNull(Theory.parseChord("C6/9")!!.bass)
        assertEquals("M7", Theory.parseChord("CM7")!!.shown)
        assertEquals("m(maj7)", Chord(0, "mmaj7").suffix)
        assertEquals("(b5)", Chord(7, "b5").suffix)
    }

    @Test fun aSuffixItCantReadIsNoChordUnlessReadLeniently() {
        for (text in listOf("N.C.", "x2", "H", "", "  ", "Cfoo")) assertNull(Theory.parseChord(text), text)
        val lenient = Theory.parseChord("Cmfoo/E", strict = false)!!
        assertEquals(Triple(0, "mfoo", 4), Triple(lenient.root, lenient.quality, lenient.bass))
        assertEquals(setOf(0, 3, 7), lenient.intervals)
        assertNull(Theory.parseChord("Cfoo/x", strict = false))
        // Python's strip: a no-break space and an ideographic one are whitespace, a zero-width space is not
        assertEquals(Chord(2, "", null, ""), Theory.parseChord("　D "))
        assertNull(Theory.parseChord("C​"))
    }

    @Test fun notesAreSpelledAsTheKeyWritesThem() {
        assertEquals("C Db D Eb E F Gb G Ab A Bb B".split(" "), Theory.spelling(Key(5, "ionian")))
        assertEquals("C C# D D# E F F# G G# A A# B".split(" "), Theory.spelling(Key(4, "ionian")))
        assertEquals("F#m", Theory.keyName(Key(6, "aeolian")))
        assertEquals("D dorian", Theory.keyName(Key(2, "dorian")))
        assertEquals("F#", Theory.keyName(Key(6, "ionian")))  // six sharps or six flats: F# over Gb
    }

    @Test fun aKeyIsReadFromHowTabsAndTagsWriteIt() {
        assertEquals(Key(9, "aeolian"), Theory.parseKey("Am"))
        assertEquals(Key(6, "aeolian"), Theory.parseKey("F#m"))
        assertEquals(Key(0, "aeolian"), Theory.parseKey("C minor"))
        assertEquals(Key(9, "dorian"), Theory.parseKey("A Dorian"))
        assertEquals(Key(10, "ionian"), Theory.parseKey(" bb "))
        for (text in listOf("", "H", "Am7", "Key: A", 42, null)) assertNull(Theory.parseKey(text), "$text")
        // IGNORECASE reads a dotless i as an i, and str.lower keeps it: a mode no key has, as Python answers it
        assertEquals(Key(9, "mınor"), Theory.parseKey("A mınor"))
        assertFailsWith<IllegalArgumentException> { Theory.keyName(Theory.parseKey("A mınor")!!) }  // a ValueError
    }

    private val hotel = arrayOf("Am", "E7", "G", "D", "F", "C", "Dm", "E", "Am", "E7", "G", "D", "F", "C", "Dm", "E7")

    @Test fun aKeyNamedByItsLetterAloneIsMinorWhenTheChordsSaySo() {
        for ((case, want) in listOf(
            Triple("A", 2, hotel.toList()) to ("Am" to "Bm"),
            Triple("B", 2, hotel.toList()) to ("Am" to "Bm"),
            Triple("C", 3, listOf("C", "F", "G", "Am", "C")) to ("C" to "Eb"),
            Triple("A", 9, listOf("Am", "F", "C", "G", "Am")) to ("Am" to "F#m"),
            Triple("C", 3, listOf("Am", "F", "C", "G", "A")) to ("C" to "Eb"),
            Triple("A major", 2, hotel.toList()) to ("A" to "B"),
            Triple("A", 2, emptyList<String>()) to ("A" to "B"),
            Triple("A dorian", 0, hotel.toList()) to ("A dorian" to "A dorian"),
        )) {
            val (text, capo, names) = case
            val played = chords(*names.toTypedArray())
            val key = Theory.shapesKey(Theory.namedKey(text, capo, played)!!, capo, played)
            assertEquals(want, Theory.keyName(key) to Theory.keyName(Theory.sounding(key, capo)), "$case")
        }
        assertNull(Theory.namedKey("Standard", 2, chords(*hotel)))
        assertNull(Theory.namedKey(null, 0, chords(*hotel)))
        assertEquals(Key(7, "ionian"), Theory.estimateKey(chords("G", "C", "D", "Em", "G")))
        assertNull(Theory.estimateKey(emptyList()))
    }

    @Test fun aModeChangeMovesEachNoteToTheSameDegree() {
        val cMinor = Key(0, "aeolian")
        assertEquals("Am", named(Theory.mapChord(Theory.parseChord("Ab")!!, cMinor, "ionian")))
        assertEquals("Bm7b5", named(Theory.mapChord(Theory.parseChord("Bb7")!!, cMinor, "ionian")))
        val g = Theory.parseChord("G")!!
        assertSame(g, Theory.mapChord(g, cMinor, "ionian"))
        val am = Theory.parseChord("Am7")!!
        assertSame(am, Theory.mapChord(am, Key(0, "ionian"), "ionian"))
    }

    @Test fun alternativesAndCapoHints() {
        val gMajor = Key(7, "ionian")
        // colours on its root, its root position, then chords on other roots, a third below first
        assertEquals(listOf("D7", "Dadd9", "Dsus2", "D6", "D", "Bm7", "Bm", "F#dim"),
                     Theory.alternatives(Theory.parseChord("D/F#")!!, gMajor).map { named(it, gMajor) })
        assertEquals(listOf(1 to "A", 3 to "G"), Theory.capoHints(Key(10, "ionian")).map { it.first to Theory.keyName(it.second) })
        assertEquals(listOf(0 to "G", 3 to "E"),
                     Theory.capoHints(Key(5, "ionian"), capo = 2).map { it.first to Theory.keyName(it.second) })
        assertEquals(emptyList(), Theory.capoHints(Key(7, "ionian")))
    }

    @Test fun chordsAndKeysAreFrozenAndEveryListHandedOutIsACopy() {
        val tones = mutableSetOf(0, 4, 7, 11)
        val chord = Chord(0, "x", tones = tones)
        tones += 2
        assertEquals(setOf(0, 4, 7, 11), chord.tones)
        assertFailsWith<UnsupportedOperationException> { (chord.tones as MutableSet<Int>).add(5) }
        assertFailsWith<UnsupportedOperationException> { (chord.intervals as MutableSet<Int>).add(5) }
        assertFailsWith<UnsupportedOperationException> { (chord.pitchClasses as MutableSet<Int>).add(5) }
        assertFailsWith<UnsupportedOperationException> { (Theory.QUALITIES as MutableMap<String, Set<Int>>).clear() }
        assertFailsWith<UnsupportedOperationException> { (Theory.QUALITIES.getValue("m") as MutableSet<Int>).clear() }
        assertFailsWith<UnsupportedOperationException> { (Theory.MODES as MutableList<String>).clear() }
        assertFailsWith<UnsupportedOperationException> { (Theory.SCALES.getValue("ionian") as MutableList<Int>).clear() }
        assertEquals(Chord(0, "x", null, null, setOf(11, 7, 4, 0)), chord)
        assertEquals(chord.hashCode(), Chord(0, "x", tones = linkedSetOf(11, 7, 4, 0)).hashCode())
        assertNotEquals(Chord(0, "maj7", shown = "M7"), Chord(0, "maj7", shown = "maj7"))
        assertEquals(Chord(2, "m", 5), Chord(2, "m").copy(bass = 5))

        val gMajor = Key(7, "ionian")
        val dOverFSharp = Theory.parseChord("D/F#")!!
        val alts = Theory.alternatives(dOverFSharp, gMajor)
        for (got in listOf(Theory.alternatives(dOverFSharp, gMajor), Theory.spelling(gMajor), Theory.spelling(null),
                           Theory.capoHints(Key(10, "ionian")), Theory.capoHints(Key(5, "ionian"), capo = 2))) {
            (got as MutableList<*>).clear()
        }
        assertEquals(alts, Theory.alternatives(dOverFSharp, gMajor))
        assertEquals("C C# D Eb E F F# G Ab A Bb B".split(" "), Theory.spelling(gMajor))
        assertEquals("C C# D Eb E F F# G Ab A Bb B".split(" "), Theory.spelling(null))
        assertEquals(listOf(1, 3), Theory.capoHints(Key(10, "ionian")).map { it.first })
        assertEquals(listOf(0, 3), Theory.capoHints(Key(5, "ionian"), capo = 2).map { it.first })
        assertTrue(alts.isNotEmpty())
    }

    /** Python's errors: MODES.index's ValueError an IllegalArgumentException, a dict's KeyError a
     * NoSuchElementException. */
    @Test fun aModeNoKeyHasIsPythonsError() {
        assertFailsWith<IllegalArgumentException> { Theory.spelling(Key(0, "minor")) }
        assertFailsWith<NoSuchElementException> { Theory.scale(Key(0, "major")) }
        assertFailsWith<NoSuchElementException> { Chord(0, "nope").intervals }
    }
}
