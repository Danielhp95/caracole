package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr

/**
 * coverage.py: how much of a song's lyrics a chord sheet holds. A sheet is complete when it covers at least
 * [RankPolicy.coverageThreshold] of the song's distinct lyric lines ([lyricLines]); a line counts as covered when
 * rapidfuzz's `partial_ratio` against the sheet's lyric text ([sheetLyricText]) is [RankPolicy.lineMatch] or more, or,
 * for a sheet whose lyric text is shorter than the line, their whole-string `ratio` is ([match]). Chinese is compared
 * as pinyin ([comparable]), so Traditional lyrics meet a Simplified sheet.
 *
 * Its regexes are Python's, through PyRegex (`\W`, `\s` and `\d` with Python's Unicode, IGNORECASE folding as sre
 * does); lines are `str.splitlines`'s, words `str.split()`'s, lengths in code points
 * (vectors/sites/ug_coverage.jsonl, tests/test_conformance_rank.py).
 */
object Coverage {
    /** coverage.MIN_LINE_CHARS: a shorter lyric line is no evidence. */
    const val MIN_LINE_CHARS = 4

    private val NON_WORD = PyRegex.compile("""[\W_]+""")
    private val CH_SPAN = PyRegex.compile("""(?i)\[ch\].*?\[/ch\]""")
    private val TAB_TAGS = PyRegex.compile("""(?i)\[/?tab\]""")
    private val SECTION = PyRegex.compile("""^\s*\[[^\]\n]*\]\s*$""")
    private val FILLER = PyRegex.compile("""(?i)^[\s|/\\\-–x×0-9().:*]*$""")
    private val STAFF = PyRegex.compile("""^\s*[A-Ga-g]?[#b]?\s*\|.*-{2,}""")
    private val CHORD_TOKEN = PyRegex.compile(
        """(?i)^\(?(?:[A-G][#b]?|(?:do|re|mi|fa|sol|la|si)[#b]?)""" +
            """(?:m|maj|min|dim|aug|sus|add|M|°|ø|\+|-)?\d*(?:(?:sus|add|maj|b|#)\d+)*""" +
            """(?:/[A-G][#b]?)?\)?$""",
    )
    private val FILLER_TOKEN = PyRegex.compile("""(?i)^(?:\||-+|/|x\d+|\(x?\d+\)|\d+x|\*+)$""")

    /** coverage.normalize_line: accents and case folded, punctuation made spaces, whitespace collapsed. */
    fun normalizeLine(s: String): String = Py.split(PyRe.sub(NON_WORD, Normalize.fold(s)) { " " }).joinToString(" ")

    /** coverage.lyric_lines: the distinct normalized lyric lines (a chorus counts once; very short lines skipped). */
    fun lyricLines(plain: String): List<String> {
        val seen = HashSet<String>()
        val out = ArrayList<String>()
        for (line in PyStr.splitlines(plain)) {
            val n = normalizeLine(line)
            if (Py.len(n) < MIN_LINE_CHARS || !seen.add(n)) continue
            out += n
        }
        return out
    }

    /** coverage._is_plain_chord_line: a line of chord names (and filler) alone, at least one chord. */
    fun isPlainChordLine(line: String): Boolean {
        val tokens = Py.split(line)
        if (tokens.isEmpty()) return false
        val chords = tokens.filter { PyRe.match(CHORD_TOKEN, it) != null }
        return chords.isNotEmpty() &&
            tokens.all { PyRe.match(CHORD_TOKEN, it) != null || PyRe.match(FILLER_TOKEN, it) != null }
    }

    /**
     * coverage.sheet_lyric_text: the lyrics in a sheet, one normalized string: chord lines (`[ch]` markup or plain
     * chord names), tab staff lines and `[Section]` headers dropped, chords written inline removed.
     */
    fun sheetLyricText(sheet: String): String {
        val kept = ArrayList<String>()
        for (raw in PyStr.splitlines(sheet)) {
            val line = PyRe.sub(TAB_TAGS, raw) { "" }
            val withoutChords = PyRe.sub(CH_SPAN, line) { " " }
            if (PyRe.search(CH_SPAN, line) != null && PyRe.match(FILLER, withoutChords) != null) continue
            if (PyRe.match(SECTION, line) != null || PyRe.match(STAFF, line) != null) continue
            if (isPlainChordLine(withoutChords)) continue
            val text = normalizeLine(withoutChords)
            if (text.isNotEmpty()) kept += text
        }
        return kept.joinToString(" ")
    }

    /** coverage._comparable: Chinese text as pinyin, normalized; any other as it is. */
    fun comparable(s: String): String = if (Normalize.hasHan(s)) normalizeLine(Normalize.romanize(s)) else s

    /** coverage.coverage: the share of [lines] ([lyricLines]'s) the sheet holds; null without lyrics. */
    fun coverage(sheet: String, lines: List<String>, lineMatch: Double = 85.0): Double? {
        if (lines.isEmpty()) return null
        val text = comparable(sheetLyricText(sheet))
        if (text.isEmpty()) return 0.0
        val covered = lines.count { match(comparable(it), text) >= lineMatch }
        return covered.toDouble() / lines.size.toDouble()
    }

    /** The sheet's coverage of a song's plain [lyrics] at the policy's line match, as ug/fetch.py and
     * lacuerda_fetch.py score one (`coverage(sheet, lyric_lines(plain), line_match=rank.line_match)`). */
    fun coverage(sheetText: String, lyrics: String, policy: RankPolicy): Double? =
        coverage(sheetText, lyricLines(lyrics), policy.lineMatch)

    /**
     * coverage._match: how well the sheet's lyric [text] holds a lyric [line], 0–100: `partial_ratio`, which finds
     * the line inside the text; but a text shorter than the line can't hold it (a sheet whose only word is "I" sits
     * inside most lines), so the two are then compared whole.
     */
    fun match(line: String, text: String): Double =
        if (Py.len(text) >= Py.len(line)) Fuzz.partialRatioAlignment(line, text).score else Fuzz.ratio(line, text)
}
