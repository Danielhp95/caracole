package io.github.danielhp95.caracole.core.py

/**
 * The tables tests/test_conformance_unicode.py writes from Python 3.14's own answers, read from the classpath
 * (caracole/unicode/…), and the two shapes they are kept in: a value per code point ([CodePointTable]) and a set of
 * code points ([CodePointSet]). Each file is a `#` line naming its unicodedata version, then hex code points (its
 * generator's docstring has the whole of each format):
 * - flags.txt `start end mask` (bits: alnum alpha decimal digit numeric space word printable latin cased
 *   case-ignorable), category.txt `start end Xx` (Cn left out), combining.txt `start end ccc` (decimal, 0 left
 *   out): runs;
 * - decomposition.txt `cp kind cp…`, one level deep, kind `c` (canonical, composes), `x` (canonical, excluded from
 *   composition) or `k` (compatibility); Hangul's is arithmetic;
 * - case.txt `cp lower upper casefold`, each `+`-joined or `=` for itself;
 * - ignorecase.txt, one IGNORECASE class a line, its representative first.
 */
internal object UnicodeTables {
    /** A table's lines, each split at its spaces, its header checked to be [PyUnicode.UNIDATA_VERSION]'s. */
    fun read(name: String): List<List<String>> {
        val stream = UnicodeTables::class.java.getResourceAsStream("/caracole/unicode/$name")
            ?: throw IllegalStateException("caracole/unicode/$name is not on the classpath (tests/conformance/data)")
        val lines = stream.bufferedReader(Charsets.UTF_8).use { it.readLines() }
        val header = lines.firstOrNull().orEmpty()
        check(header.startsWith("#") && "unicodedata ${PyUnicode.UNIDATA_VERSION}," in header) {
            "caracole/unicode/$name is not unicodedata ${PyUnicode.UNIDATA_VERSION}'s: $header"
        }
        return lines.drop(1).filter { it.isNotEmpty() }.map { it.split(' ') }
    }

    fun hex(s: String): Int = s.toInt(16)

    /** "0069+0307" as its code points. */
    fun sequence(s: String): IntArray = s.split('+').map(::hex).toIntArray()
}

/** A value per code point, 0 where none is given: blocks of 128 code points, each distinct block stored once. */
internal class CodePointTable private constructor(private val index: IntArray, private val values: IntArray) {
    operator fun get(cp: Int): Int =
        if (cp < 0 || cp > MAX_CODE_POINT) 0 else values[(index[cp ushr SHIFT] shl SHIFT) or (cp and MASK)]

    companion object {
        const val MAX_CODE_POINT = 0x10FFFF
        private const val SHIFT = 7
        private const val SIZE = 1 shl SHIFT
        private const val MASK = SIZE - 1
        private const val BLOCKS = (MAX_CODE_POINT + 1) ushr SHIFT

        /** From runs [start, end, value, start, end, value, …], ascending and disjoint. */
        fun ofRuns(runs: IntArray): CodePointTable {
            require(runs.size % 3 == 0)
            val index = IntArray(BLOCKS)
            val distinct = ArrayList<IntArray>()
            val byHash = HashMap<Int, MutableList<Int>>()
            var block = IntArray(SIZE)
            var r = 0
            val n = runs.size / 3
            for (b in 0 until BLOCKS) {
                val lo = b shl SHIFT
                val hi = lo + MASK
                while (r < n && runs[3 * r + 1] < lo) r++
                var k = r
                while (k < n && runs[3 * k] <= hi) {
                    for (cp in maxOf(lo, runs[3 * k])..minOf(hi, runs[3 * k + 1])) block[cp - lo] = runs[3 * k + 2]
                    k++
                }
                val hash = block.contentHashCode()
                val same = byHash[hash]?.firstOrNull { distinct[it].contentEquals(block) }
                if (same != null) {
                    index[b] = same
                    block.fill(0)
                } else {
                    index[b] = distinct.size
                    byHash.getOrPut(hash) { mutableListOf() } += distinct.size
                    distinct += block
                    block = IntArray(SIZE)
                }
            }
            val values = IntArray(distinct.size * SIZE)
            distinct.forEachIndexed { i, values1 -> values1.copyInto(values, i * SIZE) }
            return CodePointTable(index, values)
        }

        /** From single code points and their values. */
        fun ofPoints(points: Map<Int, Int>): CodePointTable {
            val sorted = points.keys.sorted()
            val runs = IntArray(sorted.size * 3)
            sorted.forEachIndexed { i, cp -> runs[3 * i] = cp; runs[3 * i + 1] = cp; runs[3 * i + 2] = points.getValue(cp) }
            return ofRuns(runs)
        }
    }
}

