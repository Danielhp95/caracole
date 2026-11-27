package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** align.Alignment: what [Align.lyricsOffset] found. [offset]: the seconds to add to every LRC time (0.0 for none
 * needed), or null when no shift fits clearly; [why] says why, in align.py's words; [best], [score] and [runnerUp] as
 * align.py keeps them (`round(…, 3)`; [runnerUp] -inf where every candidate is within a beat of the best). */
data class Alignment(
    val offset: Double?, val why: String, val best: Double? = null, val score: Double? = null,
    val runnerUp: Double? = null,
)

/**
 * autochords/align.py on the phone, function for function: how far to shift LRCLIB's timed lyrics to fit audio of
 * another length, scored from the chords and beats alone ([lyricsOffset]), and the LRC so moved ([shiftedLrc]). Its
 * constants are align.py's (autochords.json); its grid, bars and snapped chords [AutoSheet]'s, as align.py takes
 * merge.py's.
 *
 * Every score is Python's float arithmetic in Python's order: `statistics.fmean` math.fsum's correctly rounded sum
 * over the count (Py.mathFsum), the builtin `sum` Neumaier's (Py.fsum), `max` the first of those tied; a line's words
 * folded as `" ".join(re.findall(r"\w+", text.casefold()))` (PyUnicode.casefold, PyRegex's `\w`); [Alignment.why]'s
 * numbers as Python's format specs write them (PyFormat: `.2f`, `.3f`, `+.2f`), an LRC stamp's too (`02d`, `06.3f`
 * over `divmod`).
 */
object Align {
    private val align by lazy { ViewerData.table("autochords").getValue("align").jsonObject }
    private fun number(name: String): Double = align.getValue(name).jsonPrimitive.double
    private fun count(name: String): Int = align.getValue(name).jsonPrimitive.int

    private val MAX_SHIFT by lazy { number("MAX_SHIFT") }
    private val STEPS_PER_BEAT by lazy { count("STEPS_PER_BEAT") }
    private val MIN_LINES by lazy { count("MIN_LINES") }
    private val WEIGHTS: Map<String, Double> by lazy {
        align.getValue("WEIGHTS").jsonObject.mapValues { it.value.jsonPrimitive.double }
    }
    private val BAR_SHARE by lazy { number("BAR_SHARE") }
    private val EXTENT_COST by lazy { number("EXTENT_COST") }
    private val PRIOR by lazy { number("PRIOR") }
    private val MARGIN by lazy { number("MARGIN") }
    private val MIN_ONSETS by lazy { number("MIN_ONSETS") }
    private val MIN_COVERAGE by lazy { number("MIN_COVERAGE") }
    private val STEADY_BARS by lazy { count("STEADY_BARS") }
    private val REPEAT_CHARS by lazy { count("REPEAT_CHARS") }
    private val REPEATS_PER_LINE by lazy { count("REPEATS_PER_LINE") }
    private val EPS by lazy { number("EPS") }

    /** align._WORD: a line's words, for its key. */
    private val WORD by lazy { PyRegex.compile(align.getValue("WORD").jsonPrimitive.content) }

    private class Line(val start: Double, val end: Double, val key: String)

    /** align._Fit: a candidate shift and what it scored, before anything is rounded. */
    internal class Fit(val offset: Double, val score: Double, val onsets: Double, val coverage: Double)

    /** What [lyricsOffset] weighs: every candidate's [Fit], in order, and the audio's beat; or, where it scores
     * none, its answer ([early]). */
    internal class Scored(val fits: List<Fit>, val beat: Double, val early: Alignment? = null)

    /** _Audio: the chords and bars of the audio, to look times up in. */
    private class Audio(segments: List<ChordSegment>, beats: List<Double>, downbeats: List<Double>, until: Double) {
        val segs = AutoSheet.snapToBeats(segments, beats)
        val starts = segs.map { it.start }
        private val grid = AutoSheet.beatGrid(beats, until)
        val beat = AutoSheet.period(grid)?.takeIf { it != 0.0 } ?: 0.0
        val bars = AutoSheet.barStarts(grid, starts, downbeats)
        val bar = AutoSheet.period(bars)?.takeIf { it != 0.0 } ?: (AutoSheet.BEATS_PER_BAR * beat)
        val changes = pySortedSet(starts)

