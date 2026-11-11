package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonyReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harmony's chord half answers as viewer/harmony.py: every record of vectors/viewer/harmony_chords.jsonl
 * (HarmonyReplay), and test_viewer_harmony.py's own cases, by hand. */
class HarmonyTest {
    private val c = Key(0, "ionian")
    private val aMinor = Key(9, "aeolian")

    @Test fun everyRecordIsHarmonyPys() {
        val misses = Misses("harmony")
        HarmonyReplay.chords(misses)
        misses.assertNone()
    }

    private fun ch(name: String): Chord = Theory.parseChord(name) ?: throw AssertionError("no chord $name")

    /** Each chord's numeral, each read with the next one as the chord it goes to. */
    private fun texts(names: String, key: Key): List<String> {
        val chords = names.split(" ").map(::ch)
        return chords.mapIndexed { i, chord -> Harmony.numeral(chord, key, chords.getOrNull(i + 1)).text }
    }

    /** The pitch class of a note's name, double sharps and flats too: "B#" is 0, "Ebb" is 2. */
    private fun pc(name: String): Int =
        Math.floorMod(Theory.NATURAL.getValue(name.substring(0, 1)) + name.count { it == '#' } - name.count { it == 'b' }, 12)

    @Test fun cMajorsTriadsAndSevenths() {
        assertEquals("I ii iii IV V vi vii°".split(" "), texts("C Dm Em F G Am Bdim", c))
        assertEquals("Imaj7 ii7 iii7 IVmaj7 V7 vi7 viiø7".split(" "), texts("Cmaj7 Dm7 Em7 Fmaj7 G7 Am7 Bm7b5", c))
    }

    @Test fun aMinorsTriadsAreWrittenAgainstTheMajorScaleAndItsDominantIsMajor() {
        assertEquals("i ii° ♭III iv v ♭VI ♭VII".split(" "), texts("Am Bdim C Dm Em F G", aMinor))
        assertEquals("V7", Harmony.numeral(ch("E7"), aMinor).text)
        assertEquals(Relation("in", null, null), Harmony.relation(ch("E7"), aMinor))
        assertEquals("vii°7", Harmony.numeral(ch("G#dim7"), aMinor).text)
    }

    @Test fun theNumeralsFields() {
        assertEquals(Numeral("♭", "VII", "", "", null, null), Harmony.numeral(ch("Bb"), c))
        assertEquals(Numeral("", "vii", "ø", "7", null, null), Harmony.numeral(ch("Bm7b5"), c))
        assertEquals(Numeral("", "I", "+", "", null, null), Harmony.numeral(ch("Caug"), c))
        assertEquals("V/V/3", Numeral("", "V", "", "", "3", "V").text)
    }

    @Test fun extensionsAreWrittenAsTheChordNameHasThem() {
        for ((name, text) in listOf(
            "C5" to "I5", "Csus4" to "Isus4", "C6" to "I6", "Cadd9" to "Iadd9", "Am6" to "vi6", "G9" to "V9",
            "G7sus4" to "V7sus4", "Dm9" to "ii9", "C6/9" to "I69", "Am(maj7)" to "vimaj7", "G7b9" to "V7♭9",
            "Cmaj7#11" to "Imaj7♯11",
        )) assertEquals(text, Harmony.numeral(ch(name), c).text, name)
        assertEquals("I", Harmony.numeral(Theory.parseChord("Cfoo", strict = false)!!, c).text)
        assertEquals("vi", Harmony.numeral(Theory.parseChord("Amfoo", strict = false)!!, c).text)
    }

    @Test fun aSlashChordsBassIsItsDegreeAboveTheChordsRootChordToneOrNot() {
        for ((name, text) in listOf("C/E" to "I/3", "C/D" to "I/2", "G/F" to "V/♭7", "G7/F" to "V7/♭7",
                                    "Am/C" to "vi/♭3", "C/C" to "I", "Cadd9/D" to "Iadd9/2")) {
            assertEquals(text, Harmony.numeral(ch(name), c).text, name)
        }
        assertNull(Harmony.numeral(ch("C/C"), c).bass)
    }

