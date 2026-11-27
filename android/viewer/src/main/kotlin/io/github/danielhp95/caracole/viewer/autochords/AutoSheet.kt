package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** merge.ChordSegment: a chord sounding from [start] to [end] seconds; the label "N" ([AutoSheet.NO_CHORD]) means no
 * chord. Its one home: `:autochords`' Labels and the hearing name it by a typealias. */
data class ChordSegment(val start: Double, val end: Double, val label: String)

/**
 * autochords/merge.py on the phone, function for function: the chords heard snapped to the beats ([snapToBeats]) and
 * laid out over a song's lyrics as the text of `sheet (auto).txt` ([build]), byte for byte; the credit of a sheet
 * from a YouTube video ([youtubeCredit]); plain lyrics put on a sheet of none ([withPlainLyrics]). Its constants and
 * patterns are merge.py's (autochords.json). LRC is read by [Lrc], merge.py's own reader.
 *
 * As Python: every float is a double rounded as `round(x, 3)` rounds (Py.round), `round(x)` half to even, `int()` a
 * truncation, a median `statistics.median`'s (the middle, or the mean of the two middles), `max`, `min` and `sorted`
 * taking the first of those tied (sorts stable); a text's lengths, indexes and slices in code points; a chord line's
 * columns display columns (ChordPro.displayColumns, chordpro.display_columns: a wide character two, a combining mark
 * none); a word's letters by Python's Unicode categories (PyUnicode.category), never the JDK's.
 */
object AutoSheet {
    private val merge by lazy { ViewerData.table("autochords").getValue("merge").jsonObject }

    val NO_CHORD: String by lazy { merge.getValue("NO_CHORD").jsonPrimitive.content }
    val AUTO_MARKER: String by lazy { merge.getValue("AUTO_MARKER").jsonPrimitive.content }
    private val DEFAULT_BEAT by lazy { merge.getValue("DEFAULT_BEAT").jsonPrimitive.double }
    internal val BEATS_PER_BAR by lazy { merge.getValue("BEATS_PER_BAR").jsonPrimitive.int }
    private val BARS_PER_LINE by lazy { merge.getValue("BARS_PER_LINE").jsonPrimitive.int }
    private val GAP_BARS by lazy { merge.getValue("GAP_BARS").jsonPrimitive.int }
    private val EPS by lazy { merge.getValue("EPS").jsonPrimitive.double }
    private val UNSPACED by lazy { PyRegex.compile(merge.getValue("UNSPACED").jsonPrimitive.content) }
    private val APOSTROPHES by lazy { Py.codePoints(merge.getValue("APOSTROPHES").jsonPrimitive.content).toSet() }

    /** snap_to_beats: every chord change moved to the nearest beat of the grid ([beatGrid]); a chord shorter than a
     * beat and "N" dropped; a chord that touches the next of the same name merged with it. Without beats the segments
     * are only cleaned. */
    fun snapToBeats(segments: List<ChordSegment>, beats: List<Double>): List<ChordSegment> {
        val segs = segments.sortedWith { a, b -> pyCompare(a.start, b.start).takeIf { it != 0 } ?: pyCompare(a.end, b.end) }
        if (segs.isEmpty()) return emptyList()
        val grid = beatGrid(beats, segs.map { it.end }.reduce(::pyMax))
        if (grid.size < 2) return merged(segs.filter { it.label != NO_CHORD && it.end > it.start })
        val snapped = ArrayList<ChordSegment>()
        for (s in segs) {
            val a = nearest(grid, s.start)
            val b = nearest(grid, s.end)
            if (b > a && s.label != NO_CHORD) snapped += ChordSegment(grid[a], grid[b], s.label)
        }
        return merged(snapped)
    }

    /** youtube_credit: the line after the song's name of a sheet made from a YouTube video's audio: the video by its
     * title, else its id, and its channel, each with its spaces made one ("Audio from YouTube: Creep (Radiohead -
     * Topic)"). */
    fun youtubeCredit(title: String, channel: String, videoId: String): String {
        val named = Py.split(title.ifEmpty { videoId }).joinToString(" ")
        val by = Py.split(channel).joinToString(" ")
        return if (by.isNotEmpty()) "Audio from YouTube: $named ($by)" else "Audio from YouTube: $named"
    }

