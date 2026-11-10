package io.github.danielhp95.caracole.core.fuzz

/**
 * rapidfuzz 3.14.5's scorers as caracole's search calls them (search.py `_Query.readings`, lacuerda_index.py), on
 * code points, `processor=None`: a port of its C++ core, rapidfuzz-cpp 3.3.4 (fuzz_impl.hpp, common_impl.hpp), never
 * of its pure-Python fallback, which picks other alignment windows. tests/helpers/rapidfuzz_cpp.py is the Python
 * transcription this follows line for line, and vectors/fuzz/ (tests/test_conformance_fuzz.py) the answers it gives
 * exactly, every double compared with `==` (FuzzTest).
 *
 * - [ratio]: `(1.0 - indel / (len1 + len2)) * 100`, 100 for two empty strings; the Indel distance is
 *   `len1 + len2 - 2 * LCS`, the LCS bit-parallel (Hyyrö's, rapidfuzz's `lcs_blockwise`), exact at any length.
 * - [tokenSortRatio]: [ratio] of each string's words sorted by code point, one space between; a word ends at
 *   rapidfuzz's `is_space`, whose set depends on how CPython stores the string (see [isSpace]).
 * - [partialRatioAlignment]: the full windows searched in bisection order with the score cutoff, then the prefixes,
 *   then the suffixes; the first strictly better wins and 100 returns at once; two strings of one length are tried
 *   both ways.
 * - [extract]: `process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=…, limit=…)`.
 * - [osaDistance]: `rapidfuzz.distance.OSA.distance` (OSA_impl.hpp): the common prefix and suffix taken off, then the
 *   optimal string alignment distance (insertions, deletions, substitutions, and two adjacent characters swapped as
 *   one edit, never edited again), by its dynamic programme, which Hyyrö's bit-parallel one rapidfuzz runs equals; a
 *   distance past [osaDistance]'s cutoff is the cutoff plus one.
 * - [extractDistance]: `process.extract(query, choices, scorer=OSA.distance, score_cutoff=d, limit=None)`, as
 *   match.py's typo route asks it: every choice within the distance, the nearest first, then by index.
 * - [tokenSetRatio]: `fuzz.token_set_ratio` (fuzz_impl.hpp): each string's words sorted and deduplicated, split into
 *   what both hold and what each holds alone; 100 when one's words are all the other's, else the best of the two
 *   rests' ratio and each of them beside the shared words, as rapidfuzz-cpp's arithmetic computes it; 0 when either
 *   has no word.
 *
 * No JDK or ICU text API: a string is read as its UTF-16 units joined into code points by arithmetic alone.
 */
object Fuzz {
    data class Alignment(val score: Double, val srcStart: Int, val srcEnd: Int, val destStart: Int, val destEnd: Int)
    data class Extracted(val choice: String, val score: Double, val index: Int)

    /** One choice [extractDistance] keeps: its [distance] to the query and its [index] among the choices. */
    data class ExtractedDistance(val choice: String, val distance: Int, val index: Int)

    fun ratio(a: String, b: String): Double = ratio(codePoints(a), codePoints(b))

    fun tokenSortRatio(a: String, b: String): Double = ratio(sortedSplit(codePoints(a)), sortedSplit(codePoints(b)))

    fun partialRatioAlignment(a: String, b: String): Alignment = alignment(codePoints(a), codePoints(b))

    /** process.extract with scorer=fuzz.ratio: each choice whose normalized similarity reaches `scoreCutoff / 100`
     * (and whose score then reaches [scoreCutoff], as process_cpp checks), by score, highest first, then by index;
     * [limit] of them, all for null. */
    fun extract(query: String, choices: List<String>, scoreCutoff: Double, limit: Int?): List<Extracted> {
        val q = codePoints(query)
        val pattern = Pattern(q)
        val cutoff = scoreCutoff / 100
        val found = ArrayList<Extracted>()
        choices.forEachIndexed { index, choice ->
            val sim = normalizedSimilarity(pattern, codePoints(choice), cutoff)
            if (sim >= cutoff && sim * 100 >= scoreCutoff) found += Extracted(choice, sim * 100, index)
        }
        found.sortWith(compareByDescending<Extracted> { it.score }.thenBy { it.index })
        return if (limit == null || limit >= found.size) found else found.subList(0, maxOf(limit, 0)).toList()
    }

