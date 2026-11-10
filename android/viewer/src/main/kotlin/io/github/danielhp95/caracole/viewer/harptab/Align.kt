package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import java.math.BigInteger
import java.util.IdentityHashMap
import kotlin.math.abs

/**
 * Holes over syllables, as harptab.py places them (its docstring's "Holes over syllables"): `syllable_starts`,
 * `align` and its steps (`_snapped`, `_split_words`, `_held`, `_places`, `_parts`), and the cuts of a word with no
 * hyphen (`_cuts`, `_rank`). Every column is a code point, Python's: a row's groups come at code-point columns
 * ([Scan]'s), and its words are read as code points too ([Text]). The cuts' costs are summed as Python's builtin sum
 * sums floats (core.py.Py.fsum), and `math.comb`'s counts are exact (BigInteger), so a word's every way is weighed or
 * none, as Python's.
 */
internal object Align {
    private val B = HarptabData

    /** `(?:-+|[,.;!?])(?=[^\W\d_])`: a syllable's start inside a word, after a hyphen or a comma. */
    private val INSIDE: Regex by lazy { PyRegex.compile("""(?:-+|[,.;!?])(?=[^\W\d_])""") }

    /** A text as Python indexes it: its code points, and each UTF-16 place's code point. */
    class Text(val text: String) {
        val cps: IntArray = Py.codePoints(text)
        private val place: IntArray = IntArray(text.length + 1).also { out ->
            var cp = 0
            var i = 0
            while (i < text.length) {
                val n = Character.charCount(text.codePointAt(i))
                for (k in 0 until n) out[i + k] = cp
                i += n
                cp++
            }
            out[text.length] = cp
        }

        val size: Int get() = cps.size

        /** The code-point place of the UTF-16 place [at]. */
        fun cp(at: Int): Int = place[at]

        /** `text[a:b]`, as Python slices it. */
        fun slice(a: Int, b: Int): String {
            val from = a.coerceIn(0, size)
            val to = b.coerceIn(0, size)
            return if (to <= from) "" else Py.string(cps, from, to)
        }

        /** Each match of [regex] (`finditer`) as its code-point start and end. */
        fun spans(regex: Regex): List<IntArray> =
            PyRe.finditer(regex, text).map { intArrayOf(cp(it.range.first), cp(it.range.last + 1)) }.toList()
    }

    /** harptab.syllable_starts: the columns a syllable of [lyric] starts at. */
    fun syllableStarts(lyric: String): List<Int> {
        val text = Text(lyric)
        val starts = sortedSetOf<Int>()
        for (m in PyRe.finditer(B.WORD, lyric)) {
            val start = text.cp(m.range.first)
            starts += start
            val word = Text(m.value)
            for (h in PyRe.finditer(INSIDE, m.value)) {
                if (h.range.first > 0) starts += start + word.cp(h.range.last + 1)
            }
        }
        return starts.toList()
    }

    /** harptab.align: [row] with each group placed on a column of its words ([Row.parts], [Row.placement]); a row
     * played alone is one part, and a row shown as written none (its placement as it was). */
    fun align(row: Row, reach: Int = B.REACH): Row {
        if (!row.trusted) return row.copy(parts = emptyList())
        val written = row.lyric ?: return row.copy(parts = if (row.groups.isNotEmpty()) listOf(row.groups.toList() to "") else emptyList())
        val lyric = HarpTabText.rstrip(written)
        val text = Text(lyric)
        val words = text.spans(B.WORD)
        val groups = row.groups.filter { it.holes.isNotEmpty() }  // what it couldn't read goes with them, after
        val atOf = snapped(groups, syllableStarts(lyric), reach)
        val placement = LinkedHashMap<String, Int>()
        placement["snap"] = atOf.size
        splitWords(text, words, groups, atOf, placement)
        held(groups, words, atOf, placement)
        return row.copy(parts = parts(text, places(row.groups, groups, atOf)), placement = placement)
    }