    @Test fun theTwoWayReadingsOfHarmonysDocstring() {
        // B♭ in C is borrowed from C minor, not C Mixolydian's ♭VII.
        assertEquals(Relation("borrowed", "C minor", null), Harmony.relation(ch("Bb"), c, ch("C")))
        // D in C is V/V only going to G; going elsewhere, C Lydian's II.
        assertEquals("V/V", Harmony.numeral(ch("D"), c, ch("G")).text)
        assertEquals(Relation("borrowed", "C Lydian", null), Harmony.relation(ch("D"), c, ch("C")))
        // C7 in C is V7/IV only going to an F that is no dominant seventh: a blues's C7 F7 stays I7 IV7.
        assertEquals("I Imaj7 V7/IV IV".split(" "), texts("C Cmaj7 C7 F", c))
        assertEquals("I7", Harmony.numeral(ch("C7"), c, ch("F7")).text)
        assertEquals(Relation("borrowed", "C Mixolydian", null), Harmony.relation(ch("C7"), c, ch("F7")))
        assertEquals("i V7/iv iv".split(" "), texts("Am A7 Dm", aMinor))
    }

    @Test fun secondaryAndLeadingToneChords() {
        assertEquals(Relation("secondary", null, "G"), Harmony.relation(ch("D7"), c, ch("G")))
        assertEquals("V/V/3", texts("D/F# G", c)[0])
        assertEquals("V/vi", Harmony.numeral(ch("E"), c, ch("F")).text)  // in no mode on C: secondary wherever it goes
        assertEquals("V7/♭III", texts("G7 C", aMinor)[0])
        assertEquals("♭VII7", texts("G7 Am", aMinor)[0])
        assertEquals("vii°7/ii", texts("C#dim7 Dm", c)[0])
        assertEquals(Relation("leading", null, "Dm"), Harmony.relation(ch("C#dim7"), c, ch("Dm")))
        assertEquals("viiø7/V", texts("F#m7b5 G", c)[0])
    }

    @Test fun borrowedAndOutside() {
        for ((name, text) in listOf("Eb" to "♭III", "Ab" to "♭VI", "Fm" to "iv", "Ddim" to "ii°", "Bdim7" to "vii°7")) {
            assertEquals(text, Harmony.numeral(ch(name), c).text, name)
            assertEquals(Relation("borrowed", "C minor", null), Harmony.relation(ch(name), c), name)
        }
        assertEquals("C Phrygian", Harmony.relation(ch("Db"), c).source)
        assertEquals("A Dorian", Harmony.relation(ch("D"), aMinor).source)
        assertEquals("A major", Harmony.relation(ch("A"), aMinor).source)
        assertEquals("Eb minor", Harmony.relation(ch("Db"), Key(3, "ionian")).source)
        assertEquals(Relation("outside", null, null), Harmony.relation(ch("F#"), c))
        assertEquals("♯IV", Harmony.numeral(ch("F#"), c).text)
        assertEquals("♭V", Harmony.numeral(ch("Eb"), aMinor).text)
    }

    @Test fun families() {
        assertEquals(listOf("home", "home", "home", "away", "away", "pull", "pull"),
                     "C Em Am F Dm G Bdim".split(" ").map { Harmony.family(ch(it), c) })
        assertEquals(listOf("home", "home", "home", "away", "away", "pull", "pull"),
                     "Am C F Dm Bdim E7 G".split(" ").map { Harmony.family(ch(it), aMinor) })
        assertNull(Harmony.family(ch("Bb"), c))
    }

