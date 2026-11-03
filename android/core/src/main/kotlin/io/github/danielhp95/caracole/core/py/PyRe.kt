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
                // Checked, not trusted: an engine that read the guard otherwise could match empty here forever.
                m = nonEmpty(regex).matchAt(s, at)?.takeIf { it.range.first == at && it.range.last + 1 > at }
                    ?.let(::withoutTheGuard)
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

    /**
     * [regex] matching only where it ends after it began. Its group 1, before [regex]'s own, takes the rest of the
     * text where the match begins, and the match may not end where that rest begins again, which only the place it
     * began does. No `(?!\G)`: Android's ICU answers a `\G` inside a lookaround as though no match were there, so a
     * pattern whose first alternative is empty (`|c+`, `b{,2}|c+`) matched empty again and never found the longer
     * one (CorpusOnDeviceTest, unicode/regex.jsonl). [regex]'s groups are one further on in it, its numbered
     * backreferences moved with them ([referencesMoved]), and [withoutTheGuard] gives the match [regex]'s own groups.
     */
    private fun nonEmpty(regex: Regex): Regex = synchronized(NON_EMPTY) {
        NON_EMPTY.getOrPut(regex) {
            Regex("(?=((?s:.*)))(?:" + referencesMoved(regex.pattern) + ")(?!\\1)", regex.options)
        }
    }

    /**
     * [pattern] with each numbered backreference to the next group: `(?:\N)`, as PyPattern writes one, outside a
     * class and not escaped, becomes `(?:\N+1)`. A named one (`\k<name>`) refers to its group by its name.
     */
    internal fun referencesMoved(pattern: String): String {
        val out = StringBuilder(pattern.length + 8)
        var i = 0
        var inClass = 0
        while (i < pattern.length) {
            val c = pattern[i]
            if (c == '\\') {
                out.append(pattern, i, minOf(i + 2, pattern.length))
                i += 2
                continue
            }
            if (inClass == 0 && pattern.startsWith("(?:\\", i)) {
                var j = i + 4
                while (j < pattern.length && pattern[j] in '0'..'9') j++
                if (j > i + 4 && j < pattern.length && pattern[j] == ')') {
                    out.append("(?:\\").append(pattern.substring(i + 4, j).toInt() + 1).append(')')
                    i = j + 1
                    continue
                }
            }
            if (c == '[') inClass++ else if (c == ']' && inClass > 0) inClass--
            out.append(c)
            i++
        }
        return out.toString()
    }

    /** A match of [nonEmpty]'s pattern as its pattern's own: group 1, the guard's, left out. */
    private fun withoutTheGuard(m: MatchResult): MatchResult = object : MatchResult {
        override val range: IntRange get() = m.range
        override val value: String get() = m.value
        override val groups: MatchGroupCollection = object : AbstractCollection<MatchGroup?>(), MatchNamedGroupCollection {
            override val size: Int get() = m.groups.size - 1
            override fun iterator(): Iterator<MatchGroup?> = (0 until size).map { get(it) }.iterator()
            override fun get(index: Int): MatchGroup? = m.groups[if (index == 0) 0 else index + 1]
            override fun get(name: String): MatchGroup? = (m.groups as MatchNamedGroupCollection)[name]
        }
        override val groupValues: List<String> get() = groups.map { it?.value ?: "" }
        override fun next(): MatchResult? = m.next()?.let(::withoutTheGuard)
    }

    private val NON_EMPTY = java.util.WeakHashMap<Regex, Regex>()

    /** re.findall: each match's text, or its one group's ("" where the group took no part). */
    fun findall(regex: Regex, s: String): List<String> {
        val groups = groupCount(regex)
        require(groups <= 1) { "re.findall of a pattern with $groups groups answers tuples: ${regex.pattern}" }
        return finditer(regex, s).map { if (groups == 0) it.value else it.groups[1]?.value ?: "" }.toList()
    }

    /** re.split: the text between the matches, each match's groups after it (null where one took no part); at
     * most [maxsplit] splits when it is above 0, and none when it is below, as Python's loop reads it. */
    fun split(regex: Regex, s: String, maxsplit: Int = 0): List<String?> {
        if (maxsplit < 0) return listOf(s)
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

    /** re.sub with a function: each match (the first [count], when it is above 0; none, when it is below) replaced
     * by what [repl] makes of it. */
    fun sub(regex: Regex, s: String, count: Int = 0, repl: (MatchResult) -> String): String {
        if (count < 0) return s
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
