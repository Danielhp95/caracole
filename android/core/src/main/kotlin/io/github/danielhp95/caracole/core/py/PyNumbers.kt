package io.github.danielhp95.caracole.core.py

import java.math.BigInteger

/** float(str), Python 3.14's: Unicode decimal digits, underscores between digits, inf and nan words, spaces
 * stripped; null where Python raises ValueError. */
object PyFloat {
    /**
     * As PyFloat_FromString reads [s]: each code point past ASCII a space (str.isspace) made `' '`, a decimal digit
     * made its ASCII digit, anything else refused (_PyUnicode_TransformDecimalAndSpaceToASCII); then an underscore
     * only between two digits (_Py_string_to_number_with_underscores), ASCII whitespace off both ends (Py_ISSPACE:
     * space, \t, \n, \v, \f, \r, never \x1c–\x1f, which str.strip would take), and what is left a decimal number
     * (`[+-]` digits with an optional `.` and fraction, at least one digit, an optional exponent) or `inf`,
     * `infinity` or `nan` in any case after an optional sign, read whole. The double is the one nearest the decimal,
     * ties to the even one (dtoa's), from its digits alone: never the JDK's parser.
     */
    fun parse(s: String): Double? {
        val ascii = PyNumbers.ascii(s) ?: return null
        val text = PyNumbers.underscores(ascii) ?: return null
        var from = 0
        var to = text.length
        while (from < to && PyNumbers.isSpace(text[from])) from++
        if (from == to) return null
        while (to > from + 1 && PyNumbers.isSpace(text[to - 1])) to--
        return number(text, from, to)
    }

    /** _Py_dg_strtod and _Py_parse_inf_or_nan over text[from, to), which must be read whole. */
    private fun number(text: String, from: Int, to: Int): Double? {
        var i = from
        val negative = text[i] == '-'
        if (text[i] == '-' || text[i] == '+') i++
        val signed = i
        val digits = StringBuilder()
        var point = -1 // the digits' count before the point
        var any = false
        while (i < to && text[i] in '0'..'9') { digits.append(text[i]); i++; any = true }
        if (i < to && text[i] == '.') {
            point = digits.length
            i++
            while (i < to && text[i] in '0'..'9') { digits.append(text[i]); i++; any = true }
        }
        if (!any) return word(text, signed, to, negative) // dtoa read nothing: inf or nan, from after the sign
        var exponent = 0L
        if (i < to && (text[i] == 'e' || text[i] == 'E')) {
            var k = i + 1
            val minus = k < to && text[k] == '-'
            if (k < to && (text[k] == '-' || text[k] == '+')) k++
            if (k < to && text[k] in '0'..'9') {
                while (k < to && text[k] in '0'..'9') {
                    if (exponent < 1_000_000_000L) exponent = exponent * 10 + (text[k] - '0')
                    k++
                }
                if (minus) exponent = -exponent
                i = k
            }
        }
        if (i != to) return null
        val fraction = if (point < 0) 0 else digits.length - point
        return PyNumbers.nearest(negative, digits, exponent - fraction)
    }

    private fun word(text: String, at: Int, to: Int, negative: Boolean): Double? {
        val rest = Py.asciiLower(text.substring(at, to))
        return when (rest) {
            "inf", "infinity" -> if (negative) Double.NEGATIVE_INFINITY else Double.POSITIVE_INFINITY
            "nan" -> Double.fromBits(if (negative) NEGATIVE_NAN else NAN)
            else -> null
        }
    }

    private const val NAN = 0x7ff8000000000000L
    private const val NEGATIVE_NAN = -0x8000000000000L // 0xfff8000000000000: -fabs(NAN), "-nan"'s
}

/** int(str), Python 3.14's (base 10): Unicode decimal digits, underscores, a sign, spaces stripped; null where Python
 * raises ValueError. */
object PyInt {
    /** Python's limit on the digits int() reads (sys.get_int_max_str_digits()). */
    const val MAX_DIGITS = 4300

    /**
     * As PyLong_FromUnicodeObject reads [s] in base 10: the same mapping to ASCII as float()'s, ASCII whitespace off
     * both ends, an optional sign, then digits with single underscores between them (none first or last), read
     * whole; more than [MAX_DIGITS] digits (leading zeros counted, underscores not) is Python's ValueError too.
     */
    fun parse(s: String): BigInteger? {
        val text = PyNumbers.ascii(s) ?: return null
        var from = 0
        var to = text.length
        while (from < to && PyNumbers.isSpace(text[from])) from++
        while (to > from && PyNumbers.isSpace(text[to - 1])) to--
        var i = from
        val negative = i < to && text[i] == '-'
        if (i < to && (text[i] == '-' || text[i] == '+')) i++
        if (i >= to || text[i] !in '0'..'9') return null
        val digits = StringBuilder(to - i)
        var previous = ' '
        while (i < to) {
            val c = text[i]
            when {
                c in '0'..'9' -> digits.append(c)
                c == '_' -> if (previous == '_') return null
                else -> return null
            }
            previous = c
            i++
        }
        if (previous == '_' || digits.length > MAX_DIGITS) return null
        val value = BigInteger(digits.toString())
        return if (negative) value.negate() else value
    }
}

