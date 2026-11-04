package io.github.danielhp95.caracole.core.py

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Python's format specs and rounding, the ones caracole writes text with: f-strings' `f` and `%` (Megalobiz's LRC
 * stamps, `{s:05.2f}`; a share, `{x:.0%}`) and round(x). A double is rounded half-even on its exact binary value, as
 * CPython's dtoa does (0.125 to 0.12, 2.675 to 2.67), never on a decimal string half-up nor in the default locale, as
 * String.format would (vectors/py/format_numbers.jsonl).
 */
object PyFormat {
    /** f'{x:0W.Nf}': [digits] after the point, at least [width] wide, padded with zeros after the sign when [zero],
     * else with spaces before it; "inf", "-inf" and "nan" (never "-nan") as Python writes them, padded alike. */
    fun fixed(x: Double, digits: Int, width: Int = 0, zero: Boolean = false): String {
        require(digits >= 0) { "digits must be 0 or more: $digits" }
        require(width >= 0) { "width must be 0 or more: $width" }
        val negative = !x.isNaN() && Math.copySign(1.0, x) < 0
        val body = when {
            x.isNaN() -> "nan"
            x.isInfinite() -> "inf"
            else -> BigDecimal(Math.abs(x)).setScale(digits, RoundingMode.HALF_EVEN).toPlainString()
        }
        val sign = if (negative) "-" else ""
        val pad = width - sign.length - body.length
        return when {
            pad <= 0 -> sign + body
            zero -> sign + "0".repeat(pad) + body
            else -> " ".repeat(pad) + sign + body
        }
    }

    /** f'{x:.N%}': x * 100, in double as Python multiplies it, written as [fixed] writes it, then "%". */
    fun percent(x: Double, digits: Int): String = fixed(x * 100.0, digits) + "%"

    /** round(x): to the nearest whole number, a half to the even one (float.__round__ with no digits). Python's
     * ValueError for NaN is an [IllegalArgumentException], its OverflowError for an infinity an
     * [ArithmeticException], as is a whole number past a Long, which Python answers as an int. */
    fun roundHalfEven(x: Double): Long {
        if (x.isNaN()) throw IllegalArgumentException("cannot convert float NaN to integer")
        if (x.isInfinite()) throw ArithmeticException("cannot convert float infinity to integer")
        val rounded = Math.rint(x)  // IEEE round-half-even, exact: CPython's round() then its half-way fix
        if (rounded >= TWO_63 || rounded < -TWO_63) throw ArithmeticException("$x rounds past a Long")
        return rounded.toLong()
    }

    private const val TWO_63 = 9.223372036854775808e18
}
