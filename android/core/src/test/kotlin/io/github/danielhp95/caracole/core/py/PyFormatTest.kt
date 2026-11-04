package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.PyFormatRecords
import org.junit.Test
import java.util.Locale
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** PyFormat and PyUnicode.eastAsianWidth against vectors/py/format_numbers.jsonl and format_width.jsonl: Python's
 * `f` and `%` specs, round() and unicodedata.east_asian_width. */
class PyFormatTest {
    @Test fun everyFormatAndRoundRecordAnswersAsPythonDid() {
        val misses = Misses("py/format_numbers.jsonl")
        PyFormatRecords.numbers(misses)
        misses.assertNone()
    }

    @Test fun everyCodePointIsAsWideAsPythonSays() {
        val misses = Misses("py/format_width.jsonl")
        PyFormatRecords.widths(misses)
        assertEquals(0x110000, misses.checked)
        misses.assertNone()
    }

    @Test fun aTieRoundsToTheEvenDigitOnItsExactBinaryValue() {
        assertEquals("0.12", PyFormat.fixed(0.125, 2))
        assertEquals("0.38", PyFormat.fixed(0.375, 2))
        assertEquals("2", PyFormat.fixed(2.5, 0))
        assertEquals("2.67", PyFormat.fixed(2.675, 2))  // 2.67499999… in binary
        assertEquals("0.83", PyFormat.fixed(0.835, 2))
        assertEquals("0.01", PyFormat.fixed(0.005, 2))  // 0.00500000000000000010…
    }

    @Test fun aSignAZeroPaddingAndAWidthAsPythonWritesThem() {
        assertEquals("-0.00", PyFormat.fixed(-0.0, 2))
        assertEquals("-0.00", PyFormat.fixed(-0.001, 2))
        assertEquals("-01.50", PyFormat.fixed(-1.5, 2, 6, zero = true))
        assertEquals(" -1.50", PyFormat.fixed(-1.5, 2, 6))
        assertEquals("000inf", PyFormat.fixed(Double.POSITIVE_INFINITY, 2, 6, zero = true))
        assertEquals("-inf", PyFormat.fixed(Double.NEGATIVE_INFINITY, 2))
        assertEquals("nan", PyFormat.fixed(-Double.NaN, 1))
        assertEquals("123456.79", PyFormat.fixed(123456.789, 2, 5, zero = true))  // wider than the width
    }

    @Test fun megalobizsStampOfItsLastMillisecondReadsSixty() {
        // f"{ms % 60000 / 1000:05.2f}" of 59999 ms: Python's own rounding up, which the phone keeps.
        assertEquals("60.00", PyFormat.fixed(59999 % 60000 / 1000.0, 2, 5, zero = true))
        assertEquals("07.25", PyFormat.fixed(7.25, 2, 5, zero = true))
    }

    @Test fun aPercentMultipliesByAHundredInDoubleFirst() {
        assertEquals("12%", PyFormat.percent(0.125, 0))
        assertEquals("50%", PyFormat.percent(0.5, 0))
        assertEquals("33%", PyFormat.percent(1.0 / 3, 0))
        assertEquals("0.1%", PyFormat.percent(0.0005, 1))
        assertEquals("-0%", PyFormat.percent(-0.0, 0))
        assertEquals("inf%", PyFormat.percent(Double.POSITIVE_INFINITY, 0))
    }

    @Test fun theDefaultLocaleChangesNothing() {
        val before = Locale.getDefault()
        try {
            Locale.setDefault(Locale.GERMANY)
            assertEquals("1234.50", PyFormat.fixed(1234.5, 2))
            assertEquals("12.5%", PyFormat.percent(0.125, 1))
        } finally {
            Locale.setDefault(before)
        }
    }

    @Test fun roundIsHalfEvenToAWholeNumber() {
        assertEquals(2L, PyFormat.roundHalfEven(2.5))
        assertEquals(-2L, PyFormat.roundHalfEven(-2.5))
        assertEquals(0L, PyFormat.roundHalfEven(0.5))
        assertEquals(0L, PyFormat.roundHalfEven(-0.5))
        assertEquals(2L, PyFormat.roundHalfEven(1.5))
        assertEquals(0L, PyFormat.roundHalfEven(0.49999999999999994))
        assertEquals(4503599627370497L, PyFormat.roundHalfEven(4503599627370497.0))
        assertEquals(-9223372036854775807L - 1, PyFormat.roundHalfEven(-9.223372036854775808e18))
    }

    @Test fun roundRefusesNanInfinitiesAndWholeNumbersPastALong() {
        assertFailsWith<IllegalArgumentException> { PyFormat.roundHalfEven(Double.NaN) }  // ValueError
        assertFailsWith<ArithmeticException> { PyFormat.roundHalfEven(Double.POSITIVE_INFINITY) }  // OverflowError
        assertFailsWith<ArithmeticException> { PyFormat.roundHalfEven(9.223372036854775808e18) }  // Python: an int
        assertFailsWith<ArithmeticException> { PyFormat.roundHalfEven(-1e19) }
    }

    @Test fun aNegativeDigitsOrWidthIsRefused() {
        assertFailsWith<IllegalArgumentException> { PyFormat.fixed(1.0, -1) }
        assertFailsWith<IllegalArgumentException> { PyFormat.fixed(1.0, 1, -1) }
        assertFailsWith<IllegalArgumentException> { PyFormat.percent(1.0, -1) }
    }

    @Test fun widthsOfTheScriptsCaracoleLaysOut() {
        val said = "a宋ｱＡ€é¡😀\u0000𠀀".codePoints().toArray().map(PyUnicode::eastAsianWidth)
        assertEquals(listOf("Na", "W", "H", "F", "A", "A", "A", "W", "N", "W"), said)
        assertEquals("N", PyUnicode.eastAsianWidth(-1))
        assertEquals("N", PyUnicode.eastAsianWidth(0x110000))
    }
}
