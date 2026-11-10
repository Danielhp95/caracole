package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.json.PyJson
import org.junit.Test
import java.math.BigInteger
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** PyRepr, the one rule setting_problem and songs_with quote a value by: Python's repr, str and truthiness of what
 * json.loads, a form or a file gave. */
class PyReprTest {
    private fun loads(text: String) = PyJson.loads(text)

    @Test fun reprIsPythonsForEveryKindJsonLoadsMakes() {
        assertEquals("None", PyRepr.repr(null))
        assertEquals("None", PyRepr.repr(loads("null")))
        assertEquals("\"it's\"", PyRepr.repr(loads("\"it's\"")))
        assertEquals("True", PyRepr.repr(loads("true")))
        assertEquals("0", PyRepr.repr(loads("-0")))
        assertEquals("12345678901234567890123", PyRepr.repr(loads("12345678901234567890123")))
        assertEquals("2.0", PyRepr.repr(loads("2.0")))
        assertEquals("100000.0", PyRepr.repr(loads("1e5")))
        assertEquals("1e+16", PyRepr.repr(loads("1e16")))
        assertEquals("nan", PyRepr.repr(loads("NaN")))
        assertEquals("-inf", PyRepr.repr(loads("-Infinity")))
        assertEquals("inf", PyRepr.repr(loads("1e400")))
        assertEquals("[1, 'a', None, [False]]", PyRepr.repr(loads("[1, \"a\", null, [false]]")))
        assertEquals("{'a': 1.5, 'b': {}}", PyRepr.repr(loads("{\"a\": 1.5, \"b\": {}}")))
    }

    @Test fun reprTakesWhatAFormOrAFileGivesAsPythonHoldsIt() {
        assertEquals("3", PyRepr.repr(3))
        assertEquals("3", PyRepr.repr(3L))
        assertEquals("3", PyRepr.repr(BigInteger.valueOf(3)))
        assertEquals("False", PyRepr.repr(false))
        assertEquals("0.5", PyRepr.repr(0.5f))
        assertEquals("['G', 2]", PyRepr.repr(listOf("G", 2)))
        assertEquals("{'key': 'G'}", PyRepr.repr(mapOf("key" to "G")))
    }

    @Test fun strIsATextItselfAndAnythingElseItsRepr() {
        assertEquals("Verse", PyRepr.str(loads("\"Verse\"")))
        assertEquals("2", PyRepr.str(loads("2")))
        assertEquals("1.0", PyRepr.str(loads("1.0")))
        assertEquals("['Chorus']", PyRepr.str(loads("[\"Chorus\"]")))
        assertEquals("True", PyRepr.str(loads("true")))
    }

    @Test fun falsyIsPythonsTruthiness() {
        for (text in listOf("null", "\"\"", "0", "-0", "0.0", "-0.0", "0e5", "false", "[]", "{}")) {
            assertTrue(PyRepr.falsy(loads(text)), text)
        }
        assertTrue(PyRepr.falsy(null))
        for (text in listOf("\" \"", "1", "0.1", "NaN", "true", "[0]", "{\"a\": null}", "100000000000000000000000")) {
            assertFalse(PyRepr.falsy(loads(text)), text)
        }
    }
}