/** A set of code points, as ascending disjoint ranges [start, end, start, end, …]. */
internal class CodePointSet private constructor(private val ranges: IntArray) {
    val isEmpty: Boolean get() = ranges.isEmpty()

    operator fun contains(cp: Int): Boolean {
        var lo = 0
        var hi = ranges.size / 2 - 1
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            when {
                cp < ranges[2 * mid] -> hi = mid - 1
                cp > ranges[2 * mid + 1] -> lo = mid + 1
                else -> return true
            }
        }
        return false
    }

    fun union(other: CodePointSet): CodePointSet = of(ranges + other.ranges)

    fun complement(): CodePointSet {
        val out = ArrayList<Int>()
        var next = 0
        for (i in 0 until ranges.size / 2) {
            if (ranges[2 * i] > next) { out += next; out += ranges[2 * i] - 1 }
            next = ranges[2 * i + 1] + 1
        }
        if (next <= CodePointTable.MAX_CODE_POINT) { out += next; out += CodePointTable.MAX_CODE_POINT }
        return CodePointSet(out.toIntArray())
    }

    /** With every member of each IGNORECASE class one of its members is in: what sre's IGNORECASE matches. */
    fun closedUnderIgnoreCase(): CodePointSet {
        val added = ArrayList<Int>()
        for (members in PyUnicode.ignoreCaseClasses()) {
            if (members.any { it in this }) for (m in members) { added += m; added += m }
        }
        return if (added.isEmpty()) this else of(ranges + added.toIntArray())
    }

    /** The ranges as a java.util.regex class body: `\x{…}` escapes in the BMP, the code points beyond it as they
     * are, so that java.util.regex reads the pattern by code point (its lookbehind steps by UTF-16 unit otherwise). */
    fun body(): String {
        val out = StringBuilder()
        for (i in 0 until ranges.size / 2) {
            val (a, b) = ranges[2 * i] to ranges[2 * i + 1]
            point(out, a)
            if (b > a) {
                if (b > a + 1) out.append('-')
                point(out, b)
            }
        }
        return out.toString()
    }

    /** A class matching exactly this set; one that matches nothing when it is empty. */
    fun asClass(): String = if (isEmpty) "(?!)" else "[" + body() + "]"

    companion object {
        /** From ranges in any order, overlapping or not. */
        fun of(ranges: IntArray): CodePointSet {
            require(ranges.size % 2 == 0)
            val order = (0 until ranges.size / 2).sortedBy { ranges[2 * it] }
            val out = ArrayList<Int>()
            for (i in order) {
                val (a, b) = ranges[2 * i] to ranges[2 * i + 1]
                if (out.isNotEmpty() && a <= out[out.size - 1] + 1) {
                    if (b > out[out.size - 1]) out[out.size - 1] = b
                } else {
                    out += a
                    out += b
                }
            }
            return CodePointSet(out.toIntArray())
        }

        fun points(vararg cps: Int): CodePointSet = of(IntArray(cps.size * 2) { cps[it / 2] })

        private fun point(out: StringBuilder, cp: Int) {
            if (cp > 0xFFFF) out.appendCodePoint(cp) else out.append("\\x{").append(cp.toString(16)).append('}')
        }
    }
}
