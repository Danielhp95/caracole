package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonyReplay
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harmony's progressions answer as viewer/harmony.py's: every record of vectors/viewer/harmony_progressions.jsonl
 * (HarmonyReplay), and tests/test_viewer_harmony.py's progression cases, by hand. */
class ProgressionsTest {
    private val c = Key(0, "ionian")
    private val aMinor = Key(9, "aeolian")
    private val g = Key(7, "ionian")

    @Test fun everyRecordIsHarmonyPys() {
        val misses = Misses("harmony progressions")
        HarmonyReplay.progressions(misses)
        misses.assertNone()
    }

    private fun ch(name: String): Chord = Theory.parseChord(name) ?: throw AssertionError("no chord $name")

    private fun section(names: String): List<Chord?> = names.trim().split(Regex(" +")).filter { it.isNotEmpty() }
        .map { if (it == "N.C.") null else ch(it) }

    private fun named(names: String, key: Key): Progression {
        val found = Harmony.progressions(listOf("Verse" to section(names)), key)
        assertEquals(1, found.size, names)
        return found[0].second
    }

    @Test fun thePopProgressionIsNamedInEveryTurnAndKey() {
        val pop = listOf("C", "G", "Am", "F").map(::ch)
        for (tonic in 0 until 12) {
            val chords = pop.map { Chord(Math.floorMod(it.root + tonic, 12), it.quality) }
            for (turn in 0 until 4) {
                val turned = chords.drop(turn) + chords.take(turn)
                val found = Harmony.progressions(listOf("Chorus" to turned), Key(tonic, "ionian"))
                assertEquals(listOf("Chorus" to "the pop progression"), found.map { (n, p) -> n to p.name })
            }
        }
        val minor = named("Am F C G", aMinor)
        assertEquals(listOf("i", "♭VI", "♭III", "♭VII") to "the pop progression", minor.numerals to minor.name)
    }

    @Test fun repeatsAreFoldedAndAChordHeldIsOne() {
        assertEquals(Progression(listOf("vi", "IV", "I", "V"), 4, "the pop progression", "half"), named("Am F C G ".repeat(4), c))
        val held = named("C C G G Am Am F F", c)
        assertEquals(listOf("I", "V", "vi", "IV") to 1, held.numerals to held.repeats)
        assertEquals(Progression(listOf("i", "♭VII", "♭VI", "V"), 1, "the Andalusian cadence", "half"), named("Am G F E", aMinor))
    }

    @Test fun theCatalogue() {
        for ((names, key, name) in listOf(
            Triple("C Am F G", c, "the '50s progression"), Triple("Dm7 G7 Cmaj7", c, "ii–V–I"),
            Triple("Bm7b5 E7 Am", aMinor, "the minor ii–V–i"), Triple("C F G", c, "I–IV–V"),
            Triple("C Bb F", c, "the double-plagal progression"), Triple("Am Dm G C", c, "the circle of fifths"),
            Triple("C G Am Em F C F G", c, "Pachelbel's Canon"), Triple("E7 A7 D7 G7", c, "the ragtime progression"),
            Triple("F G Em Am", c, "the royal road"), Triple("C Dm Em F", c, null),
            Triple("C E7 A7 D7 G7 C", c, "the ragtime progression"), Triple("Am G F E", c, "the Andalusian cadence"),
            Triple("Am Dm G C", aMinor, "the circle of fifths"), Triple("F G Em Am", aMinor, "the royal road"),
            Triple("C G Am F C", c, "the pop progression"), Triple("C G F C F", c, null),
            Triple("C7 F7 C7 G7 F7 C7", c, "the 12-bar blues"), Triple("C F C G F C", c, "the 12-bar blues"),
            Triple("G B C Cm", g, "the Creep progression"), Triple("G Bm C Cm", g, null),
            Triple("Am G F G", aMinor, "the Aeolian shuttle"), Triple("Am G F Em ".repeat(2), aMinor, "the lament"),
        )) assertEquals(name, named(names, key).name, names)
    }

    @Test fun howASectionEnds() {
        for ((names, ending) in listOf("Dm G C" to "authentic", "C F C" to "plagal", "C F G" to "half",
                                       "C F G Am" to "deceptive", "C Am" to null, "G" to null)) {
            assertEquals(ending, named(names, c).ending, names)
        }
        assertEquals("authentic", named("Am E Am", aMinor).ending)
    }

