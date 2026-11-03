package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex

/**
 * One of normalize.py's patterns (or library.py's), as Python's re reads it, for the few calls normalize.py makes
 * of it: [search], [sub] with a literal replacement, [split] and [matchEnd] (`pattern.match(text, pos)`).
 *
 * [source] is Python's own text and core.py.PyRegex compiles it, IGNORECASE as a leading `(?i)`, which it reads as
 * sre does (a literal stands for its case class, `\w \s \d \b` read the text as it is); [PyRe] steps over a text as
 * Python's re functions do.
 */
internal class KeyPattern(val source: String, val ignoreCase: Boolean) {
    val regex: Regex = PyRegex.compile(if (ignoreCase) IGNORECASE + source else source)

    /** `re.search(pattern, s) is not None`. */
    fun search(s: String): Boolean = PyRe.search(regex, s) != null

    /** `re.sub(pattern, replacement, s)`, the replacement written as it is (it holds no group reference). */
    fun sub(s: String, replacement: String = ""): String = PyRe.sub(regex, s) { replacement }

    /** `re.split(pattern, s)`, for a pattern with no group. */
    fun split(s: String): List<String> = PyRe.split(regex, s).map { requireNotNull(it) { "a group in $source" } }

    /** `pattern.match(s, at).end()`, or null; indexes in UTF-16 units. */
    fun matchEnd(s: String, at: Int): Int? {
        if (at > s.length) return null
        return regex.matchAt(s, at)?.let { it.range.last + 1 }
    }

    private companion object {
        /** re.IGNORECASE, as an inline flag at the start of a pattern. */
        const val IGNORECASE = "(?i)"
    }
}