    /**
     * build_sheet: the text of `sheet (auto).txt`. With timed lyrics ([synced], LRC; read for its word stamps where
     * [syncedWords] is given, which is then what is laid out), each sung line gets the chords that start in it, over
     * the word sung then; where the voice rests two bars or more, chord-only lines of bars. With [plain] lyrics only,
     * a chart of the whole song, then them; with none, the chart alone. [source], when it holds more than spaces, is a
     * line (or lines) after the song's name.
     */
    fun build(
        segments: List<ChordSegment>, title: String, artist: String, synced: String? = null,
        syncedWords: List<LrcLine>? = null, plain: String? = null, beats: List<Double>? = null,
        downbeats: List<Double>? = null, source: String? = null,
    ): String {
        val segs = snapToBeats(segments, beats.orEmpty())
        val lines: List<Pair<Double, String>>
        val words: List<List<WordStart>?>?
        if (!syncedWords.isNullOrEmpty()) {
            lines = syncedWords.map { it.time to it.text }
            words = syncedWords.map { it.words }
        } else {
            lines = if (!synced.isNullOrEmpty()) Lrc.parse(synced) else emptyList()
            words = null
        }
        val until = (segs.map { it.end } + lines.map { it.first } + listOf(0.0)).reduce(::pyMax)
        val grid = beatGrid(beats.orEmpty(), until)
        val beat = truthy(period(grid)) ?: DEFAULT_BEAT
        val bars = barStarts(grid, segs.map { it.start }, downbeats.orEmpty())
        val bar = truthy(period(bars)) ?: (BEATS_PER_BAR * beat)
        val out = arrayListOf(AUTO_MARKER, "$artist - $title")
        val credit = source?.let { Py.strip(it) }
        if (!credit.isNullOrEmpty()) out += credit
        out += ""
        if (lines.any { it.second.isNotEmpty() }) {
            out += syncedBody(segs, lines, beat / 2, bars, bar, words)
        } else {
            val whole = if (segs.isNotEmpty()) chart(segs, bars, barAt(bars, segs[0].start), segs.last().end) else emptyList()
            if (whole.isNotEmpty()) {
                out += "[Chords]"
                out += whole
                out += ""
            }
            out += lyricsBlock(plain)
        }
        return out.joinToString("\n").trimEnd('\n') + "\n"
    }

    /** with_plain_lyrics: a sheet [build] made with no lyrics, as it would have made it with [plain]: its chart, then
     * them. */
    fun withPlainLyrics(sheet: String, plain: String): String =
        (listOf(sheet.trimEnd('\n'), "") + lyricsBlock(plain)).joinToString("\n").trimEnd('\n') + "\n"

    /** _lyrics_block: plain lyrics as a sheet's last section, or no line for none. */
    private fun lyricsBlock(plain: String?): List<String> {
        val lyrics = PyStr.splitlines((plain ?: "").trim('\n')).map(::rstrip)
        return if (lyrics.any { it.isNotEmpty() }) listOf("[Lyrics]") + lyrics else emptyList()
    }

    /** `x or y` of a float: null for none or zero. */
    private fun truthy(x: Double?): Double? = x?.takeIf { it != 0.0 }

    /** _period: the median spacing of a sorted grid, or null when it has fewer than two points. */
    internal fun period(grid: List<Double>): Double? {
        if (grid.size < 2) return null
        return median((1 until grid.size).map { grid[it] - grid[it - 1] })
    }

    /** statistics.median of floats. */
    internal fun median(xs: List<Double>): Double {
        val data = xs.sortedWith(::pyCompare)
        val n = data.size
        require(n > 0) { "no median for empty data" }
        return if (n % 2 == 1) data[n / 2] else (data[n / 2 - 1] + data[n / 2]) / 2
    }

    private class Sung(val t: Double, val text: String, val after: Double?, val rest: Boolean)

