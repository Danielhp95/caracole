package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** PyUnicode.capitalize against str.capitalize (vectors/py/sites_capitalize.jsonl: every code point alone and after a
 * letter, and strings). */
class PyCapitalizeTest {
    @Test fun everyRecordAnswersAsStrCapitalizeDid() = PyReplay.capitalize()

    @Test fun theFirstIsTitleCasedTheRestLoweredInContext() {
        assertEquals("ǅungla", PyUnicode.capitalize("ǆUNGLA"))
        assertEquals("Ssx", PyUnicode.capitalize("ßX"))
        assertEquals("Ας", PyUnicode.capitalize("ΑΣ"))
        assertEquals("Σα", PyUnicode.capitalize("ΣΑ"))
        assertEquals("ა", PyUnicode.capitalize("ა"))
        assertEquals("Dorian", PyUnicode.capitalize("dorian"))
        assertEquals("", PyUnicode.capitalize(""))
        assertEquals("\uD800a", PyUnicode.capitalize("\uD800A"))
    }

    @Test fun pyUnicodesCapitalizeIsNoForbiddenCall() {
        assertTrue(ForbiddenApis.scan("K.kt", "val a = PyUnicode.capitalize(s)").isEmpty())
        assertEquals(1, ForbiddenApis.scan("K.kt", "val a = s.capitalize()").size)
    }
}