        fun chordAt(t: Double): String? {
            val i = bisectRight(starts, t) - 1
            return if (i >= 0 && segs[i].end > t) segs[i].label else null
        }

        /** Seconds of [a, b) during which some chord sounds. */
        fun sounding(a: Double, b: Double): Double {
            var i = maxOf(bisectRight(starts, a) - 1, 0)
            var total = 0.0
            while (i < segs.size && segs[i].start < b) {
                total += pyMax(0.0, pyMin(b, segs[i].end) - pyMax(a, segs[i].start))
                i++
            }
            return total
        }

        /** Where the music starts and ends: the first and last chords of steady stretches. */
        fun music(window: Double): Pair<Double, Double> {
            val start = segs.firstOrNull { sounding(it.start, it.start + window) >= window / 2 }?.start ?: segs[0].start
            val end = segs.lastOrNull { sounding(it.end - window, it.end) >= window / 2 }?.end ?: segs.last().end
            return start to end
        }
    }

    /** lyrics_offset: how far to shift the timed [lines] (Lrc.parse's) to fit the audio the models heard as [heard],
     * [beats] and [downbeats], [audioS] long, when LRCLIB timed them against a release [lyricsS] long. */
    fun lyricsOffset(
        lines: List<Pair<Double, String>>, heard: List<ChordSegment>, beats: List<Double>, downbeats: List<Double>,
        audioS: Double, lyricsS: Double,
    ): Alignment {
        val scored = scored(lines, heard, beats, downbeats, audioS, lyricsS)
        scored.early?.let { return it }
        val fits = scored.fits
        val beat = scored.beat
        var best = fits[0]
        for (f in fits.drop(1)) {  // max by (score, -abs(offset)): the first of those tied
            if (f.score > best.score || (f.score == best.score && -Math.abs(f.offset) > -Math.abs(best.offset))) best = f
        }
        val others = fits.filter { Math.abs(it.offset - best.offset) > beat + EPS }.map { it.score }
        val runnerUp = others.reduceOrNull(::pyMax) ?: Double.NEGATIVE_INFINITY
        fun found(offset: Double?, why: String) =
            Alignment(offset, why, Py.round(best.offset, 3), Py.round(best.score, 3), Py.round(runnerUp, 3))
        if (best.onsets < MIN_ONSETS) {
            return found(null, "the lines land on no bars or chord changes (onsets ${f2(best.onsets)})")
        }
        if (best.coverage < MIN_COVERAGE) {
            return found(null, "the lines land where no chord sounds (coverage ${f2(best.coverage)})")
        }
        if (best.score - runnerUp < MARGIN) {
            return found(null, "no clear winner (${f3(best.score)} at ${signed(best.offset)} s, " +
                                   "${f3(runnerUp)} a beat or more away)")
        }
        val offset = if (Math.abs(best.offset) <= beat + EPS) 0.0 else Py.round(best.offset, 3)
        return found(offset, "${f3(best.score)} at ${signed(best.offset)} s, ${f3(runnerUp)} a beat or more away")
    }

    /** lyrics_offset up to its candidates scored (its answer, where it gives one before: too few lines, no chords
     * or no beats). */
    internal fun scored(
        lines: List<Pair<Double, String>>, heard: List<ChordSegment>, beats: List<Double>, downbeats: List<Double>,
        audioS: Double, lyricsS: Double,
    ): Scored {
        fun early(why: String) = Scored(emptyList(), 0.0, Alignment(null, why))
        val sung = sung(lines)
        if (sung.size < MIN_LINES) return early("${sung.size} sung lines, too few to place")
        val audio = Audio(heard, beats, downbeats, (listOf(audioS) + heard.map { it.end }).reduce(::pyMax))
        if (audio.segs.isEmpty() || audio.beat <= 0.0 || audio.bars.size < 2) {
            return early("no chords or no beats to place the lines by")
        }
        val d = audioS - lyricsS
        val pairs = repeated(sung)
        val music = audio.music(STEADY_BARS * audio.bar)
        val least = pyMax(0.0, music.second - music.first - lyricsS)  // the overhang no shift avoids
        return Scored(candidates(d, audio.beat, audio.bar).map { fit(it, sung, pairs, audio, d, music, lyricsS, least) },
                      audio.beat)
    }

