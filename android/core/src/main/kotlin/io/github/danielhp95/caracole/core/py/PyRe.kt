package io.github.danielhp95.caracole.core.py

/**
 * Python's re functions over a [PyRegex.compile]d pattern: the matches Python finds. Kotlin's own findAll, split and
 * replace step over a text by UTF-16 unit after an empty match, and so may match inside a surrogate pair, and never
 * look again where an empty match was. Here, as in Python 3.7+, the search goes on where a match ended (an empty
 * match there included), and after an empty match it first looks for a longer one at the same place (an empty
 * alternative or a lazy quantifier tried first: `|a`, `a*?`), then from the next code point.
 */
object PyRe {
    /** re.search. */
    fun search(regex: Regex, s: String): MatchResult? = regex.find(s)

    /** re.match: a match at the start. */
    fun match(regex: Regex, s: String): MatchResult? = regex.matchAt(s, 0)

    /** re.fullmatch. */
    fun fullmatch(regex: Regex, s: String): MatchResult? = regex.matchEntire(s)

    /** re.finditer. */
    fun finditer(regex: Regex, s: String): Sequence<MatchResult> = sequence {
        var at = 0
        var mustAdvance = false
        while (at <= s.length) {
            var m: MatchResult? = null
            if (mustAdvance) {
                // Checked, not trusted: an engine whose \G were elsewhere could otherwise match empty here forever.
                m = nonEmpty(regex).matchAt(s, at)?.takeIf { it.range.first == at && it.range.last + 1 > at }
                if (m == null) {
                    if (at >= s.length) break
                    at += Character.charCount(s.codePointAt(at))
                }
            }
            if (m == null) m = regex.find(s, at) ?: break
            yield(m)
            at = m.range.last + 1
            mustAdvance = at == m.range.first
        }
    }

    /** [regex] matching only where it ends after it began: `\G` is where the match began, as both
     * java.util.regex and Android's ICU read it at a region's start. */
    private fun nonEmpty(regex: Regex): Regex = synchronized(NON_EMPTY) {
        NON_EMPTY.getOrPut(regex) { Regex("(?:" + regex.pattern + ")(?!\\G)", regex.options) }
    }

    private val NON_EMPTY = java.util.WeakHashMap<Regex, Regex>()

    /** re.findall: each match's text, or its one group's ("" where the group took no part). */
    fun findall(regex: Regex, s: String): List<String> {
        val groups = groupCount(regex)
        require(groups <= 1) { "re.findall of a pattern with $groups groups answers tuples: ${regex.pattern}" }
        return finditer(regex, s).map { if (groups == 0) it.value else it.groups[1]?.value ?: "" }.toList()
    }

    /** re.split: the text between the matches, each match's groups after it (null where one took no part). */
    fun split(regex: Regex, s: String, maxsplit: Int = 0): List<String?> {
        val groups = groupCount(regex)
        val out = ArrayList<String?>()
        var last = 0
        var n = 0
        for (m in finditer(regex, s)) {
            if (maxsplit > 0 && n >= maxsplit) break
            out += s.substring(last, m.range.first)
            for (g in 1..groups) out += m.groups[g]?.value
            last = m.range.last + 1
            n++
        }
        out += s.substring(last)
        return out
    }

    /** re.sub with a function: each match (the first [count], when it isn't 0) replaced by what [repl] makes of it. */
    fun sub(regex: Regex, s: String, count: Int = 0, repl: (MatchResult) -> String): String {
        val out = StringBuilder()
        var last = 0
        var n = 0
        for (m in finditer(regex, s)) {
            if (count > 0 && n >= count) break
            out.append(s, last, m.range.first).append(repl(m))
            last = m.range.last + 1
            n++
        }
        return out.append(s, last, s.length).toString()
    }

    private fun groupCount(regex: Regex): Int = regex.toPattern().matcher("").groupCount()
}
