package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import org.junit.Test
import java.math.BigInteger
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** PyFloat and PyInt against float() and int() (vectors/py/sites_numbers.jsonl: every Unicode decimal digit and
 * space, underscores, inf and nan, ties between two doubles), and the cases a corpus line can't hold. */
class PyNumbersTest {
    @Test fun everyRecordAnswersAsFloatAndIntDid() = PyReplay.numbers()

    private fun bits(x: Double?) = x?.let { java.lang.Long.toHexString(it.toRawBits()) }

    @Test fun floatIsTheNearestDoubleTiesToEven() {
        assertEquals(bits(9007199254740992.0), bits(PyFloat.parse("9007199254740993")))
        assertEquals(bits(9007199254740996.0), bits(PyFloat.parse("9007199254740995")))
        assertEquals(bits(Double.MIN_VALUE), bits(PyFloat.parse("2.4703282292062328e-324")))
        assertEquals(bits(0.0), bits(PyFloat.parse("2.4703282292062327e-324")))
        assertEquals(bits(Double.MAX_VALUE), bits(PyFloat.parse("1.7976931348623158e308")))
        assertEquals(Double.POSITIVE_INFINITY, PyFloat.parse("1.7976931348623159e308"))
        assertEquals(bits(-0.0), bits(PyFloat.parse("-0e5")))
        assertEquals(0.0, PyFloat.parse("1e-99999999999999999999"))
        assertEquals(Double.NEGATIVE_INFINITY, PyFloat.parse("-1e99999999999999999999"))
    }

    @Test fun floatReadsWhatPythonReads() {
        assertEquals(1.5, PyFloat.parse("\u00a0١.٥\u3000"))
        assertEquals(1000.01, PyFloat.parse("1_000.0_1"))
        assertEquals("7ff8000000000000", bits(PyFloat.parse("nan")))
        assertEquals("fff8000000000000", bits(PyFloat.parse("-NaN")))
        assertEquals(Double.POSITIVE_INFINITY, PyFloat.parse(" +Infinity "))
        assertNull(PyFloat.parse("\u001c1"))
        assertNull(PyFloat.parse("1_"))
        assertNull(PyFloat.parse("0x10"))
        assertNull(PyFloat.parse("1\uD800"))
    }

    @Test fun intReadsWhatPythonReads() {
        assertEquals(BigInteger.valueOf(123), PyInt.parse(" １２_3 "))
        assertEquals(BigInteger.ZERO, PyInt.parse("-0"))
        assertEquals(BigInteger("1".repeat(4300)), PyInt.parse("1".repeat(4300)))
        assertNull(PyInt.parse("1".repeat(4301)))
        assertNull(PyInt.parse("0".repeat(4301)))
        assertNull(PyInt.parse("1.0"))
        assertNull(PyInt.parse("_1"))
        assertNull(PyInt.parse("1__0"))
        assertNull(PyInt.parse("\uDC00"))
    }
}