    private fun f2(x: Double) = PyFormat.fixed(x, 2)
    private fun f3(x: Double) = PyFormat.fixed(x, 3)

    /** f"{x:+.2f}": a sign always, "-" for a negative zero too. */
    private fun signed(x: Double): String {
        val body = PyFormat.fixed(x, 2)
        return if (body.startsWith("-")) body else "+$body"
    }

    /** shifted_lrc: the LRC [text] with every stamp moved by [offset] seconds, a line's and each word's alike; the
     * rest as written. A time moved before the start is dropped, its line with it once it has no other; a word stamp
     * so moved starts at 0. */
    fun shiftedLrc(text: String, offset: Double): String {
        val out = ArrayList<String>()
        for (raw in PyStr.splitlines(Lrc.lstripBom(text))) {
            val line = Py.strip(raw)
            val stamps = PyRe.match(Lrc.STAMP_RUN, line)
            if (stamps == null) {
                out += raw
                continue
            }
            val times = PyRe.finditer(Lrc.STAMP, stamps.value).map { Py.round(Lrc.seconds(it) + offset, 3) }.toList()
            if (times.all { it < 0.0 }) continue
            val words = PyRe.sub(Lrc.WORD_TIME, line.substring(stamps.range.last + 1)) {
                stamp(Lrc.seconds(it) + offset, '<', '>')
            }
            out += times.filter { it >= 0.0 }.joinToString("") { stamp(it, '[', ']') } + words
        }
        return out.joinToString("\n") + "\n"
    }

    /** _stamp: an LRC stamp of [t] seconds (0 for before the start), `[mm:ss.xxx]`, from Python's float divmod. */
    private fun stamp(t: Double, open: Char, close: Char): String {
        val (minutes, seconds) = divmod(pyMax(0.0, Py.round(t, 3)), 60.0)
        // int(minutes), unbounded: a float's whole value, never a Long's
        val m = java.math.BigDecimal(minutes).toBigInteger().toString().padStart(2, '0')
        return "$open$m:${PyFormat.fixed(seconds, 3, 6, zero = true)}$close"
    }

    /** divmod(x, y) of floats, CPython's float_divmod. */
    private fun divmod(vx: Double, wx: Double): Pair<Double, Double> {
        var mod = vx % wx  // fmod
        var div = (vx - mod) / wx
        if (mod != 0.0) {
            if ((wx < 0.0) != (mod < 0.0)) {
                mod += wx
                div -= 1.0
            }
        } else {
            mod = Math.copySign(0.0, wx)
        }
        val floordiv: Double
        if (div != 0.0) {
            var f = Math.floor(div)
            if (div - f > 0.5) f += 1.0
            floordiv = f
        } else {
            floordiv = Math.copySign(0.0, vx / wx)
        }
        return floordiv to mod
    }

    /** _sung: the sung lines, each until the next LRC entry or a typical line's length, whichever is first. */
    private fun sung(lines: List<Pair<Double, String>>): List<Line> {
        val timed = lines.sortedWith { a, b -> pyCompare(a.first, b.first) }
        val windows = ArrayList<Double>()
        for (j in 0 until timed.size - 1) {
            val (t, text) = timed[j]
            val next = timed[j + 1].first
            if (text.isNotEmpty() && next > t) windows += next - t
        }
        val typical = if (windows.isNotEmpty()) AutoSheet.median(windows) else 0.0
        val out = ArrayList<Line>()
        for ((j, line) in timed.withIndex()) {
            val (t, text) = line
            if (text.isEmpty()) continue
            val next = if (j + 1 < timed.size) timed[j + 1].first else Double.POSITIVE_INFINITY
            val end = pyMin(next, t + typical)
            if (end > t) out += Line(t, end, PyRe.findall(WORD, PyUnicode.casefold(text)).joinToString(" "))
        }
        return out
    }

    /** _repeated: pairs of lines sung with the same words, long enough to count. */
    private fun repeated(sung: List<Line>): List<Pair<Line, Line>> {
        val groups = LinkedHashMap<String, ArrayList<Line>>()
        for (line in sung) if (Py.len(line.key) >= REPEAT_CHARS) groups.getOrPut(line.key) { ArrayList() } += line
        val out = ArrayList<Pair<Line, Line>>()
        for (group in groups.values) {
            val first = group.take(REPEATS_PER_LINE)
            for ((i, a) in first.withIndex()) {
                for (b in group.subList(minOf(i + 1, group.size), minOf(REPEATS_PER_LINE, group.size))) out += a to b
            }
        }
        return out
    }

