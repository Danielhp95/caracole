package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * The Python str methods harptab.py leans on beyond core.py's, on code points as Python's: `expandtabs`, `rstrip`,
 * `swapcase`, and harptab's own `_fold_accents` and `_is_word` (vectors/viewer/harptab_read.jsonl's `text_of`
 * records hold Python's answers).
 */
object HarpTabText {
    /** harptab.expand: `line.expandtabs(TAB_STOP).replace(" ", " ")`, its columns counted in code points, a
     * `\n` or `\r` starting a line again. */
    fun expand(line: String): String {
        val stop = HarptabData.TAB_STOP
        val out = StringBuilder(line.length + 8)
        var column = 0
        var i = 0
        while (i < line.length) {
            val cp = line.codePointAt(i)
            i += Character.charCount(cp)
            when (cp) {
                '\t'.code -> if (stop > 0) {
                    val incr = stop - column % stop
                    repeat(incr) { out.append(' ') }
                    column += incr
                }
                else -> {
                    out.appendCodePoint(if (cp == 0xA0) ' '.code else cp)
                    column++
                    if (cp == '\n'.code || cp == '\r'.code) column = 0
                }
            }
        }
        return out.toString()
    }

    /** str.rstrip(): Python's whitespace off the end. */
    fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }

    /**
     * str.swapcase: each upper case letter lower, each lower case one upper, as Python 3.14 swaps them. For a single
     * code point that is: a title case letter (Lt) as it is, else its full lower case where that differs, else its
     * full upper case (checked against Python for every code point); a capital sigma is final or not by the whole
     * text, as Python's lower_ucs4 reads it.
     */
    fun swapcase(s: String): String {
        val cps = Py.codePoints(s)
        val out = StringBuilder(s.length)
        for ((i, cp) in cps.withIndex()) {
            val one = String(Character.toChars(cp))
            when {
                cp == CAPITAL_SIGMA -> out.append(sigma(cps, i))
                PyUnicode.category(cp) == "Lt" -> out.append(one)
                PyUnicode.lower(one) != one -> out.append(PyUnicode.lower(one))
                PyUnicode.upper(one) != one -> out.append(PyUnicode.upper(one))
                else -> out.append(one)
            }
        }
        return out.toString()
    }

    private const val CAPITAL_SIGMA = 0x3A3

    /** The capital sigma at [i] of [cps] lowered in its context: the text lowered whole with every other sigma a
     * Latin letter of the same case (cased, never case-ignorable, as a sigma is), so that the one σ or ς in it is
     * this one's. */
    private fun sigma(cps: IntArray, i: Int): String {
        val context = StringBuilder()
        for ((k, cp) in cps.withIndex()) {
            context.appendCodePoint(when {
                k == i -> cp
                cp == CAPITAL_SIGMA -> 'A'.code
                cp == 0x3C3 || cp == 0x3C2 -> 'a'.code
                else -> cp
            })
        }
        val lowered = PyUnicode.lower(context.toString())
        return if ('ς' in lowered) "ς" else "σ"
    }

    /** harptab._fold_accents: NFKD, its combining marks left out. */
    fun foldAccents(text: String): String {
        val out = StringBuilder(text.length)
        val decomposed = PyUnicode.nfkd(text)
        var i = 0
        while (i < decomposed.length) {
            val cp = decomposed.codePointAt(i)
            i += Character.charCount(cp)
            if (PyUnicode.combining(cp) == 0) out.appendCodePoint(cp)
        }
        return out.toString()
    }

    /** harptab._is_word: whether what a line couldn't read is the tabber's word: letters and no digit, a vowel among
     * them, two at least where it stands [alone]. */
    fun isWord(text: String, alone: Boolean): Boolean {
        if (HarptabData.DIGIT.containsMatchIn(text)) return false
        val folded = PyUnicode.casefold(foldAccents(text))
        var letters = 0
        var vowel = false
        var i = 0
        while (i < folded.length) {
            val cp = folded.codePointAt(i)
            i += Character.charCount(cp)
            if (PyUnicode.isAlpha(cp)) {
                letters++
                if (cp in WORD_VOWELS) vowel = true
            }
        }
        return letters >= (if (alone) 2 else 1) && vowel
    }

    private val WORD_VOWELS: Set<Int> = "aeiouyøæåœ".codePoints().toArray().toHashSet()

    // --- code points, at UTF-16 places -----------------------------------------------------------------------------

    /** The code point at [i] (a UTF-16 place at a code point's start), or -1 past the end. */
    internal fun at(s: String, i: Int): Int = if (i < s.length) s.codePointAt(i) else -1

    /** The code point before [i], or -1 at the start. */
    internal fun before(s: String, i: Int): Int = if (i > 0) s.codePointBefore(i) else -1

    /** The UTF-16 place [n] code points after [i], at most the end. */
    internal fun forward(s: String, i: Int, n: Int): Int {
        var at = i
        repeat(n) { if (at < s.length) at += Character.charCount(s.codePointAt(at)) }
        return at
    }

    /** The UTF-16 place [n] code points before [i], at least the start. */
    internal fun back(s: String, i: Int, n: Int): Int {
        var at = i
        repeat(n) { if (at > 0) at -= Character.charCount(s.codePointBefore(at)) }
        return at
    }

    /** The code points of [s] that aren't Python's whitespace. */
    internal fun solid(s: String): Int {
        var n = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            if (!PyUnicode.isSpace(cp)) n++
        }
        return n
    }
}
