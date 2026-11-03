package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.py.PyUnicode

/** Python's `repr` of a string, as caracole's messages quote a name (`{name!r}`): the words a take leaves a unit
 * with are Python's. */
internal object PyRepr {
    fun str(s: String): String {
        val quote = if ('\'' in s && '"' !in s) '"' else '\''
        val out = StringBuilder().append(quote)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            when {
                cp == quote.code || cp == '\\'.code -> out.append('\\').appendCodePoint(cp)
                cp == '\t'.code -> out.append("\\t")
                cp == '\n'.code -> out.append("\\n")
                cp == '\r'.code -> out.append("\\r")
                cp < 0x20 || cp == 0x7F -> out.append("\\x").append(hex(cp, 2))
                cp < 0x7F -> out.appendCodePoint(cp)
                PyUnicode.isPrintable(cp) -> out.appendCodePoint(cp)
                cp < 0x100 -> out.append("\\x").append(hex(cp, 2))
                cp < 0x10000 -> out.append("\\u").append(hex(cp, 4))
                else -> out.append("\\U").append(hex(cp, 8))
            }
        }
        return out.append(quote).toString()
    }

    private fun hex(n: Int, width: Int): String {
        val digits = Integer.toHexString(n)
        return "0".repeat(maxOf(0, width - digits.length)) + digits
    }
}