    /** OSA.distance(a, b, score_cutoff=[scoreCutoff]): the distance, or the cutoff plus one past it (none given:
     * the distance always). */
    fun osaDistance(a: String, b: String, scoreCutoff: Int? = null): Int =
        osa(codePoints(a), codePoints(b), scoreCutoff ?: Int.MAX_VALUE - 1)

    /** process.extract(query, choices, scorer=OSA.distance, score_cutoff=[maxDistance], limit=None): each choice at
     * most [maxDistance] from the query, the nearest first, then by index. */
    fun extractDistance(query: String, choices: List<String>, maxDistance: Int): List<ExtractedDistance> {
        val q = codePoints(query)
        val found = ArrayList<ExtractedDistance>()
        choices.forEachIndexed { index, choice ->
            val d = osa(q, codePoints(choice), maxDistance)
            if (d <= maxDistance) found += ExtractedDistance(choice, d, index)
        }
        found.sortWith(compareBy<ExtractedDistance> { it.distance }.thenBy { it.index })
        return found
    }

    /** fuzz.token_set_ratio(a, b). */
    fun tokenSetRatio(a: String, b: String): Double = tokenSet(sortedWords(codePoints(a)), sortedWords(codePoints(b)))

    // --- code points ------------------------------------------------------------------------------------------

    /** The string's code points, as Python counts them: a surrogate pair is one, a lone surrogate itself. */
    internal fun codePoints(s: String): IntArray {
        val out = IntArray(s.length)
        var n = 0
        var i = 0
        while (i < s.length) {
            val c = s[i].code
            if (c in 0xD800..0xDBFF && i + 1 < s.length && s[i + 1].code in 0xDC00..0xDFFF) {
                out[n++] = 0x10000 + ((c - 0xD800) shl 10) + (s[i + 1].code - 0xDC00)
                i += 2
            } else {
                out[n++] = c
                i += 1
            }
        }
        return if (n == out.size) out else out.copyOf(n)
    }

    // --- Indel ------------------------------------------------------------------------------------------------

    /** PatternMatchVector: for each code point of [s], the bits of its positions, 64 a word. */
    internal class Pattern(val s: IntArray) {
        val words = (s.size + 63) ushr 6
        private val latin = arrayOfNulls<LongArray>(256)
        private val other = HashMap<Int, LongArray>()

        init {
            for ((i, c) in s.withIndex()) {
                val bits = if (c in 0..255) latin[c] ?: LongArray(words).also { latin[c] = it }
                else other.getOrPut(c) { LongArray(words) }
                bits[i ushr 6] = bits[i ushr 6] or (1L shl (i and 63))
            }
        }

        fun bits(c: Int): LongArray? = if (c in 0..255) latin[c] else other[c]
        fun has(c: Int): Boolean = bits(c) != null
    }

    /** The LCS of the pattern's string and `t[from until to]`, bit-parallel: a 0 in `v` is a character of the
     * pattern's in the LCS so far (rapidfuzz-cpp's lcs_unroll and lcs_blockwise). */
    internal fun lcs(p: Pattern, t: IntArray, from: Int = 0, to: Int = t.size): Int {
        if (p.words == 0 || from >= to) return 0
        val v = LongArray(p.words) { -1L }
        for (k in from until to) {
            val m = p.bits(t[k]) ?: continue
            var carry = 0L
            for (w in 0 until p.words) {
                val s = v[w]
                val u = s and m[w]
                val partial = s + carry
                var out = if (java.lang.Long.compareUnsigned(partial, carry) < 0) 1L else 0L
                val x = partial + u
                if (java.lang.Long.compareUnsigned(x, u) < 0) out = 1L
                v[w] = x or (s - u)
                carry = out
            }
        }
        var zeros = 0
        for (w in 0 until p.words) zeros += java.lang.Long.bitCount(v[w].inv())
        return zeros
    }

