package io.github.danielhp95.caracole.core.py

/**
 * The few of Python's str methods caracole serve's checks lean on, as Python 3.14 has them: `isspace` and `isdigit`
 * by their tables (vectors/web/security.jsonl holds Python's, SecurityTest compares every code point), `strip`,
 * `isascii`, `lower`, html.escape, and UTF-8 decoded as `bytes.decode` does, strictly or with its replacement.
 *
 * `lower` is Python's (PyUnicode.lower), on every letter.
 */
object PyText {
    /** str.isspace (Unicode's White_Space with bidi class WS, B or S, and Zs). */
    private val SPACES = intArrayOf(
        0x9, 0xD, 0x1C, 0x20, 0x85, 0x85, 0xA0, 0xA0, 0x1680, 0x1680, 0x2000, 0x200A, 0x2028, 0x2029, 0x202F, 0x202F,
        0x205F, 0x205F, 0x3000, 0x3000,
    )

    /** str.isdigit: Numeric_Type Decimal or Digit. */
    private val DIGITS = intArrayOf(
        0x30, 0x39, 0xB2, 0xB3, 0xB9, 0xB9, 0x660, 0x669, 0x6F0, 0x6F9, 0x7C0, 0x7C9, 0x966, 0x96F, 0x9E6, 0x9EF,
        0xA66, 0xA6F, 0xAE6, 0xAEF, 0xB66, 0xB6F, 0xBE6, 0xBEF, 0xC66, 0xC6F, 0xCE6, 0xCEF, 0xD66, 0xD6F, 0xDE6, 0xDEF,
        0xE50, 0xE59, 0xED0, 0xED9, 0xF20, 0xF29, 0x1040, 0x1049, 0x1090, 0x1099, 0x1369, 0x1371, 0x17E0, 0x17E9,
        0x1810, 0x1819, 0x1946, 0x194F, 0x19D0, 0x19DA, 0x1A80, 0x1A89, 0x1A90, 0x1A99, 0x1B50, 0x1B59, 0x1BB0, 0x1BB9,
        0x1C40, 0x1C49, 0x1C50, 0x1C59, 0x2070, 0x2070, 0x2074, 0x2079, 0x2080, 0x2089, 0x2460, 0x2468, 0x2474, 0x247C,
        0x2488, 0x2490, 0x24EA, 0x24EA, 0x24F5, 0x24FD, 0x24FF, 0x24FF, 0x2776, 0x277E, 0x2780, 0x2788, 0x278A, 0x2792,
        0xA620, 0xA629, 0xA8D0, 0xA8D9, 0xA900, 0xA909, 0xA9D0, 0xA9D9, 0xA9F0, 0xA9F9, 0xAA50, 0xAA59, 0xABF0, 0xABF9,
        0xFF10, 0xFF19, 0x104A0, 0x104A9, 0x10A40, 0x10A43, 0x10D30, 0x10D39, 0x10D40, 0x10D49, 0x10E60, 0x10E68,
        0x11052, 0x1105A, 0x11066, 0x1106F, 0x110F0, 0x110F9, 0x11136, 0x1113F, 0x111D0, 0x111D9, 0x112F0, 0x112F9,
        0x11450, 0x11459, 0x114D0, 0x114D9, 0x11650, 0x11659, 0x116C0, 0x116C9, 0x116D0, 0x116E3, 0x11730, 0x11739,
        0x118E0, 0x118E9, 0x11950, 0x11959, 0x11BF0, 0x11BF9, 0x11C50, 0x11C59, 0x11D50, 0x11D59, 0x11DA0, 0x11DA9,
        0x11F50, 0x11F59, 0x16130, 0x16139, 0x16A60, 0x16A69, 0x16AC0, 0x16AC9, 0x16B50, 0x16B59, 0x16D70, 0x16D79,
        0x1CCF0, 0x1CCF9, 0x1D7CE, 0x1D7FF, 0x1E140, 0x1E149, 0x1E2F0, 0x1E2F9, 0x1E4F0, 0x1E4F9, 0x1E5F1, 0x1E5FA,
        0x1E950, 0x1E959, 0x1F100, 0x1F10A, 0x1FBF0, 0x1FBF9,
    )