    @Test fun explainSaysTheDegreeTheQualityTheBassAndTheKey() {
        assertEquals("vi: the 6th chord of C major, minor (lower case)", Harmony.explain(ch("Am"), c))
        assertEquals("♭VII: on the lowered 7th degree of C major, major (upper case); borrowed from C minor",
                     Harmony.explain(ch("Bb"), c))
        assertEquals("V/V: the V of V in C major, major (upper case); leads to G", Harmony.explain(ch("D"), c, ch("G")))
        assertEquals("V/vi: the V of vi in C major, major (upper case); points to Am", Harmony.explain(ch("E"), c, ch("F")))
        assertEquals("V7: the 5th chord of C major, major (upper case) with a 7th (7)", Harmony.explain(ch("G7"), c))
        assertEquals("I/2: the 1st chord of C major, major (upper case); D in the bass, the 2nd above its root, " +
                         "outside the chord", Harmony.explain(ch("C/D"), c))
        assertTrue(Harmony.explain(ch("Cadd9/D"), c).endsWith("; D in the bass, its 9th"))
    }

    @Test fun theGlossaryListsOnlyTheSymbolsTheChordsUse() {
        val plain = Harmony.glossary(listOf(ch("C"), ch("Am"), ch("G7"), ch("C")), c)
        assertEquals(listOf("I–VII", "I", "i", "7"), plain.map { it.first })
        assertEquals("G7 = V7", plain[3].third)
        val rich = Harmony.glossary("C Bb D7 G C/E Bm7b5 E Am".split(" ").map(::ch), c)
        assertEquals(listOf("I–VII", "I", "i", "♭", "ø", "7", "/3", "V/x"), rich.map { it.first })
        assertEquals("D7 = V7/V", rich.first { it.first == "V/x" }.third)
        assertEquals(emptyList(), Harmony.glossary(emptyList(), c))
        assertEquals("G#dim7 = vii°7/vi", Harmony.glossary(listOf(ch("G#dim7"), ch("Am")), c).first { it.first == "vii°/x" }.third)
    }

    @Test fun chordTonesAndScalesKeepOneLetterADegree() {
        assertEquals(listOf("C" to "R", "E" to "3", "G" to "5", "Bb" to "♭7"), Harmony.chordTones(ch("C7"), c))
        assertEquals(listOf("A" to "R", "C" to "♭3", "Eb" to "♭5", "G" to "♭7"), Harmony.chordTones(ch("Am7b5"), null))
        assertEquals(listOf("C" to "R", "D" to "2", "E" to "3", "G" to "5"), Harmony.chordTones(ch("C/D"), c))
        assertEquals(listOf("C#" to "R", "E" to "♭3", "G" to "♭5", "B" to "♭7"), Harmony.chordTones(ch("C#m7b5"), c))
        assertEquals(listOf("G#" to "R", "B#" to "3", "D#" to "5", "F#" to "♭7"), Harmony.chordTones(ch("G#7"), Key(1, "aeolian")))
        assertEquals(listOf("G#" to "R", "B" to "♭3", "D" to "♭5", "F" to "♭♭7"), Harmony.chordTones(ch("G#dim7"), c))
        assertEquals("D Dorian" to "D E F G A B C".split(" "), Harmony.soloScale(ch("Dm7"), c))
        assertEquals("Bb Mixolydian" to "Bb C D Eb F G Ab".split(" "), Harmony.soloScale(ch("Bb"), c))
        assertEquals("E Phrygian dominant" to "E F G# A B C D".split(" "), Harmony.soloScale(ch("E7"), aMinor))
        assertEquals("C melodic minor" to "C D Eb F G A B".split(" "), Harmony.soloScale(ch("Cm(maj7)"), c))
        assertEquals("C# diminished (whole-half)", Harmony.soloScale(ch("C#dim7"), c).first)
        assertEquals("Db Mixolydian" to "Db Eb F Gb Ab Bb Cb".split(" "), Harmony.soloScale(ch("Db"), Key(3, "ionian")))
    }

