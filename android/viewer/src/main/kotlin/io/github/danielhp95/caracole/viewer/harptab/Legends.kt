package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * A tab's legend, as harptab.py reads one: `legend` (each block of two or more adjacent lines `SYM = meaning`),
 * `_meaning` by `_LEXICON`, `_entry` and `_template` (a symbol written with a placeholder for its hole), and what the
 * candidates make of it: `_where` (a symbol placed where the tab's lines write it), `_agrees`, `_with_legend` and
 * `_agreement`.
 */
internal object Legends {
    private val B = HarptabData

    fun legend(lines: List<String>): List<Legend> {
        val blocks = ArrayList<List<Pair<Int, Symbol?>>>()
        var run = ArrayList<Pair<Int, Symbol?>>()
        for ((n, line) in (lines + "").withIndex()) {
            var m = if (Py.strip(line).isNotEmpty() && B.URL.find(line) == null) PyRe.match(B.LEGEND_LINE, line) else null
            if (m != null) {
                val sym = m.groups["sym"]!!.value
                if ("=" !in m.groups["sep"]!!.value && PyUnicode.allAlpha(sym) && Py.len(sym) > 2) m = null
            }
            if (m != null) {
                run.add(n to entry(m.groups["sym"]!!.value, m.groups["meaning"]!!.value))
                continue
            }
            if (run.count { it.second != null } >= 2) {
                while (run.isNotEmpty() && run.last().second == null) run.removeAt(run.size - 1)
                while (run.isNotEmpty() && run.first().second == null) run.removeAt(0)
                blocks += run
            }
            run = ArrayList()
        }
        return blocks.map { block ->
            Legend(block.map { (n, _) -> HarpTabText.rstrip(lines[n]) }, block.mapNotNull { it.second }.distinct(),
                   block.map { it.first })
        }
    }

    /** harptab._meaning: the meaning a legend's words name first, or null. */
    fun meaning(text: String): String? {
        val folded = HarpTabText.foldAccents(text)
        var best: Pair<Int, String>? = null
        for ((means, pattern) in B.LEXICON) {
            val m = pattern.find(folded) ?: continue
            val start = m.range.first
            if (best == null || start < best.first || (start == best.first && Py.CODE_POINT_ORDER.compare(means, best.second) < 0)) {
                best = start to means
            }
        }
        return best?.second
    }

    /** harptab._entry: one line of a legend as a symbol. */
    fun entry(sym: String, meaning: String): Symbol? {
        val means = meaning(meaning) ?: return null
        if (B.URL.find(sym) != null || B.URL.find(meaning) != null) return null
        var count = 1
        if (means == "bend") count = if (B.THREE.find(meaning) != null) 3 else if (B.TWO.find(meaning) != null) 2 else 1
        return template(sym, means, count)
    }

    /** harptab._template: a symbol written with a placeholder for its hole, placed where the placeholder says, or
     * `at` "" with none; null where nothing can go. */
    fun template(sym: String, means: String, count: Int = 1): Symbol? {
        val found = PyRe.finditer(B.PLACEHOLDER, sym).toList()
        if (found.isEmpty()) {
            val cps = Py.codePoints(sym)
            if (cps.size > 1 && cps.toSet().size == 1 && means == "bend") {
                return Symbol(String(Character.toChars(cps[0])), means, "", maxOf(1, Math.floorDiv(count, cps.size)))
            }
            return Symbol(sym, means, "", count)
        }
        if (found.size == 1) {
            val a = found[0].range.first
            val b = found[0].range.last + 1
            val pre = sym.substring(0, a)
            var post = sym.substring(b)
            val close = B.CLOSE[pre]
            if (close != null && post.startsWith(close.substring(1))) {
                post = post.substring(1)
                if (post.isEmpty()) return if (means in B.BREATHS) Symbol(close, means, "around", count) else null
                return Symbol(post, means, "after", count)
            }
            if (pre.isEmpty() && post.isEmpty()) {
                return if (means in B.BREATHS) Symbol("", means, "bare") else Symbol(sym, means, "", count)
            }
            if (pre.isNotEmpty() && (post.isEmpty() || means in B.BREATHS)) return Symbol(pre, means, "before", count)
            return Symbol(post, means, "after", count)
        }
        val between = PyText.strip(sym.substring(found[0].range.last + 1, maxOf(found[0].range.last + 1, found[1].range.first)),
                                   "()[]{}")
        return if (found.size == 2 && between.isNotEmpty() && (means == "join" || means == "together" || means in B.EFFECTS) &&
            means != "hold") Symbol(between, means, "between") else null
    }

    private val literals = object : LinkedHashMap<Pair<String, Boolean>, Regex>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Pair<String, Boolean>, Regex>?): Boolean = size > 256
    }

    /** `re.compile(re.escape(text), re.I if folded else 0)`. */
    private fun literal(text: String, folded: Boolean): Regex = synchronized(literals) {
        literals.getOrPut(text to folded) { PyRegex.compile((if (folded) "(?i)" else "") + Tokens.escape(text)) }
    }

    /** harptab._where: a legend's symbol placed where the tab's lines of holes write it, or null when they never
     * write it. */
    fun where(sym: Symbol, lines: List<String>): Symbol? {
        if (sym.at == "bare") return sym
        if (sym.at == "around") return if (lines.any { B.NUM_IN_BRACKETS.find(it) != null }) sym else null
        val folded = sym.text.codePoints().anyMatch { PyUnicode.isAlpha(it) }
        val pattern = literal(sym.text, folded)
        val hits = ArrayList<Triple<String, Int, Int>>()
        for (line in lines) for (m in PyRe.finditer(pattern, line)) hits += Triple(line, m.range.first, m.range.last + 1)
        if (hits.isEmpty()) return null
        if (sym.at.isNotEmpty()) return sym
        if (sym.means in B.EFFECTS || sym.means == "mark") return sym.copy(at = "after")
        val before = hits.count { (line, _, b) ->
            PyRe.match(B.HOLE_AFTER, line.substring(b, HarpTabText.forward(line, b, 3))) != null
        }
        val after = hits.count { (line, a, _) ->
            B.HOLE_BEFORE.find(line.substring(HarpTabText.back(line, a, 3), a)) != null
        }
        return sym.copy(at = if (before > after) "before" else "after")
    }

    /** harptab._agrees: whether [notation] reads the legend's [sym] as the legend says. */
    fun agrees(notation: Notation, sym: Symbol): Boolean {
        if (sym.at == "bare") return notation.bare == sym.means
        val own = notation.meaning(sym.text, sym.at)
            ?: if (notation.fold) notation.meaning(HarpTabText.swapcase(sym.text), sym.at) else null
        if (sym.means == "mark") return (own != null && own.means == "mark") || (own == null && B.DECOR.matchEntire(sym.text) != null)
        return own != null && own.means == sym.means && (sym.means != "bend" || own.count == sym.count)
    }

    /** harptab._with_legend: the preset that agrees with most of a legend's symbols the tab uses ([found], placed),
     * changed as it says, and [found]. */
    fun withLegend(found: List<Symbol>, lines: List<String>): Pair<Notation, List<Symbol>>? {
        if (found.isEmpty()) return null
        val presets = B.PRESETS
        var base = presets[0]
        var most = found.count { agrees(base, it) }
        for (n in presets.drop(1)) {
            val agree = found.count { agrees(n, it) }
            if (agree > most) {
                base = n
                most = agree
            }
        }
        val changes = ArrayList<Symbol>()
        var bare: String? = ""
        val text = lines.joinToString("\n")
        for (sym in found) {
            if (sym.at == "bare") {
                bare = sym.means
                continue
            }
            changes += sym
            val swapped = HarpTabText.swapcase(sym.text)
            if (!base.fold && sym.text != swapped && swapped in text) changes += sym.copy(text = swapped)
        }
        return base.changed(changes, bare = bare) to found
    }

    /** harptab._agreement: the share of [found] [notation] agrees with. */
    fun agreement(notation: Notation, found: List<Symbol>): Double =
        if (found.isEmpty()) 0.0 else found.count { agrees(notation, it) }.toDouble() / found.size
}
