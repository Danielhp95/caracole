package io.github.danielhp95.caracole.core.py

/** Python's str and number semantics caracole's code leans on, on code points (lane py-unicode). */
object Py {
    /** Python's str ordering: by code point, not by UTF-16 unit. */
    val CODE_POINT_ORDER: Comparator<String> get() = TODO("lane py-unicode")

    /** len(s): code points. */
    fun len(s: String): Int = TODO("lane py-unicode")
    fun codePoints(s: String): IntArray = TODO("lane py-unicode")
    fun string(cps: IntArray, from: Int = 0, to: Int = cps.size): String = TODO("lane py-unicode")

    /** s[from:to], negative indexes included, on code points. */
    fun slice(s: String, from: Int?, to: Int?): String = TODO("lane py-unicode")

    /** str.split() on Python's whitespace. */
    fun split(s: String): List<String> = TODO("lane py-unicode")
    fun strip(s: String): String = TODO("lane py-unicode")

    /** A–Z only: header names, hex, protocol words. */
    fun asciiLower(s: String): String = TODO("lane py-unicode")

    /** round(x, n): half-even on the exact binary value. */
    fun round(x: Double, digits: Int): Double = TODO("lane py-unicode")

    /** The builtin sum() of floats, 3.12+ (Neumaier). */
    fun fsum(xs: Iterable<Double>): Double = TODO("lane py-unicode")
    fun floorMod(a: Int, b: Int): Int = TODO("lane py-unicode")

    /** Counter(items).most_common(1)[0][0]. */
    fun <K> mostCommonFirst(items: Iterable<K>): K? = TODO("lane py-unicode")
}
