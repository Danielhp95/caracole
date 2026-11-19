package io.github.danielhp95.caracole.viewer.sung

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.viewer.pages.internal.PageConstants

/**
 * viewer/sung.py: the song's timed lyrics matched to its sheet's lines, so the page can light the line being sung, its
 * data's `sung` (SheetPage.build), function for function: [lineKey] is `line_key`, [lines] `sung_lines`. Its numbers
 * are page.json's `sung` (PageConstants), sung.py's own.
 *
 * Each timed line `(seconds, text)` from 0 to under [MAX_SECONDS] is the sheet line it is sung on, by its index among
 * the lines the page draws (SheetView.drawnLines), or null: read top to bottom (a monotone match), of all such matches
 * the one that pairs the most lines, each paired as early as it can be; two lines meet when their keys are
 * Fuzz.ratio (rapidfuzz's) [LINE_MATCH] or more alike, a line with no words meeting none. A match of fewer than
 * [MIN_LINES] lines, or of fewer than [MIN_SHARE] of the sheet's lines with words, is none. A time is in milliseconds as
 * Python's round() makes them, half to even. Normalize and Fuzz are core.py's Unicode, never the JDK's.
 */
object Sung {
    /** sung.LINE_MATCH: Fuzz.ratio of two lines' keys for the one to be sung on the other. */
    val LINE_MATCH: Double get() = PageConstants.SUNG_LINE_MATCH

    /** sung.MIN_SHARE: of the sheet's lines with words, the share a match must light. */
    val MIN_SHARE: Double get() = PageConstants.SUNG_MIN_SHARE

    /** sung.MIN_LINES: the lines a match must light at least. */
    val MIN_LINES: Int get() = PageConstants.SUNG_MIN_LINES

    /** sung.MAX_SECONDS: a timed line at a day or more is no song's. */
    val MAX_SECONDS: Double get() = PageConstants.SUNG_MAX_SECONDS

    /** line_key: a line's words as the match compares them: a line that holds Chinese in its pinyin
     * (Normalize.romanize), then as Normalize.nameWords cuts them, one space between; "" for a line with none. */
    fun lineKey(text: String): String = Normalize.nameWords(Normalize.romanize(text)).joinToString(" ")

    /** sung_lines: for each timed line of [timed] from 0 to under [MAX_SECONDS], in the order given, its time in
     * milliseconds and the index in [drawn] of the sheet line it is sung on, or null; null for the whole when fewer
     * than [MIN_LINES], or fewer than [MIN_SHARE] of [drawn]'s lines with words, are matched. */
    fun lines(drawn: List<String>, timed: List<Pair<Double, String>>): List<Pair<Long, Int?>>? {
        val sung = timed.filter { (s, _) -> 0.0 <= s && s < MAX_SECONDS }
            .map { (s, t) -> PyFormat.roundHalfEven(s * 1000) to lineKey(t) }
        if (sung.size < MIN_LINES) return null
        val keys = drawn.map(::lineKey)
        val n = keys.size
        val m = sung.size
        val fits = Array(n) { i ->
            val a = keys[i]
            BooleanArray(m) { j ->
                val b = sung[j].second
                a.isNotEmpty() && b.isNotEmpty() && Fuzz.ratio(a, b) >= LINE_MATCH
            }
        }
        // best[i][j]: the most pairs matchable from sheet line i and timed line j on (0 past either's end)
        val best = Array(n + 1) { IntArray(m + 1) }
        for (i in n - 1 downTo 0) {
            val row = best[i]
            val below = best[i + 1]
            for (j in m - 1 downTo 0) {
                row[j] = maxOf(below[j], row[j + 1], if (fits[i][j]) 1 + below[j + 1] else 0)
            }
        }
        val on = arrayOfNulls<Int>(m)
        var i = 0
        var j = 0
        while (i < n && j < m) {
            if (fits[i][j] && best[i][j] == 1 + best[i + 1][j + 1]) {
                on[j] = i
                i++
                j++
            } else if (best[i][j + 1] >= best[i + 1][j]) {
                j++ // a timed line this sheet line isn't sung on
            } else {
                i++
            }
        }
        val matched = best[0][0]
        if (matched < MIN_LINES || matched < MIN_SHARE * keys.count { it.isNotEmpty() }) return null
        return sung.mapIndexed { k, (ms, _) -> ms to on[k] }
    }
}
