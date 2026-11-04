package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.PyUnicode

/** The str methods the sheet's readers use, as Python's: its whitespace (str.isspace), its tab stops, its translate
 * tables by code point. Never Kotlin's trim, lines or isWhitespace, whose Unicode is the JDK's. */
internal object Str {
    fun rstrip(s: String): String {
        var end = s.length
        while (end > 0) {
            val cp = s.codePointBefore(end)
            if (!PyUnicode.isSpace(cp)) break
            end -= Character.charCount(cp)
        }
        return s.substring(0, end)
    }

    /** Whether `s.strip()` is empty: [s] all whitespace, or nothing. */
    fun blank(s: String): Boolean {
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (!PyUnicode.isSpace(cp)) return false
            i += Character.charCount(cp)
        }
        return true
    }

    /** str.rstrip(chars), [chars] BMP characters. */
    fun rstrip(s: String, chars: String): String {
        var end = s.length
        while (end > 0 && s[end - 1] in chars) end--
        return s.substring(0, end)
    }

    /** str.expandtabs(size): each tab to the next multiple of [size], counted in code points from the last `\n` or
     * `\r`. */
    fun expandTabs(s: String, size: Int): String {
        if ('\t' !in s) return s
        val out = StringBuilder(s.length + 8)
        var column = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            when (cp) {
                '\t'.code -> if (size > 0) {
                    val n = size - column % size
                    repeat(n) { out.append(' ') }
                    column += n
                }
                '\n'.code, '\r'.code -> { out.append(cp.toChar()); column = 0 }
                else -> { out.appendCodePoint(cp); column++ }
            }
        }
        return out.toString()
    }

    /** str.translate with a table of code points. */
    fun translate(s: String, table: Map<Int, String>): String {
        val out = StringBuilder(s.length)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            val to = table[cp]
            if (to != null) out.append(to) else out.appendCodePoint(cp)
        }
        return out.toString()
    }

    /** str.count of a non-empty [sub]. */
    fun count(s: String, sub: String): Int {
        var n = 0
        var at = s.indexOf(sub)
        while (at >= 0) {
            n++
            at = s.indexOf(sub, at + sub.length)
        }
        return n
    }

    /** str.partition(sep). */
    fun partition(s: String, sep: String): Triple<String, String, String> {
        val at = s.indexOf(sep)
        return if (at < 0) Triple(s, "", "") else Triple(s.substring(0, at), sep, s.substring(at + sep.length))
    }

    /** " " * n. */
    fun spaces(n: Int): String = if (n <= 0) "" else " ".repeat(n)
}
