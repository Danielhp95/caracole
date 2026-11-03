package io.github.danielhp95.caracole.core.keys

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** normalize.py's patterns as Python's re reads them, through core.py.PyRegex: each answer here is Python's. */
class KeyPatternTest {
    private val live = KeyTables.pattern("_LIVE_WORD")
    private val acoustic = KeyTables.pattern("_ACOUSTIC_WORD")
    private val dashSuffix = KeyTables.pattern("_DASH_SUFFIX")

    @Test fun everyPatternOfNormalizeAndLibraryCompiles() {
        val patterns = Json.parseToJsonElement(KeyTables.text("tables.json")).jsonObject.getValue("patterns").jsonObject
        assertEquals(setOf("_DASH_SUFFIX", "_PAREN_FEAT", "_PAREN_SUFFIX", "_ACOUSTIC_WORD", "_LIVE_WORD", "_PART_BREAK",
            "_FEATURING", "_BRACKETED", "_MORA", "_RESERVED"), patterns.keys)
        for (name in patterns.keys) assertTrue(KeyTables.pattern(name).regex.pattern.isNotEmpty(), name)
    }

    @Test fun ignoreCaseMatchesSresOddLetters() {
        assertTrue(live.search("Hysteria - lıve"))  // ı
        assertTrue(live.search("SONG (LİVE)"))  // İ
        assertEquals("Song", dashSuffix.sub("Song - ſtereo"))  // ſ
        assertEquals("Song", dashSuffix.sub("Song - Bonus TracK"))  // the Kelvin sign
        assertTrue(acoustic.search("ACÚSTICO"))
        assertTrue(acoustic.search("acustica"))
    }

    @Test fun wordBoundariesReadTheTextAsItIs() {
        assertFalse(live.search("aLIVEb"))
        assertFalse(live.search("a_live"))
        assertFalse(live.search("a ſtereo"))
    }

    @Test fun dotDollarAndDigitsAreOnPythonsTerms() {
        assertEquals("Song", dashSuffix.sub("Song - Live\n"))  // $ before a final \n
        assertEquals("Song", dashSuffix.sub("Song - Live\nmore"))  // \s takes the \n, then .* the rest
        assertEquals("Song", dashSuffix.sub("Song - Remaster ２０１１"))  // \d is Unicode's digits
    }

    @Test fun splitSubAndMatchAtStepAsPythonsRe() {
        assertEquals(listOf("宋冬野", "斑马", "Zebra", "a", "b"), KeyTables.pattern("_PART_BREAK").split("宋冬野 - 斑马（Zebra）a / b"))
        assertEquals("abcdefgh", KeyTables.pattern("_RESERVED").sub("a*b?c\"d<e>f|g\u0000\u001f\u007fh"))
        val mora = KeyTables.pattern("_MORA")
        assertEquals(listOf(1, 2, 5), listOf(0, 1, 2).map { mora.matchEnd("itchisuru", it) })
        assertEquals(1, mora.matchEnd("nna", 0))
        assertEquals(1, mora.matchEnd("kka", 0))
        assertNull(mora.matchEnd("x", 5))
    }
}
