package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * harptab._Tokens: a notation compiled, where a hole may start (its before-symbols, then its number), one symbol of
 * each place, an effect written apart, a join, holes together (`7,8B`). [sources] are the Python patterns each was
 * compiled from (start, before, after, apart, join, together), as harptab._tokens writes them, which
 * vectors/viewer/harptab_read.jsonl's `tokens_of` records compare to the character; [fold]'s are compiled with
 * re.I, as `(?i)` before them.
 */
class Tokens internal constructor(val sources: List<String?>, val fold: Boolean) {
    private fun compiled(n: Int): Regex? = sources[n]?.let { PyRegex.compile(if (fold) "(?i)$it" else it) }

    internal val start: Regex = compiled(0)!!
    internal val before: Regex? = compiled(1)
    internal val after: Regex? = compiled(2)
    internal val apart: Regex? = compiled(3)
    internal val join: Regex? = compiled(4)
    internal val together: Regex? = compiled(5)

    companion object {
        private val cache = object : LinkedHashMap<Notation, Tokens>(16, 0.75f, true) {
            override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Notation, Tokens>?): Boolean = size > 64
        }

        /** harptab._tokens: [notation]'s tokenizer, the last 64 kept. */
        fun of(notation: Notation): Tokens = synchronized(cache) { cache.getOrPut(notation) { compile(notation) } }

        private fun compile(notation: Notation): Tokens {
            fun texts(at: String, vararg means: String): List<String> =
                notation.symbols.filter { it.at == at && (means.isEmpty() || it.means in means) }.map { it.text }

            fun one(found: List<String>): String? = if (found.isNotEmpty()) alt(found) else null

            val before = texts("before")
            val after = texts("after")
            val pre = if (before.isNotEmpty()) "(?:${alt(before)}){0,4}" else ""
            val together = texts("between", "together")
            val apart = texts("after", *HarptabData.EFFECTS.toTypedArray(), "mark")
            val num = HarptabData.NUM
            return Tokens(listOf(
                "(?P<pre>$pre)(?P<num>$num)",
                one(before),
                one(after),
                if (apart.isNotEmpty()) "(?<![^\\W\\d_])(?:" + alt(apart, alone = true) + ")" else null,
                one(notation.symbols.filter { it.at == "between" && it.means != "together" }.map { it.text }),
                if (together.isNotEmpty()) "(?P<body>$num(?:(?:${alt(together)})$num)+)" else null,
            ), notation.fold)
        }

        /** harptab._alt: one of [texts], the longest first (then by code point); [alone]: a text that starts or ends
         * with a letter touches no other. */
        fun alt(texts: Collection<String>, alone: Boolean = false): String {
            fun one(t: String): String {
                if (!alone) return escape(t)
                val first = if (t.isEmpty()) -1 else t.codePointAt(0)
                val last = if (t.isEmpty()) -1 else t.codePointBefore(t.length)
                return (if (first >= 0 && PyUnicode.isAlpha(first)) "(?<![^\\W\\d_])" else "") + escape(t) +
                    (if (last >= 0 && PyUnicode.isAlpha(last)) "(?![^\\W\\d_])" else "")
            }
            val sorted = LinkedHashSet(texts).sortedWith(compareBy<String> { -Py.len(it) }.then(Py.CODE_POINT_ORDER))
            return sorted.joinToString("|") { one(it) }
        }

        /** re.escape: each of `()[]{}?*+-|^$\.&~# \t\n\r\v\f` after a backslash, the rest as it is. */
        fun escape(t: String): String = buildString(t.length * 2) {
            for (c in t) {
                if (c in SPECIAL) append('\\')
                append(c)
            }
        }

        private const val SPECIAL = "()[]{}?*+-|^$\\.&~# \t\n\r\u000b\u000c"
    }
}