    @Test fun sectionsKeepTheirOrderAndOneWithNoChordHasNone() {
        val found = Harmony.progressions(listOf("Intro" to emptyList(), "Verse" to section("C G"),
                                                "Bridge" to section("N.C."), "Chorus" to section("Am F")), c)
        assertEquals(listOf("Verse", "Chorus"), found.map { it.first })
        assertEquals(emptyList(), Harmony.progressions(emptyList(), c))
        // A secondary dominant reads the next section's first chord.
        val across = Harmony.progressions(listOf("Verse" to section("C D"), "Chorus" to section("G C")), c)
        assertEquals(listOf("I", "V/V"), across[0].second.numerals)
        assertEquals(listOf("I", "V/V", "V7/V", "V"), named("C D D7 G", c).numerals)
    }

    @Test fun wonderwallsVerseFoldsWithItsOneVariation() {
        val verse = "Em7 G Dsus4 A7sus4 ".repeat(3) + "Cadd9 Dsus4 A7sus4 " + "Em7 G Dsus4 A7sus4 ".repeat(4)
        assertEquals(Progression(listOf("i7", "♭III", "♭VIIsus4", "IV7sus4"), 8, null, null, variations = 1),
                     named(verse, Key(4, "aeolian")))
        val pre = named("Cadd9 Dsus4 Em7 ".repeat(3) + "Cadd9 Dsus4 G G/F# Em7 Dsus4/F# A7sus4", Key(4, "aeolian"))
        assertEquals(listOf(Contained("the Aeolian cadence", 3, listOf("♭VIadd9", "♭VIIsus4", "i7"), "i ♭VI ♭VII")), pre.contains)
    }

    @Test fun aProgressionWithinALongerSectionIsNamedWithItsTimes() {
        val found = named("Dm C G Am F Bb C G Am F", c)
        assertEquals(null to 1, found.name to found.repeats)
        assertEquals(listOf(Contained("the pop progression", 2, listOf("I", "V", "vi", "IV"), "I V vi IV")), found.contains)
        assertEquals(listOf("ii–V–I" to 1, "the Andalusian cadence" to 2),
                     named("Dm7 G7 Cmaj7 Am G F E7 Am G F E7", c).contains.map { it.name to it.times })
        assertEquals(listOf("the 12-bar blues" to 2),
                     named("C7 F7 C7 G7 F7 C7 F7 C7 G7 F7 C7 Am", c).contains.map { it.name to it.times })
        val whole = named("Am F C G ".repeat(2), c)
        assertEquals("the pop progression" to emptyList(), whole.name to whole.contains)
        val each = named("Dm7 G7 Cmaj7 A7 ".repeat(4), c)
        assertEquals(4 to listOf(Contained("ii–V–I", 4, listOf("ii7", "V7", "Imaj7"), "I ii V")), each.repeats to each.contains)
    }

    @Test fun noNameForAVampOrATurnItsSourcesDontGive() {
        for ((names, key) in listOf("G D C G D C G D" to g, "C G F ".repeat(3) to c, "Em Am F G" to c,
                                    "C Am Dm G" to c, "G C Am Dm" to c, "C Am Dm G ".repeat(4) + "C" to c,
                                    "G C Dm ".repeat(2) to c, "F G Am G" to c, "F Em7 A7 Dm Dm/C Bb C7 F" to Key(5, "ionian"))) {
            val found = named(names, key)
            assertEquals(null to emptyList(), found.name to found.contains.map { it.name }, names)
        }
        assertEquals(listOf("I–IV–V"), named("C F G Am G F C", c).contains.map { it.name })
    }

    @Test fun aSectionsRepeatsFoldEvenWhenOnePassVariesAChord() {
        val found = named("C G Am F ".repeat(3) + "C G Am Dm", c)
        assertEquals(listOf(listOf("I", "V", "vi", "IV"), 4, 1, "the pop progression"),
                     listOf(found.numerals, found.repeats, found.variations, found.name))
        assertEquals(1, named("C G Am F ".repeat(2) + "C G Em Am F " + "C G Am F", c).variations)
        assertEquals(1, named("C G Am F ".repeat(2) + "C Am F " + "C G Am F", c).variations)
        val other = named("C G Am F ".repeat(3) + "Dm G C F", c)
        assertEquals(listOf(1, 0), listOf(other.repeats, other.variations))
        assertEquals(listOf("the pop progression", "ii–V–I"), other.contains.map { it.name })
        val twice = named("C G Am F ".repeat(4) + "C G Am Dm " + "C G Am F " + "C G Am Dm", c)
        assertEquals(7 to 2, twice.repeats to twice.variations)
        assertEquals(1, named("C G Am F C G Am Em", c).repeats)
        val home = named("C G Am F ".repeat(2) + "C", c)
        assertEquals(Triple(listOf("I", "V", "vi", "IV"), 2, 0), Triple(home.numerals, home.repeats, home.variations))
    }