    private fun syncedBody(
        segs: List<ChordSegment>, lines: List<Pair<Double, String>>, tol: Double, bars: List<Double>, bar: Double,
        words: List<List<WordStart>?>?,
    ): List<String> {
        // Each sung line, with the time of the LRC entry after it and whether that entry is empty (a break).
        val sung = ArrayList<Sung>()
        val sungWords = ArrayList<List<WordStart>?>()
        for ((j, line) in lines.withIndex()) {
            val (t, text) = line
            if (text.isEmpty()) continue
            val after = lines.getOrNull(j + 1)
            sung += Sung(t, text, after?.first, after != null && after.second.isEmpty())
            sungWords += words?.get(j)
        }
        val windows = sung.mapNotNull { s -> s.after?.let { it - s.t } }
        val typical = if (windows.isNotEmpty()) median(windows) else GAP_BARS * bar
        val musicEnd = if (segs.isNotEmpty()) segs.last().end else sung.last().t
        val out = ArrayList<String>()
        val first = sung[0].t - tol
        if (segs.isNotEmpty() && first - segs[0].start >= bar - EPS) {
            val intro = chart(segs, bars, barAt(bars, segs[0].start), first)
            if (intro.isNotEmpty()) {
                out += "[Intro]"
                out += intro
                out += ""
            }
        }
        var blockStart = true
        for ((i, s) in sung.withIndex()) {
            val t = s.t
            val text = s.text
            val nxt = sung.getOrNull(i + 1)?.t
            val sungEnd = if (s.after == null) t + typical else pyMin(s.after, t + typical)
            val gapEnd = nxt ?: pyMax(musicEnd, sungEnd)
            val gapStart = barOnOrAfter(bars, sungEnd)
            var gap: List<String> = emptyList()
            if (gapEnd - gapStart >= GAP_BARS * bar - EPS) gap = chart(segs, bars, gapStart, gapEnd - tol)
            val end = if (gap.isNotEmpty()) gapStart else gapEnd
            val span = pyMax(end - t, EPS)
            val length = Py.len(text)
            val timed = trustedWords(sungWords[i], text, t, s.after, tol)
            val placed = ArrayList<Pair<Int, String>>()
            for (seg in segs) {
                if (!(t - tol <= seg.start && seg.start < end - tol)) continue
                val col = if (timed != null) wordColumn(timed, seg.start, tol)
                          else maxOf(0, truncate((seg.start - t) / span * length))
                placed += col to seg.label
            }
            if (blockStart && !(placed.isNotEmpty() && placed[0].first == 0)) {
                // The first line of a block names the chord already ringing when it starts.
                val ringing = segs.filter { it.start < t - tol && t - tol < it.end }.map { it.label }
                if (ringing.isNotEmpty()) placed.add(0, 0 to ringing.last())
            }
            if (placed.isNotEmpty()) out += chordLine(onWords(text, placed))
            out += text
            blockStart = gap.isNotEmpty() || (s.rest && nxt != null)
            if (gap.isNotEmpty()) {
                out += ""
                out += if (nxt == null) "[Outro]" else "[Instrumental]"
                out += gap
                out += ""
            } else if (blockStart) {
                out += ""
            }
        }
        return out
    }

    /** int(x) of a float: toward zero. */
    private fun truncate(x: Double): Int = x.toInt()

    /** _trusted_words: a sung line's word stamps when they can place its chords (in the order sung, the first no
     * earlier than the line's time, the last no later than the next entry's, within [tol]), each moved to its word's
     * start; else null. */
    private fun trustedWords(
        words: List<WordStart>?, text: String, t: Double, until: Double?, tol: Double,
    ): List<WordStart>? {
        if (words.isNullOrEmpty()) return null
        val times = words.map { it.time }
        if ((1 until times.size).any { times[it] < times[it - 1] }) return null
        if (times[0] < t - tol - EPS || (until != null && times.last() > until + tol + EPS)) return null
        val cps = Py.codePoints(text)
        val starts = wordStarts(cps)
        val own = words.map { WordStart(it.time, ownWord(cps, starts, it.column)) }
        return if (words[0].column == 0) own else listOf(WordStart(pyMin(t, times[0]), 0)) + own
    }

    /** _own_word: the start of the word [col] is in, of [starts]: the last one at or before it with no space between;
     * [col] itself when there is none. */
    private fun ownWord(cps: IntArray, starts: List<Int>, col: Int): Int {
        val i = bisectRight(starts, col) - 1
        if (i < 0) return col
        val from = starts[i]
        for (k in from until minOf(col, cps.size)) if (cps[k] == ' '.code) return col
        return from
    }