    private fun indel(p: Pattern, t: IntArray, from: Int = 0, to: Int = t.size): Int =
        p.s.size + (to - from) - 2 * lcs(p, t, from, to)

    /** rapidfuzz-cpp's `_normalized_similarity` with [cutoff] in [0, 1]: `1.0 - indel / (len1 + len2)`, or 0 below
     * the cutoff. Its distance cutoff is exact for every length a name has, so the distance is always computed. */
    private fun normalizedSimilarity(p: Pattern, t: IntArray, cutoff: Double, from: Int = 0, to: Int = t.size): Double {
        val maximum = p.s.size + (to - from)
        val dist = if (maximum == 0) 0 else indel(p, t, from, to)
        val normDist = if (maximum != 0) dist.toDouble() / maximum.toDouble() else 0.0
        val cutoffDist = minOf(1.0, 1.0 - cutoff + 0.00001)
        val sim = 1.0 - (if (normDist <= cutoffDist) normDist else 1.0)
        return if (sim >= cutoff) sim else 0.0
    }

    private fun ratio(a: IntArray, b: IntArray): Double = normalizedSimilarity(Pattern(a), b, 0.0) * 100

    // --- token sort -------------------------------------------------------------------------------------------

    /** common_impl.hpp's `is_space`: for a string CPython stores in one byte a character (every code point at most
     * U+00FF), ASCII's whitespace alone; for a wider one, U+0085, NBSP and the Unicode spaces too. */
    internal fun isSpace(c: Int, wide: Boolean): Boolean = when (c) {
        0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F, 0x20 -> true
        0x85, 0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000 -> wide
        in 0x2000..0x200A -> wide
        else -> false
    }

    /** `sorted_split(s).join()`: the words, none empty, sorted by code point, one space between. */
    private fun sortedSplit(s: IntArray): IntArray = joined(sortedWords(s))

    /** `sorted_split(s)`'s words: none empty, sorted by code point. */
    private fun sortedWords(s: IntArray): List<IntArray> {
        val wide = s.any { it > 0xFF }
        val words = ArrayList<IntArray>()
        var start = 0
        for (i in 0..s.size) {
            if (i == s.size || isSpace(s[i], wide)) {
                if (i > start) words += s.copyOfRange(start, i)
                start = i + 1
            }
        }
        words.sortWith(CODE_POINTS)
        return words
    }

    /** SplittedSentenceView's `join()`: the words, one space between. */
    private fun joined(words: List<IntArray>): IntArray {
        val out = IntArray(length(words))
        var n = 0
        for ((i, word) in words.withIndex()) {
            if (i > 0) out[n++] = 0x20
            word.copyInto(out, n)
            n += word.size
        }
        return out
    }

    /** SplittedSentenceView's `length()`: its words' code points and a space between each two. */
    private fun length(words: List<IntArray>): Int = if (words.isEmpty()) 0 else words.sumOf { it.size } + words.size - 1

    private val CODE_POINTS = Comparator<IntArray> { x, y ->
        val n = minOf(x.size, y.size)
        var i = 0
        while (i < n && x[i] == y[i]) i++
        if (i < n) x[i].compareTo(y[i]) else x.size.compareTo(y.size)
    }

    // --- token set ------------------------------------------------------------------------------------------

