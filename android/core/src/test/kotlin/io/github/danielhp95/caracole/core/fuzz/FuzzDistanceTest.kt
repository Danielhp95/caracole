package io.github.danielhp95.caracole.core.fuzz

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.MatchReplay
import org.junit.Test
import kotlin.test.assertEquals

/** core.fuzz's distances as rapidfuzz 3.14.5 answers them (vectors/fuzz/osa.jsonl, osa_extract.jsonl and
 * token_set.jsonl), and their rules by hand. */
class FuzzDistanceTest {
    @Test fun osaAndTokenSetAreRapidfuzzsOnEveryRecord() {
        val misses = Misses("fuzz: OSA and token_set")
        MatchReplay.fuzzDistances(misses)
        misses.assertNone()
    }

    @Test fun twoLettersSwappedAreOneEditButNeverEditedAgain() {
        assertEquals(1, Fuzz.osaDistance("coldplya", "coldplay"))
        assertEquals(1, Fuzz.osaDistance("ab", "ba"))
        assertEquals(3, Fuzz.osaDistance("ca", "abc"))  // Damerau's unrestricted distance is 2
        assertEquals(2, Fuzz.osaDistance("abc", "", scoreCutoff = 1))  // past the cutoff: the cutoff plus one
        assertEquals(1, Fuzz.osaDistance("😀a", "a😀"))  // a code point is one character
    }

    @Test fun theTypoRoutesExtractIsTheNearestFirstThenByIndex() {
        val got = Fuzz.extractDistance("tolo", listOf("colo", "lolo", "tool", "tolo", "x"), 1)
        assertEquals(listOf(Fuzz.ExtractedDistance("tolo", 0, 3), Fuzz.ExtractedDistance("colo", 1, 0),
                            Fuzz.ExtractedDistance("lolo", 1, 1), Fuzz.ExtractedDistance("tool", 1, 2)), got)
    }

    @Test fun tokenSetIsAHundredWhenOnesWordsAreAllTheOthers() {
        assertEquals(100.0, Fuzz.tokenSetRatio("fuzzy was a bear", "fuzzy fuzzy was a bear"))
        assertEquals(100.0, Fuzz.tokenSetRatio("a b c", "a b"))
        assertEquals(0.0, Fuzz.tokenSetRatio("", "a"))
        assertEquals(33.33333333333333, Fuzz.tokenSetRatio("x y", "z w"))
    }
}
