package io.github.danielhp95.caracole.core.json

/**
 * What Canonical and PyJson share: a string written as Python's json writes it with ensure_ascii=False, a number
 * literal by the decimal rule, and text as the bytes Python's `str.encode("utf-8", "surrogatepass")` gives. Plain
 * Kotlin: no JDK text API beyond String.codePointAt and the surrogate helpers, so the JVM and Android agree.
 */
internal object JsonText {
    private const val HEX = "0123456789abcdef"

    /** [s] quoted: `"` and `\` escaped, U+0008, 09, 0A, 0C and 0D as `\b \t \n \f \r`, every other code point below
     * U+0020 as `\u00xx`, everything else raw (json.encoder.encode_basestring). */
    fun quote(out: StringBuilder, s: String) {
        out.append('"')
        for (c in s) {
            when (c) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\b' -> out.append("\\b")
                '\t' -> out.append("\\t")
                '\n' -> out.append("\\n")
                '\u000C' -> out.append("\\f")
                '\r' -> out.append("\\r")
                else -> if (c < ' ') {
                    out.append("\\u00").append(HEX[c.code shr 4]).append(HEX[c.code and 0xF])
                } else {
                    out.append(c)
                }
            }
        }
        out.append('"')
    }

    /** Whether [s] holds a lone surrogate: a UTF-16 unit of U+D800–DFFF that is not half of a pair. */
    fun hasLoneSurrogate(s: String): Boolean {
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (cp in 0xD800..0xDFFF) return true
            i += Character.charCount(cp)
        }
        return false
    }

    /** [s]'s UTF-8, each lone surrogate as the three bytes of its code point, as Python's "surrogatepass" writes it. */
    fun utf8(s: String): ByteArray {
        var size = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            size += when {
                cp < 0x80 -> 1
                cp < 0x800 -> 2
                cp < 0x10000 -> 3
                else -> 4
            }
            i += Character.charCount(cp)
        }
        val out = ByteArray(size)
        var o = 0
        i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            when {
                cp < 0x80 -> out[o++] = cp.toByte()
                cp < 0x800 -> {
                    out[o++] = (0xC0 or (cp shr 6)).toByte()
                    out[o++] = (0x80 or (cp and 0x3F)).toByte()
                }
                cp < 0x10000 -> {
                    out[o++] = (0xE0 or (cp shr 12)).toByte()
                    out[o++] = (0x80 or ((cp shr 6) and 0x3F)).toByte()
                    out[o++] = (0x80 or (cp and 0x3F)).toByte()
                }
                else -> {
                    out[o++] = (0xF0 or (cp shr 18)).toByte()
                    out[o++] = (0x80 or ((cp shr 12) and 0x3F)).toByte()
                    out[o++] = (0x80 or ((cp shr 6) and 0x3F)).toByte()
                    out[o++] = (0x80 or (cp and 0x3F)).toByte()
                }
            }
            i += Character.charCount(cp)
        }
        return out
    }

    fun hex(bytes: ByteArray): String {
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            out.append(HEX[v shr 4]).append(HEX[v and 0xF])
        }
        return out.toString()
    }

    /** A JSON number literal's parts, `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?` in ASCII digits; null when
     * [literal] is no such literal. */
    class Number(val negative: Boolean, val whole: String, val fraction: String, val exponentNegative: Boolean,
                 val exponent: String?) {
        val integral: Boolean get() = fraction.isEmpty() && exponent == null
    }

    private fun digit(c: Char) = c in '0'..'9'

    fun number(literal: String): Number? {
        var i = 0
        val n = literal.length
        val negative = i < n && literal[i] == '-'
        if (negative) i++
        val wholeStart = i
        if (i < n && literal[i] == '0') {
            i++
        } else if (i < n && literal[i] in '1'..'9') {
            while (i < n && digit(literal[i])) i++
        } else {
            return null
        }
        val whole = literal.substring(wholeStart, i)
        var fraction = ""
        if (i < n && literal[i] == '.') {
            val start = ++i
            while (i < n && digit(literal[i])) i++
            if (i == start) return null
            fraction = literal.substring(start, i)
        }
        var exponentNegative = false
        var exponent: String? = null
        if (i < n && (literal[i] == 'e' || literal[i] == 'E')) {
            i++
            if (i < n && (literal[i] == '-' || literal[i] == '+')) exponentNegative = literal[i++] == '-'
            val start = i
            while (i < n && digit(literal[i])) i++
            if (i == start) return null
            exponent = literal.substring(start, i)
        }
        return if (i == n) Number(negative, whole, fraction, exponentNegative, exponent) else null
    }

    /** A number literal as C(v) writes it: an integer's decimal (`-0` as `0`), any other literal's exact decimal
     * value in plain notation, trailing fractional zeros and then a trailing `.` dropped, `-0` as `0`, computed on its
     * digits. CanonicalError for no number literal, an integer of more than [Canonical.MAX_INT_DIGITS] digits, or an
     * exponent written beyond ±[Canonical.MAX_EXPONENT]. */
    fun decimal(literal: String): String {
        val number = number(literal) ?: throw CanonicalError("not a JSON number: ${literal.take(40)}")
        if (number.integral) {
            if (number.whole.length > Canonical.MAX_INT_DIGITS) {
                throw CanonicalError("an integer of more than ${Canonical.MAX_INT_DIGITS} digits")
            }
            return if (number.whole == "0") "0" else literal
        }
        var shift = 0
        if (number.exponent != null) {
            val written = number.exponent.trimStart('0')
            if (written.length > Canonical.MAX_EXPONENT.toString().length) throw beyond(literal)
            var value = 0
            for (c in written) value = value * 10 + (c - '0')
            if (value > Canonical.MAX_EXPONENT) throw beyond(literal)
            shift = if (number.exponentNegative) -value else value
        }
        var digits = number.whole + number.fraction
        var point = number.whole.length + shift // where the decimal point falls among the digits
        if (point <= 0) {
            digits = "0".repeat(1 - point) + digits
            point = 1
        } else if (point > digits.length) {
            digits += "0".repeat(point - digits.length)
        }
        val integer = digits.substring(0, point).trimStart('0').ifEmpty { "0" }
        val fraction = digits.substring(point).trimEnd('0')
        val text = if (fraction.isEmpty()) integer else "$integer.$fraction"
        return if (text == "0") "0" else if (number.negative) "-$text" else text
    }

    private fun beyond(literal: String) =
        CanonicalError("an exponent beyond ±${Canonical.MAX_EXPONENT}: ${literal.take(40)}")
}