/** What float() and int() share, and the exact reading of a decimal as a double. */
internal object PyNumbers {
    /** Py_ISSPACE: C's whitespace, ASCII alone. */
    fun isSpace(c: Char): Boolean = c == ' ' || c in '\t'..'\r'

    /**
     * _PyUnicode_TransformDecimalAndSpaceToASCII: below U+007F as it is; past it a str.isspace code point `' '`, a
     * decimal digit its ASCII digit; null for anything else (Python writes a '?', which no number reads).
     */
    fun ascii(s: String): String? {
        var plain = true
        for (c in s) if (c.code >= 127) { plain = false; break }
        if (plain) return s
        val out = StringBuilder(s.length)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            when {
                cp < 127 -> out.append(cp.toChar())
                PyUnicode.isSpace(cp) -> out.append(' ')
                PyUnicode.isDecimal(cp) -> out.append('0' + decimal(cp))
                else -> return null
            }
        }
        return out.toString()
    }

    /** A decimal digit's value: its place in its run of ten (Unicode encodes each script's 0–9 in a row, and
     * tests/test_conformance_py.py checks Python's answers do too). */
    private fun decimal(cp: Int): Int {
        var start = cp
        while (PyUnicode.isDecimal(start - 1)) start--
        return (cp - start) % 10
    }

    /** _Py_string_to_number_with_underscores: [s] with its underscores out, each between two digits, or null. */
    fun underscores(s: String): String? {
        if ('_' !in s) return s
        val out = StringBuilder(s.length)
        var previous = '\u0000'
        for (c in s) {
            if (c == '_') {
                if (previous !in '0'..'9') return null
            } else {
                if (previous == '_' && c !in '0'..'9') return null
                out.append(c)
            }
            previous = c
        }
        return if (previous == '_') null else out.toString()
    }

    private val EXACT = DoubleArray(23).also { p -> p[0] = 1.0; for (k in 1 until p.size) p[k] = p[k - 1] * 10.0 }
    private val TEN = BigInteger.TEN

    /**
     * The double nearest digits × 10^[exponent] (ASCII digits, leading zeros allowed), ties to the even double, the
     * sign [negative]'s: one exact IEEE operation where the digits and the power of ten are exact doubles (Clinger's
     * fast path), else exact integer arithmetic on the digits.
     */
    fun nearest(negative: Boolean, digits: CharSequence, exponent: Long): Double {
        var start = 0
        while (start < digits.length && digits[start] == '0') start++
        var end = digits.length
        var e = exponent
        while (end > start && digits[end - 1] == '0') { end--; e++ }
        val n = end - start
        val magnitude = when {
            n == 0 -> 0.0
            n + e > 310 -> Double.POSITIVE_INFINITY
            n + e < -324 -> 0.0
            n <= 15 && e in -22..22 -> {
                var m = 0L
                for (k in start until end) m = m * 10 + (digits[k] - '0')
                if (e >= 0) m.toDouble() * EXACT[e.toInt()] else m.toDouble() / EXACT[(-e).toInt()]
            }
            else -> exact(BigInteger(digits.subSequence(start, end).toString()), e.toInt())
        }
        return if (negative) -magnitude else magnitude
    }

    /** m × 10^e as the nearest double, half to even, by integers alone. */
    private fun exact(m: BigInteger, e: Int): Double {
        val num = if (e >= 0) m.multiply(TEN.pow(e)) else m
        val den = if (e >= 0) BigInteger.ONE else TEN.pow(-e)
        // The binary exponent: 2^b <= num/den < 2^(b+1).
        var b = num.bitLength() - den.bitLength()
        val below = if (b >= 0) num < den.shiftLeft(b) else num.shiftLeft(-b) < den
        if (below) b--
        if (b > 1023) return Double.POSITIVE_INFINITY
        var shift = maxOf(b - 52, -1074) // the value of the significand's last bit
        val (n2, d2) = if (shift <= 0) num.shiftLeft(-shift) to den else num to den.shiftLeft(shift)
        val qr = n2.divideAndRemainder(d2)
        var q = qr[0].toLong()
        val twice = qr[1].shiftLeft(1).compareTo(d2)
        if (twice > 0 || (twice == 0 && q and 1L == 1L)) q++
        if (q == 1L shl 53) { q = 1L shl 52; shift++ }
        if (q < 1L shl 52) return Double.fromBits(q) // subnormal (or the smallest normal, reached by rounding up)
        val biased = shift + 1075
        if (biased >= 2047) return Double.POSITIVE_INFINITY
        return Double.fromBits((biased.toLong() shl 52) or (q - (1L shl 52)))
    }
}