    /** fuzz_impl.hpp's `token_set_ratio` over two `sorted_split`s, score_cutoff 0. */
    private fun tokenSet(a: List<IntArray>, b: List<IntArray>): Double {
        if (a.isEmpty() || b.isEmpty()) return 0.0
        // set_decomposition: each deduplicated (std::unique on the sorted words), then a's words found in b's.
        val wordsA = deduped(a)
        val diffBa = ArrayList(deduped(b))
        val intersection = ArrayList<IntArray>()
        val diffAb = ArrayList<IntArray>()
        for (word in wordsA) {
            val at = diffBa.indexOfFirst { it.contentEquals(word) }
            if (at >= 0) {
                diffBa.removeAt(at)
                intersection += word
            } else {
                diffAb += word
            }
        }
        if (intersection.isNotEmpty() && (diffAb.isEmpty() || diffBa.isEmpty())) return 100.0
        val abJoined = joined(diffAb)
        val baJoined = joined(diffBa)
        val abLen = abJoined.size.toLong()
        val baLen = baJoined.size.toLong()
        val sectLen = length(intersection).toLong()
        val sect = if (sectLen != 0L) 1L else 0L
        val sectAbLen = sectLen + sect + abLen
        val sectBaLen = sectLen + sect + baLen
        val cutoffDistance = kotlin.math.ceil((sectAbLen + sectBaLen).toDouble() * (1.0 - 0.0 / 100)).toLong()
        val dist = (abJoined.size + baJoined.size - 2 * lcs(Pattern(abJoined), baJoined)).toLong()
        var result = 0.0
        if (dist <= cutoffDistance) result = normDistance(dist, sectAbLen + sectBaLen)
        if (sectLen == 0L) return result
        val sectAbRatio = normDistance(sect + abLen, sectLen + sectAbLen)
        val sectBaRatio = normDistance(sect + baLen, sectLen + sectBaLen)
        return maxOf(result, sectAbRatio, sectBaRatio)
    }

    /** fuzz_impl.hpp's `norm_distance` with score_cutoff 0: `100.0 - 100.0 * dist / lensum`, 100 for no length. */
    private fun normDistance(dist: Long, lensum: Long): Double =
        if (lensum > 0) 100.0 - 100.0 * dist.toDouble() / lensum.toDouble() else 100.0

    /** std::unique over sorted words: each run of equal words kept once. */
    private fun deduped(words: List<IntArray>): List<IntArray> {
        val out = ArrayList<IntArray>(words.size)
        for (w in words) if (out.isEmpty() || !out.last().contentEquals(w)) out += w
        return out
    }

    // --- OSA --------------------------------------------------------------------------------------------------

    /** OSA_impl.hpp's `_distance`: the shorter first, the common affix off, then the distance, the cutoff plus one
     * past [cutoff]. */
    private fun osa(x: IntArray, y: IntArray, cutoff: Int): Int {
        val (s1, s2) = if (y.size < x.size) y to x else x to y
        var start = 0
        while (start < s1.size && s1[start] == s2[start]) start++
        var end1 = s1.size
        var end2 = s2.size
        while (end1 > start && end2 > start && s1[end1 - 1] == s2[end2 - 1]) {
            end1--
            end2--
        }
        val n = end1 - start
        val m = end2 - start
        if (n == 0) return if (m <= cutoff) m else cutoff + 1
        // The length difference alone is more than the cutoff: no alignment is within it.
        if (m - n > cutoff) return cutoff + 1
        val d = osaTable(s1, start, n, s2, start, m)
        return if (d <= cutoff) d else cutoff + 1
    }