    @Test fun everyQualityGetsANumeralAnExplanationAndAScaleThatHoldsIt() {
        for (root in listOf(0, 2, 6)) for (quality in Theory.QUALITIES.keys) {
            val chord = Chord(root, quality)
            val text = Harmony.numeral(chord, c).text
            assertTrue(Harmony.explain(chord, c).startsWith("$text: "), "$chord")
            assertTrue(Harmony.soloScale(chord, c).second.map(::pc).containsAll(chord.pitchClasses), "$chord")
            assertEquals(chord.pitchClasses, Harmony.chordTones(chord, c).map { pc(it.first) }.toSet(), "$chord")
        }
    }

    @Test fun theKeysScaleAndItsPentatonic() {
        assertEquals(listOf(0, 2, 4, 5, 7, 9, 11), Harmony.keyScale(c))
        assertEquals(listOf(9, 11, 0, 2, 4, 5, 7), Harmony.keyScale(aMinor))
        assertEquals(listOf(0, 2, 4, 7, 9), Harmony.pentatonic(c))
        assertEquals(listOf(9, 0, 2, 4, 7), Harmony.pentatonic(aMinor))
        for (mode in Theory.MODES) for (tonic in 0 until 12) {
            val key = Key(tonic, mode)
            assertTrue(Theory.scale(key).containsAll(Harmony.pentatonic(key)) && Harmony.pentatonic(key).size == 5)
            assertEquals(Theory.scale(key), Harmony.keyScale(key).toSet())
        }
    }

    @Test fun eachChordGoesToTheNextOnAnotherRoot() {
        val chords = "D D7 G G7 C".split(" ").map(::ch)
        assertEquals(listOf(ch("G"), ch("G"), ch("C"), ch("C"), null), Harmony.goesTo(chords))
        assertEquals(emptyList(), Harmony.goesTo(emptyList()))
    }

    @Test fun answersAreKeptAndAListHandedOutIsACopy() {
        val first = Harmony.glossary(listOf(ch("C"), ch("G")), c)
        (first as MutableList).clear()
        assertTrue(Harmony.glossary(listOf(ch("C"), ch("G")), c).isNotEmpty())
        val tones = Harmony.chordTones(ch("C"), c)
        (tones as MutableList).add("X" to "?")
        assertEquals(listOf("C" to "R", "E" to "3", "G" to "5"), Harmony.chordTones(ch("C"), c))
        val scale = Harmony.soloScale(ch("C"), c).second
        (scale as MutableList).clear()
        assertEquals(7, Harmony.soloScale(ch("C"), c).second.size)
        val chords = mutableListOf(ch("C"), ch("G"))
        val before = Harmony.glossary(chords, c)
        chords.add(ch("Bb"))  // the list asked with, changed after, changes nothing kept
        assertEquals(before, Harmony.glossary(listOf(ch("C"), ch("G")), c))
        assertEquals(Harmony.explain(ch("D"), c, ch("G")), Harmony.explain(ch("D"), c, ch("G")))
    }

    @Test fun whatTheChordHalfKeepsNoCallerCanChange() {
        // harmony-progressions' tables call HarmonyChords itself, past Harmony's copies: what it keeps is as frozen
        // as Python's tuples.
        val kept = listOf(
            HarmonyChords.glossary(listOf(ch("C"), ch("G7")), c),
            HarmonyChords.chordTones(ch("G7"), c),
            HarmonyChords.soloScale(ch("G7"), c).second,
        )
        for (list in kept) {
            assertFailsWith<UnsupportedOperationException> { (list as MutableList<*>).clear() }
        }
        assertFailsWith<UnsupportedOperationException> {
            @Suppress("UNCHECKED_CAST")
            (HarmonyChords.toneNames(ch("G7")) as MutableMap<Int, String>).clear()
        }
    }

    @Test fun aModeHarmonyHasNoWordForIsCapitalizedAsPythonDoes() {
        assertEquals("Dorian", HarmonyChords.modeWord("dorian"))
        // str.capitalize's title case (U+01C5, Python's "ǆorian".capitalize()), never the upper case U+01C4
        assertEquals("\u01C5orian", HarmonyChords.modeWord("\u01C6orian"))
    }
}