    /** harptab._snapped: each group of holes (by its place in [groups]) on the syllable start nearest it, within
     * [reach] columns of where it is written or its number, one a start, the nearest pairs first; one placed before a
     * group written before it loses its place. */
    private fun snapped(groups: List<Group>, starts: List<Int>, reach: Int): MutableMap<Int, Int> {
        val pairs = ArrayList<IntArray>()
        for ((n, g) in groups.withIndex()) for (s in starts) {
            val near = minOf(abs(s - g.col), abs(s - g.digit))
            if (near <= reach) pairs += intArrayOf(near, if (g.digit < s) 1 else 0, s, n)
        }
        pairs.sortWith { x, y ->
            (0 until 4).asSequence().map { x[it].compareTo(y[it]) }.firstOrNull { it != 0 } ?: 0
        }
        val atOf = LinkedHashMap<Int, Int>()
        val taken = HashSet<Int>()
        for (p in pairs) {
            val s = p[2]
            val n = p[3]
            if (n !in atOf && s !in taken) {
                atOf[n] = s
                taken += s
            }
        }
        for (n in atOf.keys.sorted()) {
            val here = atOf.getValue(n)
            if (atOf.any { (m, at) -> m < n && at > here }) atOf.remove(n)?.let { taken.remove(it) }
        }
        return atOf
    }

    /** harptab._split_words: the holes left over inside a word with no hyphen there placed where they cut it best. */
    private fun splitWords(text: Text, words: List<IntArray>, groups: List<Group>, atOf: MutableMap<Int, Int>,
                           placement: MutableMap<String, Int>) {
        for ((a, b) in words) {
            val inside = groups.indices.filter { n ->
                val digit = groups[n].digit
                n !in atOf && a < digit && digit < b && PyUnicode.isAlpha(text.cps[digit])
            }
            if (inside.isEmpty()) continue
            val fixed = (setOf(a, b) + atOf.values.filter { a < it && it < b }).sorted()
            for ((n, cut) in inside.zip(cuts(text, a, b, inside.map { groups[it].digit }, fixed))) {
                if (cut != null) {
                    atOf[n] = cut
                    placement.merge("split", 1, Int::plus)
                }
            }
        }
    }

    /** harptab._held: each hole still left on the place before it (a melisma), or, before every place, the next
     * word. */
    private fun held(groups: List<Group>, words: List<IntArray>, atOf: MutableMap<Int, Int>, placement: MutableMap<String, Int>) {
        for ((n, g) in groups.withIndex()) {
            if (n in atOf) continue
            val before = (0 until n).lastOrNull { it in atOf }
            if (before != null) {
                atOf[n] = atOf.getValue(before)
                placement.merge("held", 1, Int::plus)
            } else {
                atOf[n] = words.firstOrNull { it[0] >= g.digit }?.get(0) ?: (if (words.isNotEmpty()) words[0][0] else 0)
                placement.merge("gap", 1, Int::plus)
            }
        }
    }

    /** harptab._places: each column a place starts at, and the groups of the row there: those of holes where [atOf]
     * puts them, what it couldn't read with the hole it touches after it, else the one before it (by identity, as
     * Python's `id`). */
    private fun places(rowGroups: List<Group>, groups: List<Group>, atOf: Map<Int, Int>): Map<Int, List<Group>> {
        val place = IdentityHashMap<Group, Int>()
        for ((n, g) in groups.withIndex()) place[g] = atOf.getValue(n)
        for (g in rowGroups) {
            if (g.holes.isNotEmpty()) continue
            val after = groups.firstOrNull { it.col == g.end }
            val before = groups.lastOrNull { it.col < g.col }
            place[g] = place.getValue(after ?: before ?: groups[0])
        }
        val places = LinkedHashMap<Int, MutableList<Group>>()
        for (g in rowGroups) places.getOrPut(place.getValue(g)) { ArrayList() } += g
        return places
    }

    /** harptab._parts: the row's words cut at each place, with its groups; the words before the first place a part
     * with none. */
    private fun parts(text: Text, places: Map<Int, List<Group>>): List<Pair<List<Group>, String>> {
        val cuts = places.keys.sorted()
        val parts = ArrayList<Pair<List<Group>, String>>()
        if (cuts.isNotEmpty() && cuts[0] > 0 && Py.strip(text.slice(0, cuts[0])).isNotEmpty()) {
            parts += emptyList<Group>() to text.slice(0, cuts[0])
        }
        for ((n, at) in cuts.withIndex()) {
            val end = if (n + 1 < cuts.size) cuts[n + 1] else text.size
            parts += places.getValue(at).toList() to text.slice(at, end)
        }
        return parts
    }