    /** _word_column: the column of the word sung when a chord starts at [start]: the word starting nearest it within
     * [tol], else the last word started before it; 0 before the first. */
    private fun wordColumn(words: List<WordStart>, start: Double, tol: Double): Int {
        var best: WordStart? = null
        var bestFar = 0.0
        for (w in words) {
            val far = Math.abs(w.time - start)
            if (far > tol + EPS) continue
            // min() of (distance, column) tuples: the nearest, then the smallest column.
            if (best == null || far < bestFar || (far == bestFar && w.column < best.column)) {
                best = w
                bestFar = far
            }
        }
        if (best != null) return best.column
        return words.lastOrNull { it.time <= start }?.column ?: 0
    }

    /** _bar_starts: bar start times on the beat grid: on the downbeats, kept at their beats a bar before the first,
     * after the last and across a missed one (one less than half a bar after the one before ignored); without two
     * downbeats, 4 beats a bar phased so that most chord changes start one; a pickup bar from the grid's start. */
    internal fun barStarts(grid: List<Double>, changes: List<Double>, downbeats: List<Double>): List<Double> {
        if (grid.size < 2) return grid.toList()
        val found = downbeats.map { nearest(grid, it) }.toSortedSet().toList()
        val starts = ArrayList<Int>()
        if (found.size >= 2) {
            val perBar = maxOf(1, PyFormat.roundHalfEven(
                median((1 until found.size).map { (found[it] - found[it - 1]).toDouble() })).toInt())
            val marks = arrayListOf(found[0])
            for (m in found.drop(1)) if (m - marks.last() >= perBar / 2.0) marks += m
            var k = marks[0] - perBar
            val before = ArrayList<Int>()
            while (k > -1) {
                before += k
                k -= perBar
            }
            starts += before.asReversed()
            for (j in 1 until marks.size) {
                val a = marks[j - 1]
                val b = marks[j]
                val missing = PyFormat.roundHalfEven((b - a).toDouble() / perBar).toInt() - 1
                for (q in 0 until missing + 1) {
                    starts += a + PyFormat.roundHalfEven((q * (b - a)).toDouble() / (missing + 1)).toInt()
                }
            }
            starts += (marks.last() until grid.size step perBar)
        } else {
            val onBeat = changes.map { nearest(grid, it) }
            var phase = 0
            var most = -1
            for (p in 0 until BEATS_PER_BAR) {  // max() by (count, -p): the most, the smallest p of those tied
                val n = onBeat.count { Math.floorMod(it, BEATS_PER_BAR) == p }
                if (n > most) {
                    most = n
                    phase = p
                }
            }
            starts += (phase until grid.size step BEATS_PER_BAR)
        }
        if (starts[0] > 0) starts.add(0, 0)  // a pickup bar
        return starts.map { grid[it] }
    }

    private fun barOnOrAfter(bars: List<Double>, t: Double): Double {
        val i = bisectLeft(bars, t - EPS)
        return if (i < bars.size) bars[i] else t
    }

    /** _bar_at: the start of the bar that contains [t]. */
    private fun barAt(bars: List<Double>, t: Double): Double {
        val i = bisectRight(bars, t + EPS) - 1
        return if (i >= 0) bars[i] else t
    }

    /** _chart: chord-only lines for the bars that start in [lo, hi), four bars a line; a bar shows the chord sounding
     * when it starts, then each that starts within it, "N.C." where nothing sounds; a line repeated right away
     * written once, with a count (`| G | D | Em | C | x3`). */
    private fun chart(segs: List<ChordSegment>, bars: List<Double>, lo: Double, hi: Double): List<String> {
        val cells = ArrayList<String>()
        for ((k, start) in bars.withIndex()) {
            if (start < lo - EPS || start >= hi - EPS) continue
            val end = if (k + 1 < bars.size) pyMin(bars[k + 1], hi) else hi
            val names = segs.filter { it.start <= start + EPS && start + EPS < it.end }.mapTo(ArrayList()) { it.label }
            for (s in segs) {
                if (start + EPS < s.start && s.start < end - EPS && (names.isEmpty() || names.last() != s.label)) {
                    names += s.label
                }
            }
            cells += if (names.isNotEmpty()) names.joinToString(" ") { "[ch]$it[/ch]" } else NO_CHORD_CELL
        }
        while (cells.isNotEmpty() && cells.last() == NO_CHORD_CELL) cells.removeAt(cells.size - 1)
        val rows = cells.chunked(BARS_PER_LINE).map { "| " + it.joinToString(" | ") + " |" }
        val out = ArrayList<String>()
        var i = 0
        while (i < rows.size) {
            var n = 1
            while (i + n < rows.size && rows[i + n] == rows[i]) n++
            out += if (n == 1) rows[i] else "${rows[i]} x$n"
            i += n
        }
        return out
    }

