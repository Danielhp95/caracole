package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigDecimal
import java.math.BigInteger

/** An enhanced-LRC word stamp as merge.parse_lrc_words keeps it: the time it marks and the [column] (a code point's
 * index in its line's text) where its word, or syllable, begins. */
data class WordStart(val time: Double, val column: Int)

/** merge.LrcLine: a timed LRC line, [time] and [text] as [Lrc.parse] gives them, and its word stamps in the order
 * written, or null when no word stamp of the line comes before a word. */
data class LrcLine(val time: Double, val text: String, val words: List<WordStart>? = null)

/**
 * merge.py's own reading of LRC (`parse_lrc`, `parse_lrc_words`, `_seconds`, `_stamped_words`), which merge.py and
 * align.py read lyrics with: never lyrics.py's (core's LyricsFiles, the one reader of the lyrics files' stamps), as
 * merge.py reads none of lyrics.py's. Its patterns are merge.py's, autochords.json's, through PyRegex (`\d` any
 * script's decimal digits, `\s` Python's spaces); a stamp's numbers are Python's `int()` and `float()` of them
 * (PyInt, PyFloat), their sum a float as Python makes one; columns and lengths in code points.
 *
 * Where Python raises, so does this: a minute of more than 4300 digits is int()'s ValueError, an
 * [IllegalArgumentException]; a minute, or an `[offset:]`, past a float is its OverflowError, an
 * [ArithmeticException].
 */
object Lrc {
    private val merge by lazy { ViewerData.table("autochords").getValue("merge").jsonObject }
    private fun pattern(name: String): Regex = PyRegex.compile(merge.getValue(name).jsonPrimitive.content)

    internal val STAMP_RUN by lazy { pattern("STAMP_RUN") }
    internal val STAMP by lazy { pattern("STAMP") }
    private val TAG by lazy { pattern("TAG") }
    internal val WORD_TIME by lazy { pattern("WORD_TIME") }
    private val WORD_PIECE by lazy { pattern("WORD_PIECE") }

    /** parse_lrc: the timed lines of an LRC text, sorted by time (stably), each `(seconds, text)`; tags ignored but
     * `[offset:±ms]` (the last one, for every line), a stamp with no text kept as "". */
    fun parse(text: String): List<Pair<Double, String>> = parseWords(text).map { it.time to it.text }

    /** parse_lrc_words: [parse]'s lines, each with its word stamps. */
    fun parseWords(text: String): List<LrcLine> {
        var offset = 0.0
        val timed = ArrayList<Triple<Double, String, List<WordStart>>>()
        for (raw in PyStr.splitlines(lstripBom(text))) {
            val line = Py.strip(raw)
            val stamps = PyRe.match(STAMP_RUN, line)
            if (stamps == null) {
                val tag = PyRe.fullmatch(TAG, line)
                if (tag != null && Py.asciiLower(tag.groupValues[1]) == "offset") {
                    val ms = PyInt.parse(Py.strip(tag.groupValues[2]))  // int()'s ValueError: passed over
                    if (ms != null) offset = trueDivide(ms, 1000)
                }
                continue
            }
            val (lyric, words) = stampedWords(line.substring(stamps.range.last + 1))
            for (m in PyRe.finditer(STAMP, stamps.value)) timed += Triple(seconds(m), lyric, words)
        }
        fun moved(t: Double): Double = Py.round(pyMax(0.0, t - offset), 3)
        return timed.map { (t, lyric, words) ->
            LrcLine(moved(t), lyric, if (words.isNotEmpty()) words.map { WordStart(moved(it.time), it.column) } else null)
        }.sortedWith { a, b -> pyCompare(a.time, b.time) }
    }

    /** text.lstrip("﻿"). */
    internal fun lstripBom(text: String): String = text.trimStart('﻿')

    /** _seconds: the time a stamp's groups (minutes, seconds, an optional fraction) name: `int(m) * 60 + int(s)`, a
     * float, plus `float("0." + fraction)`. */
    internal fun seconds(m: MatchResult): Double {
        val minutes = PyInt.parse(m.groupValues[1]) ?: throw IllegalArgumentException(
            "Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion")
        val seconds = PyInt.parse(m.groupValues[2]) ?: throw IllegalArgumentException("invalid literal for int()")
        val whole = toFloat(minutes.multiply(SIXTY).add(seconds))
        val fraction = m.groups[3]?.value
        return whole + (if (fraction != null) PyFloat.parse("0.$fraction")!! else 0.0)
    }

    /** _stamped_words: a line's text after its line stamps as parse_lrc gives it (word stamps out, its words one space
     * apart) and the time and column of each word a word stamp times. */
    private fun stampedWords(rest: String): Pair<String, List<WordStart>> {
        val text = StringBuilder()
        val words = ArrayList<WordStart>()
        var stamp: Double? = null  // a word stamp, waiting for the word it times
        var space = false
        for (m in PyRe.finditer(WORD_PIECE, rest)) {
            val stamped = m.groups[1]?.value
            val spaces = m.groups[2]?.value
            when {
                !stamped.isNullOrEmpty() -> stamp = seconds(PyRe.fullmatch(WORD_TIME, stamped)!!)
                !spaces.isNullOrEmpty() -> space = text.isNotEmpty()
                else -> {
                    if (space) {
                        text.append(' ')
                        space = false
                    }
                    stamp?.let { words += WordStart(it, Py.len(text.toString())) }
                    stamp = null
                    text.append(m.groups[3]?.value ?: "")
                }
            }
        }
        return text.toString() to words
    }

    private val SIXTY = BigInteger.valueOf(60)
    private val EXACT = BigInteger.ONE.shiftLeft(53)

    /** float(n), an int made a float as Python adds it to one: the nearest double, ties to the even one; past a
     * float's range its OverflowError. */
    internal fun toFloat(n: BigInteger): Double {
        if (n.abs() <= EXACT) return n.toLong().toDouble()
        val x = PyFloat.parse(n.toString())!!
        if (x.isInfinite()) throw ArithmeticException("int too large to convert to float")
        return x
    }

    /** n / d of two ints, Python's true division: the double nearest the exact quotient, ties to the even one; past a
     * float's range its OverflowError. */
    private fun trueDivide(n: BigInteger, d: Int): Double {
        if (n.abs() <= EXACT) return n.toLong().toDouble() / d
        val x = PyFloat.parse(BigDecimal(n).divide(BigDecimal(d)).toPlainString())!!
        if (x.isInfinite()) throw ArithmeticException("integer division result too large for a float")
        return x
    }
}

/** max(a, b) of two floats as Python's builtin takes it: [a] unless [b] is greater. */
internal fun pyMax(a: Double, b: Double): Double = if (b > a) b else a

/** min(a, b) of two floats as Python's builtin takes it: [a] unless [b] is less. */
internal fun pyMin(a: Double, b: Double): Double = if (b < a) b else a
