package io.github.danielhp95.caracole.core.py

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Python's html module, as caracole's site parsers call it. */
object PyHtml {
    /**
     * html.unescape: the HTML5 table of data/caracole/html/entities.json, the numeric references by its rules.
     *
     * As Python 3.14's: each `&` that starts `#` and ASCII digits, `#x` (or `#X`) and hex digits, or 1 to 32 code
     * points none of `\t \n \f space < & # ;`, each with an optional `;`, is replaced (re.sub's left-to-right scan);
     * any other `&` stays.
     * - A number: windows-1252's meaning for 0x80–0x9F and U+FFFD for 0 (`_invalid_charrefs`), U+FFFD for a
     *   surrogate or past U+10FFFF, nothing for the invalid code points (`_invalid_codepoints`: the C0 controls but
     *   \t \n \f \r, DEL and the C1 controls, U+FDD0–FDEF and each plane's last two), else the code point. A decimal
     *   one of more than 4,300 digits is int()'s ValueError, which html.unescape raises
     *   ([IllegalArgumentException]).
     * - A name: the table's text for it (with its `;` when it has one); else the longest of its first code points,
     *   two at least, that the table names (a legacy name, with no `;`) and the rest as written; else as written.
     */
    fun unescape(s: String): String {
        val first = s.indexOf('&')
        if (first < 0) return s
        val out = StringBuilder(s.length)
        out.append(s, 0, first)
        var i = first
        while (i < s.length) {
            val c = s[i]
            if (c != '&') {
                out.append(c)
                i++
                continue
            }
            val end = if (i + 1 < s.length && s[i + 1] == '#') numeric(s, i, out) else named(s, i, out)
            if (end < 0) {
                out.append('&')
                i++
            } else {
                i = end
            }
        }
        return out.toString()
    }

    /** A numeric reference at [at] (`&#…`) replaced into [out]: the index after it, or -1 when none matches there. */
    private fun numeric(s: String, at: Int, out: StringBuilder): Int {
        var i = at + 2
        val hex = i < s.length && (s[i] == 'x' || s[i] == 'X')
        if (hex) i++
        val start = i
        var value = 0L // capped past the last code point: only "past U+10FFFF" matters then
        while (i < s.length) {
            val d = digit(s[i], hex)
            if (d < 0) break
            value = minOf(value * (if (hex) 16 else 10) + d, BEYOND)
            i++
        }
        if (i == start) {
            // `&#x` with no hex digit: not a number; and `#` starts no name, so nothing matches at this `&`.
            return -1
        }
        if (!hex && i - start > PyInt.MAX_DIGITS) {
            throw IllegalArgumentException("Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string " +
                "conversion: value has ${i - start} digits; use sys.set_int_max_str_digits() to increase the limit")
        }
        if (i < s.length && s[i] == ';') i++
        val n = value.toInt()
        val windows = if (value < 0xA0) INVALID_CHARREFS[n] else null
        when {
            windows != null -> out.append(windows)
            value in 0xD800..0xDFFF || value > 0x10FFFF -> out.append('\uFFFD')
            invalidCodePoint(n) -> {}
            else -> out.appendCodePoint(n)
        }
        return i
    }

    private const val BEYOND = 0x110000L

    private fun digit(c: Char, hex: Boolean): Int = when (c) {
        in '0'..'9' -> c - '0'
        in 'a'..'f' -> if (hex) c - 'a' + 10 else -1
        in 'A'..'F' -> if (hex) c - 'A' + 10 else -1
        else -> -1
    }

    /** A named reference at [at] replaced into [out]: the index after it, or -1 when none matches there. */
    private fun named(s: String, at: Int, out: StringBuilder): Int {
        var i = at + 1
        var count = 0 // code points, as Python's {1,32} counts them
        while (i < s.length && count < 32) {
            val c = s[i]
            if (c == '\t' || c == '\n' || c == '\u000C' || c == ' ' || c == '<' || c == '&' || c == '#' || c == ';') break
            i += Character.charCount(s.codePointAt(i))
            count++
        }
        if (count == 0) return -1
        if (i < s.length && s[i] == ';') i++
        val name = s.substring(at + 1, i)
        val table = Entities.table
        table[name]?.let { out.append(it); return i }
        // The longest prefix of two code points or more the table names: one with no ';', a legacy name.
        val cps = Py.codePoints(name)
        for (x in cps.size - 1 downTo 2) {
            val prefix = Py.string(cps, 0, x)
            val text = table[prefix] ?: continue
            out.append(text).append(name, prefix.length, name.length)
            return i
        }
        out.append('&').append(name)
        return i
    }

    /** html._invalid_charrefs: what a number below U+00A0 stands for when it isn't the code point. */
    private val INVALID_CHARREFS: Array<String?> = arrayOfNulls<String>(0xA0).also { t ->
        t[0x00] = "\uFFFD"
        t[0x0D] = "\r"
        val c1 = "\u20AC\u0081\u201A\u0192\u201E\u2026\u2020\u2021\u02C6\u2030\u0160\u2039\u0152\u008D\u017D\u008F" +
            "\u0090\u2018\u2019\u201C\u201D\u2022\u2013\u2014\u02DC\u2122\u0161\u203A\u0153\u009D\u017E\u0178"
        for (k in c1.indices) t[0x80 + k] = c1[k].toString()
    }

    /** html._invalid_codepoints. */
    private fun invalidCodePoint(n: Int): Boolean =
        n in 0x1..0x8 || n == 0xB || n in 0xE..0x1F || n in 0x7F..0x9F || n in 0xFDD0..0xFDEF ||
            (n and 0xFFFE) == 0xFFFE

    private object Entities {
        /** html.entities.html5: each name (with its ';', or without for a legacy one) and its text. */
        val table: Map<String, String> = run {
            val stream = PyHtml::class.java.getResourceAsStream("/caracole/html/entities.json")
                ?: throw IllegalStateException("caracole/html/entities.json is not on the classpath (tests/conformance/data)")
            val text = stream.use { it.readBytes() }.toString(Charsets.UTF_8)
            val rows = Json.parseToJsonElement(text).jsonObject.getValue("entities").jsonArray
            HashMap<String, String>(rows.size * 2).also { map ->
                for (row in rows) {
                    val pair = row.jsonArray
                    map[pair[0].jsonPrimitive.content] = pair[1].jsonPrimitive.content
                }
            }
        }
    }
}
