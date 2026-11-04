package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** PyHtml.unescape against html.unescape (vectors/py/sites_unescape.jsonl: every HTML5 name, every numeric
 * reference to U+10FFFF and past it), and the cases a corpus line can't hold. */
class PyHtmlTest {
    @Test fun everyRecordAnswersAsHtmlUnescapeDid() = PyReplay.unescape()

    @Test fun aNameWithoutItsSemicolonIsReadByItsLongestLegacyPrefix() {
        assertEquals("¬it;", PyHtml.unescape("&notit;"))
        assertEquals("∉", PyHtml.unescape("&notin;"))
        assertEquals("&x;", PyHtml.unescape("&ampx;"))
        assertEquals("&nope;", PyHtml.unescape("&nope;"))
    }

    @Test fun numbersFollowPythonsTables() {
        assertEquals("€", PyHtml.unescape("&#128;"))
        assertEquals("\uFFFD", PyHtml.unescape("&#xD800;"))
        assertEquals("\uFFFD", PyHtml.unescape("&#x110000;"))
        assertEquals("", PyHtml.unescape("&#1;"))
        assertEquals("\r", PyHtml.unescape("&#13;"))
        assertEquals("&#;", PyHtml.unescape("&#;"))
        assertEquals("\uD83D\uDE00", PyHtml.unescape("&#x1F600;"))
    }

    @Test fun aNameIsAtMost32CodePointsAnAstralOneCountingOnce() {
        val astral = "\uD83D\uDE00".repeat(33)
        assertEquals("&$astral;", PyHtml.unescape("&$astral;"))
    }

    @Test fun moreDigitsThanIntReadsIsPythonsValueError() {
        assertFailsWith<IllegalArgumentException> { PyHtml.unescape("&#" + "1".repeat(4301) + ";") }
        assertEquals("\uFFFD", PyHtml.unescape("&#x" + "f".repeat(5000) + ";"))
    }

    @Test fun aLoneSurrogateIsACodePointOfItsOwn() {
        assertEquals("\uD800&", PyHtml.unescape("\uD800&amp;"))
        assertEquals("&\uD800;", PyHtml.unescape("&\uD800;"))
    }
}
