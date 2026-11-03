package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * One of normalize.py's patterns, as Python's re reads it, for the few calls normalize.py makes of it: [search],
 * [sub] with a literal replacement, [split] and [matchEnd] (`pattern.match(text, pos)`).
 *
 * [translate] rewrites Python's text into one java.util.regex and Python read alike, which core.py.PyRegex then
 * compiles (its `\w \W \s \S \d \D \b \B` are Python's):
 * - `.` is any code point but `\n`, `$` the end of the text or a final `\n` before it, `\v` U+000B, `{,n}` `{0,n}`,
 *   a `{` that starts no quantifier and a `[` or `&` inside a class themselves, as Python means them;
 * - under IGNORECASE (the pattern's `ignorecase`), each literal code point is written as its sre class's
 *   representative (PyUnicode.ignoreCaseKey), and [subject] writes each code point of a text that belongs to one
 *   of those classes as its representative too, leaving every other code point as it is. So a literal matches
 *   exactly what sre's IGNORECASE matches (lower(c) or one of re._casefix's extra cases), while `\w`, `\s`, `\d`,
 *   `\b` and `.` read the text's own code points, as sre reads them. Each class a literal of these patterns
 *   belongs to keeps its \w, \s and \d alike and its UTF-16 length (i ı İ, k K, s ſ, ú Ú…); [subject] checks the
 *   length, and maps indexes back when it ever differs.
 *
 * What the rewrite doesn't carry is refused (IllegalArgumentException), so a new pattern in normalize.py that needs
 * more fails loudly: inline flags and named groups, `\N`, `\u`, a backreference or a range under IGNORECASE.
 */
internal class PyPattern(val source: String, val ignoreCase: Boolean) {
    private val translation = translate(source, ignoreCase) { PyUnicode.ignoreCaseKey(it) }
    val regex: Regex = PyRegex.compile(translation.pattern)

    /** `re.search(pattern, s) is not None`. */
    fun search(s: String): Boolean = regex.containsMatchIn(subject(s).text)

    /** `re.sub(pattern, replacement, s)`, the replacement written as it is (it holds no group). */
    fun sub(s: String, replacement: String = ""): String {
        val subject = subject(s)
        val out = StringBuilder(s.length)
        var last = 0
        for (m in regex.findAll(subject.text)) {
            val start = subject.original(m.range.first)
            val end = subject.original(m.range.last + 1)
            out.append(s, last, start).append(replacement)
            last = end
        }
        return out.append(s, last, s.length).toString()
    }

    /** `re.split(pattern, s)`, for a pattern with no group and no empty match. */
    fun split(s: String): List<String> {
        val subject = subject(s)
        val out = ArrayList<String>()
        var last = 0
        for (m in regex.findAll(subject.text)) {
            val start = subject.original(m.range.first)
            out += s.substring(last, start)
            last = subject.original(m.range.last + 1)
        }
        out += s.substring(last)
        return out
    }

    /** `pattern.match(s, at).end()`, or null: indexes in UTF-16 units (no IGNORECASE). */
    fun matchEnd(s: String, at: Int): Int? {
        require(!ignoreCase) { "matchEnd reads no IGNORECASE pattern" }
        if (at > s.length) return null
        return regex.matchAt(s, at)?.let { it.range.last + 1 }
    }

    /** A text as the translated pattern reads it: under IGNORECASE, its code points of the pattern's classes
     * written as their representatives. */
    fun subject(s: String): Subject {
        if (!ignoreCase) return Subject(s, null)
        val keys = translation.keys
        val out = StringBuilder(s.length)
        var i = 0
        var resized = false
        while (i < s.length) {
            val cp = s.codePointAt(i)
            val key = PyUnicode.ignoreCaseKey(cp)
            val written = if (key in keys) key else cp
            if (Character.charCount(written) != Character.charCount(cp)) resized = true
            out.appendCodePoint(written)
            i += Character.charCount(cp)
        }
        if (!resized) return Subject(out.toString(), null)
        // An index of the text written is an index of the original's: a map from one to the other.
        val index = IntArray(out.length + 1)
        var from = 0
        var to = 0
        while (from < s.length) {
            val cp = s.codePointAt(from)
            val key = PyUnicode.ignoreCaseKey(cp)
            val written = if (key in keys) key else cp
            for (k in 0 until Character.charCount(written)) index[to + k] = from
            to += Character.charCount(written)
            from += Character.charCount(cp)
        }
        index[to] = from
        return Subject(out.toString(), index)
    }

    class Subject(val text: String, private val index: IntArray?) {
        fun original(i: Int): Int = index?.get(i) ?: i
    }

    /** A pattern rewritten ([translate]), and the representatives of its literals (IGNORECASE). */
    data class Translation(val pattern: String, val keys: Set<Int>)

    companion object {
        /** [source], Python's pattern, as one java.util.regex and Python read alike (the class's doc). */
        fun translate(source: String, ignoreCase: Boolean, key: (Int) -> Int): Translation {
            val out = StringBuilder(source.length + 16)
            val keys = HashSet<Int>()
            var i = 0
            var inClass = false
            var classItems = 0  // the items written so far in the class we are in
            fun literal(cp: Int) {
                val written = if (ignoreCase) key(cp).also { keys += it } else cp
                if (written < 0x80 && !isAsciiAlnum(written) && written != ' '.code) out.append('\\')
                out.appendCodePoint(written)
            }
            fun refuse(why: String): Nothing = throw IllegalArgumentException("$why in the pattern ${source}")
            while (i < source.length) {
                val cp = source.codePointAt(i)
                i += Character.charCount(cp)
                if (cp == '\\'.code) {
                    if (i >= source.length) refuse("a trailing backslash")
                    val e = source.codePointAt(i)
                    i += Character.charCount(e)
                    when (e) {
                        's'.code, 'S'.code, 'w'.code, 'W'.code, 'd'.code, 'D'.code -> out.append('\\').appendCodePoint(e)
                        'b'.code, 'B'.code -> if (inClass) refuse("\\b in a class") else out.append('\\').appendCodePoint(e)
                        'n'.code, 't'.code, 'r'.code, 'f'.code -> out.append('\\').appendCodePoint(e)
                        'v'.code -> out.append("\\x0B")
                        'x'.code -> {
                            if (ignoreCase) refuse("a \\x escape under IGNORECASE")
                            if (i + 2 > source.length || !isHex(source[i].code) || !isHex(source[i + 1].code)) refuse("a bad \\x escape")
                            out.append("\\x").append(source, i, i + 2)
                            i += 2
                        }
                        in '1'.code..'9'.code ->
                            if (inClass || ignoreCase) refuse("a backreference here") else out.append('\\').appendCodePoint(e)
                        else -> if (isAsciiAlnum(e)) refuse("the escape \\${String(Character.toChars(e))}") else literal(e)
                    }
                    if (inClass) classItems++
                    continue
                }
                if (inClass) {
                    when (cp) {
                        ']'.code -> if (classItems == 0) { out.append("\\]"); classItems++ } else { out.append(']'); inClass = false }
                        '-'.code -> {
                            val atEnd = i < source.length && source[i] == ']'
                            if (classItems > 0 && !atEnd) {
                                if (ignoreCase) refuse("a range under IGNORECASE")
                                out.append('-')
                            } else {
                                out.append("\\-")
                                classItems++
                            }
                        }
                        '['.code, '&'.code, '^'.code -> { out.append('\\').appendCodePoint(cp); classItems++ }
                        else -> { literal(cp); classItems++ }
                    }
                    continue
                }
                when (cp) {
                    '['.code -> {
                        out.append('[')
                        inClass = true
                        classItems = 0
                        if (i < source.length && source[i] == '^') { out.append('^'); i++ }
                    }
                    '.'.code -> out.append("[^\\n]")
                    '$'.code -> out.append("(?=\\n?\\z)")
                    '^'.code, '|'.code, ')'.code, '*'.code, '+'.code, '?'.code -> out.appendCodePoint(cp)
                    '('.code -> {
                        out.append('(')
                        if (i < source.length && source[i] == '?') {
                            val rest = source.substring(i)
                            val opening = listOf("?:", "?=", "?!", "?<=", "?<!").firstOrNull { rest.startsWith(it) }
                                ?: refuse("the group (${rest.take(3)}")
                            out.append(opening)
                            i += opening.length
                        }
                    }
                    '{'.code -> {
                        val close = source.indexOf('}', i)
                        val body = if (close < 0) null else source.substring(i, close)
                        if (body != null && isQuantifier(body)) {
                            out.append('{').append(if (body.startsWith(",")) "0$body" else body).append('}')
                            i = close + 1
                        } else {
                            out.append("\\{")
                        }
                    }
                    else -> literal(cp)
                }
            }
            if (inClass) refuse("an unclosed class")
            return Translation(out.toString(), keys)
        }

        private fun isQuantifier(body: String): Boolean {
            val comma = body.indexOf(',')
            val parts = if (comma < 0) listOf(body) else listOf(body.substring(0, comma), body.substring(comma + 1))
            if (parts.size == 2 && body.indexOf(',', comma + 1) >= 0) return false
            if (parts.all { it.isEmpty() }) return false
            if (comma < 0 && body.isEmpty()) return false
            return parts.all { p -> p.all { it in '0'..'9' } }
        }

        private fun isAsciiAlnum(cp: Int): Boolean = cp in '0'.code..'9'.code || cp in 'a'.code..'z'.code || cp in 'A'.code..'Z'.code
        private fun isHex(cp: Int): Boolean = cp in '0'.code..'9'.code || cp in 'a'.code..'f'.code || cp in 'A'.code..'F'.code
    }
}
