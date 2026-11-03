package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.py.PyUnicode

/** Python's str operations the routes' words need: repr, as `{text!r}` writes one; splitlines. */
internal object PyStr {
    /** Python's repr of a str: in single quotes (double when it holds a single quote and no double), each backslash,
     * quote, tab, line break and character Python can't print escaped. */
    fun repr(s: String): String {
        val quote = if ('\'' in s && '"' !in s) '"' else '\''
        return buildString {
            append(quote)
            var i = 0
            while (i < s.length) {
                val cp = s.codePointAt(i)
                i += Character.charCount(cp)
                when {
                    cp == quote.code || cp == '\\'.code -> append('\\').appendCodePoint(cp)
                    cp == '\t'.code -> append("\\t")
                    cp == '\n'.code -> append("\\n")
                    cp == '\r'.code -> append("\\r")
                    cp < 0x20 || cp == 0x7f -> append("\\x%02x".format(cp))
                    cp < 0x7f || PyUnicode.isPrintable(cp) -> appendCodePoint(cp)
                    cp <= 0xff -> append("\\x%02x".format(cp))
                    cp <= 0xffff -> append("\\u%04x".format(cp))
                    else -> append("\\U%08x".format(cp))
                }
            }
            append(quote)
        }
    }

    /** str.splitlines: the lines of [s], split at each of Python's line boundaries ("\r\n" one), with none after a
     * last boundary. */
    fun splitlines(s: String): List<String> {
        val lines = ArrayList<String>()
        var start = 0
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (c in BOUNDARIES) {
                lines.add(s.substring(start, i))
                i += if (c == '\r' && i + 1 < s.length && s[i + 1] == '\n') 2 else 1
                start = i
            } else {
                i++
            }
        }
        if (start < s.length) lines.add(s.substring(start))
        return lines
    }

    private const val BOUNDARIES = "\n\r\u000b\u000c\u001c\u001d\u001e\u0085  "
}