    /** harptab._rank: how well a word cut before [k] reads as a syllable break. */
    private fun rank(text: Text, k: Int): Double {
        val l1 = text.cps[k - 1]
        val r1 = text.cps[k]
        val r2 = if (k + 1 < text.size) text.cps[k + 1] else -1
        val vowels = B.VOWELS
        if (l1 !in vowels && r1 !in vowels && PyUnicode.lower(Py.string(intArrayOf(l1, r1))) !in B.DIGRAPHS) return 0.0
        if (l1 in vowels && r1 !in vowels && r2 >= 0 && r2 in vowels) return 0.8
        return 1.6
    }

    /** harptab._cuts on a lyric given as text. */
    fun cuts(lyric: String, a: Int, b: Int, anchors: List<Int>, fixed: List<Int>): List<Int?> = cuts(Text(lyric), a, b, anchors, fixed)

    /** harptab._cuts: where to cut the word from [a] to [b] for the holes written at [anchors] inside it, in their
     * order, the cheapest set that leaves each piece a vowel; [fixed], the word's ends and the places already in it.
     * Fewer cuts when not every hole can have one, and fewer when there are more ways than MAX_CUTS to weigh. */
    private fun cuts(text: Text, a: Int, b: Int, anchors: List<Int>, fixed: List<Int>): List<Int?> {
        val fixedSet = fixed.toSortedSet()
        val spots = (a + 1 until b).filter { k ->
            k !in fixedSet && PyUnicode.isAlpha(text.cps[k - 1]) && PyUnicode.isAlpha(text.cps[k])
        }
        val most = BigInteger.valueOf(B.MAX_CUTS.toLong())
        for (count in minOf(anchors.size, spots.size) downTo 1) {
            if (comb(anchors.size, count) * comb(spots.size, count) > most) continue
            var best: Pair<IntArray, IntArray>? = null
            var bestCost = 0.0
            for (chosen in combinations(anchors.size, count)) {
                for (picked in combinations(spots.size, count)) {
                    val cut = IntArray(count) { spots[picked[it]] }
                    val bounds = (fixedSet + cut.toList()).toSortedSet().toList()
                    if (!(0 until bounds.size - 1).all { hasVowel(text, bounds[it], bounds[it + 1]) }) continue
                    val cost = Py.fsum((0 until count).map { 0.6 * abs(anchors[chosen[it]] - (cut[it] + 1)) + rank(text, cut[it]) })
                    if (best == null || cost < bestCost) {
                        best = chosen to cut
                        bestCost = cost
                    }
                }
            }
            if (best != null) {
                val out = arrayOfNulls<Int>(anchors.size)
                for (i in 0 until count) out[best.first[i]] = best.second[i]
                return out.toList()
            }
        }
        return List(anchors.size) { null }
    }

    /** `_VOWELS.intersection(lyric[x:y])`. */
    private fun hasVowel(text: Text, x: Int, y: Int): Boolean {
        for (i in maxOf(0, x) until minOf(y, text.size)) if (text.cps[i] in B.VOWELS) return true
        return false
    }

    /** math.comb(n, k), exact. */
    private fun comb(n: Int, k: Int): BigInteger {
        if (k < 0 || k > n) return BigInteger.ZERO
        val r = minOf(k, n - k)
        var out = BigInteger.ONE
        for (i in 1..r) out = out * BigInteger.valueOf((n - r + i).toLong()) / BigInteger.valueOf(i.toLong())
        return out
    }

    /** itertools.combinations(range(n), k): each in lexicographic order, a fresh array. */
    private fun combinations(n: Int, k: Int): Sequence<IntArray> = sequence {
        if (k > n) return@sequence
        val idx = IntArray(k) { it }
        while (true) {
            yield(idx.copyOf())
            var i = k - 1
            while (i >= 0 && idx[i] == i + n - k) i--
            if (i < 0) break
            idx[i]++
            for (j in i + 1 until k) idx[j] = idx[j - 1] + 1
        }
    }
}