    private fun within(table: IntArray, cp: Int): Boolean {
        var i = 0
        while (i < table.size) {
            if (cp < table[i]) return false
            if (cp <= table[i + 1]) return true
            i += 2
        }
        return false
    }

    fun isSpace(cp: Int): Boolean = within(SPACES, cp)

    fun isDigit(cp: Int): Boolean = within(DIGITS, cp)

    /** s.isdigit(): every code point a digit, and one at least. */
    fun allDigits(s: String): Boolean = s.isNotEmpty() && s.codePoints().allMatch { isDigit(it) }

    fun isAscii(s: String): Boolean = s.all { it.code < 0x80 }

    /** s.strip(): Python's whitespace off both ends. */
    fun strip(s: String): String {
        var start = 0
        var end = s.length
        while (start < end && isSpace(s.codePointAt(start))) start += Character.charCount(s.codePointAt(start))
        while (end > start && isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(start, end)
    }

    /** s.strip(chars) for a set of BMP characters. */
    fun strip(s: String, chars: String): String = s.trim { it in chars }

    fun lower(s: String): String = PyUnicode.lower(s)

    /** A–Z alone: a header's word, an HTTP method's. */
    fun asciiLower(s: String): String = buildString(s.length) { for (c in s) append(if (c in 'A'..'Z') c + 32 else c) }

    /** html.escape(s, quote=True). */
    fun escape(s: String): String = buildString(s.length) {
        for (c in s) when (c) {
            '&' -> append("&amp;")
            '<' -> append("&lt;")
            '>' -> append("&gt;")
            '"' -> append("&quot;")
            '\'' -> append("&#x27;")
            else -> append(c)
        }
    }

    /**
     * bytes.decode("utf-8"): null where it isn't UTF-8 ([replace] false, "strict"), else each maximal ill-formed part
     * one U+FFFD, as Python's "replace" writes it (Unicode's "substitution of maximal subparts").
     */
    fun utf8(bytes: ByteArray, from: Int = 0, to: Int = bytes.size, replace: Boolean = false): String? {
        val out = StringBuilder(to - from)
        var i = from
        while (i < to) {
            val b0 = bytes[i].toInt() and 0xFF
            if (b0 < 0x80) {
                out.append(b0.toChar())
                i++
                continue
            }
            // The sequence's length, and the range its second byte must be in.
            val (need, low, high) = when (b0) {
                in 0xC2..0xDF -> Triple(1, 0x80, 0xBF)
                0xE0 -> Triple(2, 0xA0, 0xBF)
                in 0xE1..0xEC, 0xEE, 0xEF -> Triple(2, 0x80, 0xBF)
                0xED -> Triple(2, 0x80, 0x9F)
                0xF0 -> Triple(3, 0x90, 0xBF)
                in 0xF1..0xF3 -> Triple(3, 0x80, 0xBF)
                0xF4 -> Triple(3, 0x80, 0x8F)
                else -> Triple(0, 0, 0)
            }
            var cp = when (need) {
                1 -> b0 and 0x1F
                2 -> b0 and 0x0F
                3 -> b0 and 0x07
                else -> -1
            }
            var taken = 1
            if (need > 0) {
                while (taken <= need) {
                    val at = i + taken
                    if (at >= to) break
                    val b = bytes[at].toInt() and 0xFF
                    val (lo, hi) = if (taken == 1) low to high else 0x80 to 0xBF
                    if (b < lo || b > hi) break
                    cp = (cp shl 6) or (b and 0x3F)
                    taken++
                }
            }
            if (need > 0 && taken == need + 1) {
                out.appendCodePoint(cp)
                i += taken
            } else {
                if (!replace) return null
                out.append('�')
                i += taken
            }
        }
        return out.toString()
    }
}