    /** _candidates: every quarter beat within MAX_SHIFT either way, d and a bar either side of it, 0 and d, each once,
     * in order. */
    private fun candidates(d: Double, beat: Double, bar: Double): List<Double> {
        val step = beat / STEPS_PER_BEAT
        val reach = (MAX_SHIFT / step).toInt()
        val nearD = (bar / step).toInt() + 1
        val found = ArrayList<Double>()
        for (k in -reach..reach) found += Py.round(k * step, 3)
        for (k in -nearD..nearD) found += Py.round(d + k * step, 3)
        found += 0.0
        found += Py.round(d, 3)
        return pySortedSet(found)
    }

    /** _overhang: seconds of the audio's music outside the lyrics' length, once shifted by [o]. */
    private fun overhang(o: Double, music: Pair<Double, Double>, lyricsS: Double): Double =
        pyMax(0.0, o - music.first) + pyMax(0.0, music.second - lyricsS - o)

    private fun closeness(points: List<Double>, t: Double, width: Double): Double {
        val i = bisectLeft(points, t)
        var near = Double.POSITIVE_INFINITY
        var any = false
        for (k in intArrayOf(i - 1, i)) {
            if (k < 0 || k >= points.size) continue
            val far = Math.abs(points[k] - t)
            if (!any || far < near) near = far  // min(): the first of those tied
            any = true
        }
        return pyMax(0.0, 1.0 - near / width)
    }

    /** _family: a chord by its root, major or minor. */
    private fun family(label: String?): String? {
        if (label == null) return null
        val second = Py.slice(label, 1, 2)
        val root = if (second == "#" || second == "b") Py.slice(label, null, 2) else Py.slice(label, null, 1)
        val rest = Py.slice(label, Py.len(root), null)
        val minor = (rest.startsWith("m") || rest.startsWith("dim")) && !rest.startsWith("maj")
        return root + (if (minor) "m" else "")
    }

    private fun fit(
        o: Double, sung: List<Line>, pairs: List<Pair<Line, Line>>, audio: Audio, d: Double,
        music: Pair<Double, Double>, lyricsS: Double, least: Double,
    ): Fit {
        val beat = audio.beat
        val bar = audio.bar
        val onsets = fmean(sung.map {
            BAR_SHARE * closeness(audio.bars, it.start + o, beat) +
                (1 - BAR_SHARE) * closeness(audio.changes, it.start + o, beat)
        })
        val coverage = fmean(sung.map { audio.sounding(it.start + o, it.end + o) / (it.end - it.start) })
        val measures = linkedMapOf("onsets" to onsets, "coverage" to coverage)
        if (pairs.isNotEmpty()) measures["repeats"] = fmean(pairs.map { (a, b) -> agreement(a, b, o, audio) })
        val evidence = Py.fsum(measures.map { (k, v) -> WEIGHTS.getValue(k) * v }) /
            Py.fsum(measures.keys.map { WEIGHTS.getValue(it) })
        val over = pyMax(0.0, overhang(o, music, lyricsS) - least - bar)
        val prior = PRIOR * pyMin(1.0, pyMax(0.0, 2.0 - pyMin(Math.abs(o), Math.abs(o - d)) / beat))
        return Fit(o, evidence - EXTENT_COST * over / bar + prior, onsets, coverage)
    }

    /** _agreement: the share of half beats over which two lines sung with the same words have the same chords. */
    private fun agreement(a: Line, b: Line, o: Double, audio: Audio): Double {
        val step = audio.beat / 2
        val n = maxOf(1, (pyMin(a.end - a.start, b.end - b.start) / step).toInt())
        var same = 0
        for (k in 0 until n) {
            val x = (k + 0.5) * step + o
            val one = family(audio.chordAt(a.start + x))
            if (one != null && one == family(audio.chordAt(b.start + x))) same++
        }
        return same.toDouble() / n
    }

    /** statistics.fmean: math.fsum's sum over the count. */
    private fun fmean(xs: List<Double>): Double {
        require(xs.isNotEmpty()) { "fmean requires at least one data point" }
        return Py.mathFsum(xs) / xs.size
    }
}
