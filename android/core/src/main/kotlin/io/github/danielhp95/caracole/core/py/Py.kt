package io.github.danielhp95.caracole.core.py

import java.math.BigDecimal
import java.math.RoundingMode

/** Python's str and number semantics caracole's code leans on, on code points. */
object Py {
    /** Python's str ordering: by code point, not by UTF-16 unit (U+E000 sorts before U+10000). */
    val CODE_POINT_ORDER: Comparator<String> get() = CodePointOrder

    private object CodePointOrder : Comparator<String> {
        override fun compare(a: String, b: String): Int {
            var i = 0
            var j = 0
            while (i < a.length && j < b.length) {
                val x = a.codePointAt(i)
                val y = b.codePointAt(j)
                if (x != y) return x.compareTo(y)
                i += Character.charCount(x)
                j += Character.charCount(y)
            }
            return (a.length - i).compareTo(b.length - j)
        }
    }

    /** len(s): code points. */
    fun len(s: String): Int = s.codePointCount(0, s.length)

    fun codePoints(s: String): IntArray {
        val out = IntArray(len(s))
        var i = 0
        var k = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            out[k++] = cp
            i += Character.charCount(cp)
        }
        return out
    }

    fun string(cps: IntArray, from: Int = 0, to: Int = cps.size): String {
        val out = StringBuilder(to - from)
        for (k in from until to) out.appendCodePoint(cps[k])
        return out.toString()
    }

    /** s[from:to], negative indexes included, on code points. */
    fun slice(s: String, from: Int?, to: Int?): String {
        val n = len(s)
        fun bound(x: Int?, default: Int): Int = when {
            x == null -> default
            x < 0 -> maxOf(0, x + n)
            else -> minOf(x, n)
        }
        val start = bound(from, 0)
        val stop = bound(to, n)
        if (stop <= start) return ""
        return s.substring(s.offsetByCodePoints(0, start), s.offsetByCodePoints(0, stop))
    }

    /** str.split() on Python's whitespace. */
    fun split(s: String): List<String> {
        val out = ArrayList<String>()
        var i = 0
        while (i < s.length) {
            while (i < s.length && PyUnicode.isSpace(s.codePointAt(i))) i += Character.charCount(s.codePointAt(i))
            if (i >= s.length) break
            val start = i
            while (i < s.length && !PyUnicode.isSpace(s.codePointAt(i))) i += Character.charCount(s.codePointAt(i))
            out += s.substring(start, i)
        }
        return out
    }

    fun strip(s: String): String {
        var start = 0
        while (start < s.length && PyUnicode.isSpace(s.codePointAt(start))) start += Character.charCount(s.codePointAt(start))
        var end = s.length
        while (end > start && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(start, end)
    }

    /** A–Z only: header names, hex, protocol words. */
    fun asciiLower(s: String): String {
        var i = 0
        while (i < s.length && s[i] !in 'A'..'Z') i++
        if (i == s.length) return s
        val out = s.toCharArray()
        while (i < out.size) {
            if (out[i] in 'A'..'Z') out[i] = out[i] + ('a' - 'A')
            i++
        }
        return String(out)
    }

    /** round(x, n): half-even on the exact binary value, then the nearest double (Python's float.__round__). */
    fun round(x: Double, digits: Int): Double {
        if (x.isNaN() || x.isInfinite() || x == 0.0) return x
        val rounded = BigDecimal(x).abs().setScale(digits, RoundingMode.HALF_EVEN)
        return nearestDouble(rounded).withSign(x)
    }

    private val EXACT_POWERS = DoubleArray(23) { var p = 1.0; repeat(it) { p *= 10.0 }; p }

    /** The double nearest a decimal: one IEEE division where both are exact, else the shortest decimal parsed. */
    private fun nearestDouble(d: BigDecimal): Double {
        val unscaled = d.unscaledValue()
        val scale = d.scale()
        if (unscaled.bitLength() <= 52 && scale in -22..22) {
            val u = unscaled.toLong().toDouble()
            return if (scale >= 0) u / EXACT_POWERS[scale] else u * EXACT_POWERS[-scale]
        }
        return d.toString().toDouble()
    }

    private fun Double.withSign(of: Double): Double = Math.copySign(this, of)

    /** The builtin sum() of floats, 3.12+ (Neumaier): 0 + the first, then each compensated, the compensation added
     * last when it is finite and not zero. */
    fun fsum(xs: Iterable<Double>): Double {
        val it = xs.iterator()
        if (!it.hasNext()) return 0.0
        var sum = 0.0 + it.next()
        var c = 0.0
        while (it.hasNext()) {
            val x = it.next()
            val t = sum + x
            c += if (Math.abs(sum) >= Math.abs(x)) (sum - t) + x else (x - t) + sum
            sum = t
        }
        if (c != 0.0 && c.isFinite()) sum += c
        return sum
    }

    fun floorMod(a: Int, b: Int): Int = Math.floorMod(a, b)

    /** Counter(items).most_common(1)[0][0]: the commonest, the first seen of those tied; null for none. */
    fun <K> mostCommonFirst(items: Iterable<K>): K? {
        val counts = LinkedHashMap<K, Int>()
        for (item in items) counts[item] = (counts[item] ?: 0) + 1
        var best: K? = null
        var most = 0
        for ((item, n) in counts) if (n > most) { best = item; most = n }
        return best
    }
}