    private const val NO_CHORD_CELL = "[ch]N.C.[/ch]"

    /** _chord_line: a chord line in UG markup, each chord at its display column, at least one space apart. */
    fun chordLine(placed: List<Pair<Int, String>>): String {
        var visible = 0
        val out = StringBuilder()
        for ((at, name) in placed) {
            val col = maxOf(at, if (visible != 0) visible + 1 else 0)
            repeat(maxOf(0, col - visible)) { out.append(' ') }
            out.append("[ch]").append(name).append("[/ch]")
            visible = col + Py.len(name)
        }
        return out.toString()
    }

    /** _on_words: the chords of a lyric line, each moved to the start of the word nearest its column (a code point's
     * index in [text]), at that word's display column; in order, one a word: a chord whose word is the one before's,
     * or under its name, takes the first word start clear of that name and a space, else the column right after it. */
    fun onWords(text: String, placed: List<Pair<Int, String>>): List<Pair<Int, String>> {
        val cps = Py.codePoints(text)
        val columns = ChordPro.displayColumns(text)
        fun shown(i: Int): Int = when {
            i < 0 -> columns[columns.size + i]  // Python's index from the end
            i < cps.size -> columns[i]
            else -> columns[cps.size] + i - cps.size
        }
        val starts = wordStarts(cps).map(::shown)
        val out = ArrayList<Pair<Int, String>>()
        var free = 0  // the first column clear of the previous chord's name and a space
        for ((col, name) in placed) {
            var at = shown(wordStart(cps, col))
            if (at < free) {
                val later = bisectLeft(starts, free)
                at = if (later < starts.size) starts[later] else free
            }
            out += at to name
            free = at + Py.len(name) + 1
        }
        return out
    }

    /** _word_start: the code point index of the word start in [text] nearest [col], a tie to the earlier word; [col]
     * itself at or past the line's end, or in a line with no word. */
    fun wordStart(text: String, col: Int): Int = wordStart(Py.codePoints(text), col)

    private fun wordStart(cps: IntArray, col: Int): Int {
        val starts = wordStarts(cps)
        if (starts.isEmpty() || col >= cps.size) return col
        return starts[nearest(starts, col)]
    }

    /** _word_starts: where the words of a line start: a letter or digit after no letter, mark or digit of a spaced
     * script (an apostrophe between two letters joins them), and each Chinese character and kana. */
    private fun wordStarts(cps: IntArray): List<Int> {
        val starts = ArrayList<Int>()
        for ((i, c) in cps.withIndex()) {
            val kind = PyUnicode.category(c)
            if (unspaced(c)) {
                if (kind == "Lo") starts += i
                continue
            }
            if (kind[0] != 'L' && kind[0] != 'N') continue
            var before = if (i > 0) cps[i - 1] else NONE
            if (i > 1 && before in APOSTROPHES) before = cps[i - 2]  // an apostrophe between two letters joins them
            if (!inWord(before)) starts += i
        }
        return starts
    }

    private const val NONE = -1

    /** _in_word: whether a letter after [c] goes on its word: a letter, a mark or a digit of a spaced script. */
    private fun inWord(c: Int): Boolean = c != NONE && PyUnicode.category(c)[0] in "LMN" && !unspaced(c)

    /** _UNSPACED.match of one character. */
    private fun unspaced(c: Int): Boolean = PyRe.match(UNSPACED, String(Character.toChars(c))) != null