    /** The optimal string alignment distance of `a[from1, from1 + n)` and `b[from2, from2 + m)`: the Levenshtein
     * table, and a swap of two adjacent characters one edit from the cell two back on both. */
    private fun osaTable(a: IntArray, from1: Int, n: Int, b: IntArray, from2: Int, m: Int): Int {
        var twoBack = IntArray(m + 1)
        var previous = IntArray(m + 1) { it }
        var current = IntArray(m + 1)
        for (i in 1..n) {
            current[0] = i
            val ai = a[from1 + i - 1]
            for (j in 1..m) {
                val bj = b[from2 + j - 1]
                val cost = if (ai == bj) 0 else 1
                var d = minOf(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
                if (i > 1 && j > 1 && ai == b[from2 + j - 2] && a[from1 + i - 2] == bj) {
                    d = minOf(d, twoBack[j - 2] + 1)
                }
                current[j] = d
            }
            val spare = twoBack
            twoBack = previous
            previous = current
            current = spare
        }
        return previous[m]
    }

    // --- partial ratio ----------------------------------------------------------------------------------------

    private class Found(var score: Double, var destStart: Int, var destEnd: Int)

    /** fuzz_impl.hpp's `partial_ratio_alignment`. */
    private fun alignment(s1: IntArray, s2: IntArray): Alignment {
        if (s1.size > s2.size) {
            val r = alignment(s2, s1)
            return Alignment(r.score, r.destStart, r.destEnd, r.srcStart, r.srcEnd)
        }
        if (s1.isEmpty() || s2.isEmpty()) {
            return Alignment(if (s1.size == s2.size) 100.0 else 0.0, 0, s1.size, 0, s1.size)
        }
        val first = partial(s1, s2, 0.0)
        if (first.score != 100.0 && s1.size == s2.size) {
            val second = partial(s2, s1, maxOf(0.0, first.score))
            if (second.score > first.score) {
                return Alignment(second.score, second.destStart, second.destEnd, 0, s1.size)
            }
        }
        return Alignment(first.score, 0, s1.size, first.destStart, first.destEnd)
    }

    /** fuzz_impl.hpp's `partial_ratio_impl` for a needle [s1] no longer than the haystack [s2]. */
    private fun partial(s1: IntArray, s2: IntArray, scoreCutoff: Double): Found {
        val len1 = s1.size
        val len2 = s2.size
        val p = Pattern(s1)
        val res = Found(0.0, 0, len1)
        var cutoff = scoreCutoff
        if (len2 > len1) {
            val maximum = len1 * 2
            val normCutoff = minOf(1.0, 1.0 - cutoff / 100 + 0.00001)
            var cutoffDist = kotlin.math.ceil(maximum.toDouble() * normCutoff).toLong()
            var best = Long.MAX_VALUE
            val scores = LongArray(len2 - len1) { -1L }
            var windows = arrayListOf(0 to len2 - len1 - 1)
            while (windows.isNotEmpty()) {
                val next = ArrayList<Pair<Int, Int>>()
                for ((f, s) in windows) {
                    for (w in 0..1) {
                        val at = if (w == 0) f else s
                        if (scores[at] < 0) {
                            scores[at] = indel(p, s2, at, at + len1).toLong()
                            if (scores[at] < cutoffDist) {
                                best = scores[at]
                                cutoffDist = best
                                res.destStart = at
                                res.destEnd = at + len1
                                if (best == 0L) {
                                    res.score = 100.0
                                    return res
                                }
                            }
                        }
                    }
                    val cell = (s - f).toLong()
                    if (cell == 1L) continue
                    val known = kotlin.math.abs(scores[f] - scores[s])
                    val improve = (cell - known / 2) / 2 * 2
                    if (minOf(scores[f], scores[s]) - improve < cutoffDist) {
                        val c = (s - f) / 2
                        next += f to f + c
                        next += f + c to s
                    }
                }
                windows = next
            }
            if (best != Long.MAX_VALUE) {
                val score = (1.0 - best.toDouble() / maximum.toDouble()) * 100
                if (score >= cutoff) {
                    cutoff = score
                    res.score = score
                }
            }
        }
        for (i in 1 until len1) {
            if (!p.has(s2[i - 1])) continue
            val r = normalizedSimilarity(p, s2, cutoff / 100, 0, i) * 100
            if (r > res.score) {
                cutoff = r
                res.score = r
                res.destStart = 0
                res.destEnd = i
                if (res.score == 100.0) return res
            }
        }
        for (i in len2 - len1 until len2) {
            if (!p.has(s2[i])) continue
            val r = normalizedSimilarity(p, s2, cutoff / 100, i, len2) * 100
            if (r > res.score) {
                cutoff = r
                res.score = r
                res.destStart = i
                res.destEnd = len2
                if (res.score == 100.0) return res
            }
        }
        return res
    }
}