    @Test fun aProgressionsKeyIsTheSameForEveryTurnAndRepeat() {
        val pop = Harmony.progressionKey(listOf("I", "V", "vi", "IV"))
        assertEquals("I V vi IV", pop)
        assertEquals(pop, Harmony.progressionKey(listOf("vi", "IV", "I", "V")))
        assertEquals(pop, Harmony.progressionKey(listOf("IV", "I", "V", "vi", "IV", "I", "V", "vi")))
        assertEquals(pop, Harmony.progressionKey(listOf("Imaj7", "V7", "vi7", "IVadd9")))
        assertEquals(pop, Harmony.progressionKey("vi IV I V"))
        assertEquals(pop, Harmony.progressionKey("vi–IV–I–V"))
        assertEquals(pop, Harmony.progressionKey("I V vi IV I"))
        assertEquals("I", Harmony.progressionKey("I I"))
        assertEquals(Harmony.progressionKey(listOf("bVII", "IV", "I")), Harmony.progressionKey(listOf("I", "♭VII", "IV")))
        assertNotEquals(pop, Harmony.progressionKey(listOf("I", "vi", "IV", "V")))
        assertNotEquals(Harmony.progressionKey(listOf("V7/V", "V", "I")), Harmony.progressionKey(listOf("V", "V", "I")))
        assertEquals(Harmony.progressionKey(listOf("I", "IV", "V")), Harmony.progressionKey(listOf("I", "V7/IV", "IV", "V")))
        assertEquals("", Harmony.progressionKey(""))
    }

    @Test fun aKeyTurnsWhereItsNumeralsSortFirstByCodePoint() {
        // Python compares str by code point: U+FFFD sorts before U+1F600, which UTF-16 units would put first.
        assertEquals("� 😀", Harmony.progressionKey(listOf("😀", "�")))
    }

    @Test fun typedNumeralsAreNamedAsASectionIs() {
        for (typed in listOf("I V IV I V IV I V", "iii vi IV V", "IV V vi V", "I vi ii V", "V I vi ii")) {
            assertNull(Harmony.nameOf(typed), typed)
        }
        assertEquals("the pop progression", Harmony.nameOf("vi IV I V"))
        assertEquals("the Aeolian shuttle", Harmony.nameOf("i bVII bVI bVII"))
        assertEquals(listOf("i", "♭VII", "♭VI", "♭VII"), Harmony.readTyped("i VII VI VII"))
        assertEquals(listOf("i7", "iv", "♭VII7"), Harmony.readTyped("i7–iv–VII7"))
        assertEquals("the circle of fifths", Harmony.nameOf("i–iv–VII–III–VI–ii°–V–i"))
        assertEquals("the Andalusian cadence", Harmony.nameOf("i VII VI V"))
        assertEquals("the lament", Harmony.nameOf("i VII VI v"))
        assertEquals(listOf("I", "VII", "IV"), Harmony.readTyped("I VII IV"))
        assertNull(Harmony.nameOf("I VII IV"))
        assertEquals(listOf("i", "bVII", "VI"), Harmony.readTyped(listOf("i", "bVII", "VI")))
        for ((name, numerals, _) in HarmonyProgressions.CATALOGUE) assertEquals(name, Harmony.nameOf(numerals), name)
    }

    @Test fun theCatalogueKeysEachReadingByItsKey() {
        val keys = Harmony.catalogue()
        assertEquals("the pop progression", keys["I V vi IV"])
        assertEquals("the pop progression", keys["i ♭VI ♭III ♭VII"])
        assertEquals("I V vi IV", keys.keys.first())
    }

    @Test fun answersAreFrozenAndAListHandedOutIsACopy() {
        val sections = listOf("Verse" to section("C G"))
        val found = Harmony.progressions(sections, c)
        (found as MutableList).clear()
        assertTrue(Harmony.progressions(sections, c).isNotEmpty())
        val p = Harmony.progressions(sections, c)[0].second
        assertFailsWith<UnsupportedOperationException> { (p.numerals as MutableList).clear() }
        val keys = Harmony.catalogue()
        (keys as MutableMap).clear()
        assertTrue(Harmony.catalogue().isNotEmpty())
        val typed = Harmony.readTyped("i VII")
        (typed as MutableList).clear()
        assertEquals(listOf("i", "♭VII"), Harmony.readTyped("i VII"))
    }
}