    private fun merged(segs: List<ChordSegment>): List<ChordSegment> {
        val out = ArrayList<ChordSegment>()
        for (s in segs) {
            val last = out.lastOrNull()
            if (last != null && last.label == s.label && s.start <= last.end + EPS) {
                out[out.size - 1] = last.copy(end = pyMax(last.end, s.end))
            } else {
                out += s
            }
        }
        return out
    }

    /** _beat_grid: the beats (those from 0, each `round(b, 3)`, each once), sorted, with missing beats filled in and
     * the grid extended to 0 and [until] at their median spacing. */
    fun beatGrid(beats: List<Double>, until: Double): List<Double> {
        val found = pySortedSet(beats.filter { it >= 0.0 }.map { Py.round(it, 3) })
        if (found.size < 2) return found
        val period = median((1 until found.size).map { found[it] - found[it - 1] })
        val grid = arrayListOf(found[0])
        for (b in found.drop(1)) {
            val base = grid.last()
            if (b - base < period / 2) continue  // the same beat detected twice
            val missing = maxOf(0L, PyFormat.roundHalfEven((b - base) / period) - 1).toInt()
            val step = (b - base) / (missing + 1)
            for (k in 1..missing) grid += Py.round(base + step * k, 3)
            grid += b
        }
        val head = ArrayList<Double>()
        var t = grid[0] - period
        while (t > -period / 2) {
            head += Py.round(pyMax(t, 0.0), 3)
            t -= period
        }
        val tail = ArrayList<Double>()
        t = grid.last() + period
        while (t < until + period / 2) {
            tail += Py.round(t, 3)
            t += period
        }
        return head.asReversed() + grid + tail
    }

    /** _nearest: the index of the grid time nearest [t]; a tie to the earlier one. */
    internal fun nearest(grid: List<Double>, t: Double): Int {
        val i = bisectLeft(grid, t)
        if (i == 0) return 0
        if (i == grid.size) return grid.size - 1
        return if (grid[i] - t < t - grid[i - 1]) i else i - 1
    }

    private fun nearest(grid: List<Int>, t: Int): Int {
        val i = bisectLeft(grid, t)
        if (i == 0) return 0
        if (i == grid.size) return grid.size - 1
        return if (grid[i] - t < t - grid[i - 1]) i else i - 1
    }

    /** str.rstrip(): Python's whitespace off the end. */
    private fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }
}

/** bisect.bisect_left of floats, compared as Python compares them (0.0 and -0.0 alike). */
internal fun bisectLeft(xs: List<Double>, x: Double): Int {
    var lo = 0
    var hi = xs.size
    while (lo < hi) {
        val mid = (lo + hi) ushr 1
        if (xs[mid] < x) lo = mid + 1 else hi = mid
    }
    return lo
}

/** bisect.bisect_right of floats. */
internal fun bisectRight(xs: List<Double>, x: Double): Int {
    var lo = 0
    var hi = xs.size
    while (lo < hi) {
        val mid = (lo + hi) ushr 1
        if (x < xs[mid]) hi = mid else lo = mid + 1
    }
    return lo
}

/** bisect.bisect_left of ints. */
internal fun bisectLeft(xs: List<Int>, x: Int): Int {
    var lo = 0
    var hi = xs.size
    while (lo < hi) {
        val mid = (lo + hi) ushr 1
        if (xs[mid] < x) lo = mid + 1 else hi = mid
    }
    return lo
}

/** bisect.bisect_right of ints. */
internal fun bisectRight(xs: List<Int>, x: Int): Int {
    var lo = 0
    var hi = xs.size
    while (lo < hi) {
        val mid = (lo + hi) ushr 1
        if (x < xs[mid]) hi = mid else lo = mid + 1
    }
    return lo
}

/** Two floats as Python's sort compares them: by `<` alone, so 0.0 and -0.0 are tied, and a stable sort keeps their
 * order (Double.compareTo would put -0.0 first). */
internal fun pyCompare(a: Double, b: Double): Int = if (a < b) -1 else if (b < a) 1 else 0

/** sorted(set(xs)) of floats: each value once (0.0 and -0.0 one, the first given kept), in order. */
internal fun pySortedSet(xs: List<Double>): List<Double> {
    val first = LinkedHashMap<Double, Double>()
    for (x in xs) first.putIfAbsent(if (x == 0.0) 0.0 else x, x)
    return first.values.sortedWith(::pyCompare)
}
