package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyHtml
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.theory.Theory

/**
 * chordpro.py: Ultimate Guitar sheet markup to ChordPro, with render.py's `_chordpro_text` and `_as_latin` and
 * ug/page.py's `decode_twice`. UG sheets, LaCuerda sheets (once `<A>X</A>` is `[ch]X[/ch]`) and auto-chords sheets
 * use one markup: chords are `[ch]X[/ch]` on chord lines placed above lyric lines; `[tab]…[/tab]` wraps
 * chord-and-lyric pairs, and real tablature; section headers are lines such as `[Verse 1]` or `[Chorus]`.
 *
 * A chord's position is its display column in the chord line once the tags are removed, as UG shows the sheet in a
 * monospace font: an East Asian wide character two columns, a combining mark none, a tab up to the next stop
 * ([displayColumns]). Lengths, columns and indexes are Python's, in code points.
 */
object ChordPro {
    private val C get() = SheetData.chordpro
    private val CHORD by lazy { C.pattern("_CHORD") }
    private val TAB_MARK by lazy { C.pattern("_TAB_MARK") }
    private val SECTION by lazy { C.pattern("_SECTION") }
    private val MARK by lazy { C.pattern("_MARK") }
    private val CHORD_LINE_REST by lazy { C.pattern("_CHORD_LINE_REST") }
    private val STAFF by lazy { C.pattern("_STAFF") }
    private val SOLFEGE by lazy { C.pattern("_SOLFEGE") }
    private val LEAD_GAP by lazy { C.pattern("_LEAD_GAP") }
    private val WORD by lazy { C.pattern("_WORD") }
    private val MARKUP_START by lazy { C.pattern("_MARKUP_START") }
    private val DECODED_BACKSLASH by lazy { C.pattern("_DECODED_BACKSLASH") }
    private val DIRECTIVE_LIKE by lazy { C.pattern("_DIRECTIVE_LIKE") }
    private val SOLFEGE_LETTER by lazy { C.strings("_SOLFEGE_LETTER") }
    private val BRACKETS by lazy { SheetData.translation(C.strings("_BRACKETS")) }
    private val ESCAPED_BACKSLASH by lazy { C.text("_ESCAPED_BACKSLASH") }
    private val AUTO_MARKER by lazy { SheetData.sheet.text("AUTO_MARKER") }
    private val ENTITY by lazy { SheetData.ugPage.pattern("_ENTITY") }
    private val LOOKALIKES by lazy { SheetData.translation(SheetData.render.strings("_LATIN_LOOKALIKES")) }

    /** chordpro.TAB_STOP. */
    val TAB_STOP: Int by lazy { C.int("TAB_STOP") }

    // --- chord names ------------------------------------------------------------------------------------------------

    /** normalize_chord: letter names for a solfège chord ("Do#m7" → "C#m7", "Sib" → "Bb", "Mi/Sol#" → "E/G#") and a
     * chord typed in lower case capitalised ("am" → "Am"); letter chords pass through ("Fadd9" stays). A solfège
     * name sre's IGNORECASE reads but no table holds ("ſol") raises, as Python's KeyError does. */
    fun normalizeChord(name: String): String {
        val (root, sep, bass) = Str.partition(name, "/")
        return letterRoot(root) + sep + (if (sep.isNotEmpty()) letterRoot(bass) else "")
    }

    private fun letterRoot(part: String): String {
        val m = PyRe.match(SOLFEGE, part) ?: return capital(part)
        val letter = SOLFEGE_LETTER[PyUnicode.lower(m.groupValues[1])]
            ?: throw NoSuchElementException("no letter for the solfège ${m.groupValues[1]}")
        return letter + part.substring(m.range.last + 1)
    }

    private fun capital(part: String): String {
        if (part.isEmpty() || part[0] !in "abcdefg") return part
        val named = ('A' + (part[0] - 'a')) + part.substring(1) // one of a to g, in capitals
        return if (Theory.parseChord(named) != null) named else part
    }

    // --- chord lines ------------------------------------------------------------------------------------------------

    /** tag_forgotten: a chord line with the chords nobody tagged tagged (`[ch]Dm[/ch]   Dm/F   [ch]E[/ch]`), when
     * every other word on it, but its bars, dashes and repeat marks, is a chord and there are no more of them than
     * tagged chords; any other line stays as it is. Columns do not move. */
    fun tagForgotten(line: String): String {
        val tagged = PyRe.finditer(CHORD, line).count()
        if (tagged == 0) return line
        val blank: (MatchResult) -> String = { Str.spaces(Py.len(it.value)) }
        val bare = PyRe.sub(MARK, PyRe.sub(CHORD, PyRe.sub(TAB_MARK, line, repl = blank), repl = blank), repl = blank)
        val forgotten = ArrayList<MatchResult>()
        for (m in PyRe.finditer(WORD, bare)) {
            if (PyRe.fullmatch(CHORD_LINE_REST, m.value) != null) continue
            if (Theory.parseChord(m.value) == null) return line
            forgotten += m
        }
        if (forgotten.isEmpty() || forgotten.size > tagged) return line
        // bare holds as many code points as line, each word where it is in line
        var out = line
        for (m in forgotten.asReversed()) {
            val start = out.offsetByCodePoints(0, bare.codePointCount(0, m.range.first))
            val end = start + m.value.length
            out = out.substring(0, start) + "[ch]" + m.value + "[/ch]" + out.substring(end)
        }
        return out
    }

    /** is_chord_line: whether a line holds chords and nothing else but bars, dashes, slashes and repeat marks. */
    fun isChordLine(line: String): Boolean {
        val tagged = tagForgotten(PyRe.sub(TAB_MARK, line) { "" })
        if (PyRe.search(CHORD, tagged) == null) return false
        val rest = PyRe.sub(MARK, PyRe.sub(CHORD, tagged) { " " }) { " " }
        return PyRe.fullmatch(CHORD_LINE_REST, rest) != null
    }

    /** merge_chord_line: one ChordPro line, each chord of the chord line placed at its column in the lyric line. A
     * chord beyond the end of the lyric is padded out with spaces; the spaces directly after the line's leading
     * chords are dropped, later chords stay on the same letters. */
    fun mergeChordLine(chords: String, lyrics: String): String {
        val text = Py.codePoints(escapeInline(Str.rstrip(Str.expandTabs(PyRe.sub(TAB_MARK, lyrics) { "" }, TAB_STOP))))
        val out = StringBuilder()
        var i = 0
        var col = 0
        for ((at, token) in chordItems(chords)) {
            while (i < text.size && col + width(text[i]) <= at) {
                col += width(text[i])
                out.appendCodePoint(text[i])
                i++
            }
            if (i == text.size && col < at) {
                out.append(Str.spaces(at - col))
                col = at
            }
            out.append(token)
        }
        out.append(Py.string(text, i))
        return finish(PyRe.sub(LEAD_GAP, out.toString()) { it.groupValues[1] })
    }

    // --- the document -----------------------------------------------------------------------------------------------

    /**
     * to_chordpro: UG sheet markup as a ChordPro document. A chord line followed by a lyric line becomes one line,
     * each chord at its column; a chord line with no lyric line under it a chord-only line; `[Verse 1]`
     * `{comment: Verse 1}`; a `[tab]` block holding staff lines, or a run of staff lines outside one,
     * `{start_of_tab}` … `{end_of_tab}`, kept verbatim; solfège chords letter names; repeat marks annotations
     * (`[*x2]`); text ChordPro would misread escaped. The header carries the title, the artist, the key and capo when
     * given, and an "auto-generated, unverified" comment for an auto-chords sheet.
     */
    fun toChordPro(markup: String, title: String, artist: String, key: String? = null, capo: Int? = null,
                   auto: Boolean = false): String = document(markup, title, artist, key, capo?.toString(), auto)

    /** [toChordPro] given the capo as UG's text ("2", " 0 "): `str(capo).strip()`. */
    fun toChordPro(markup: String, title: String, artist: String, key: String?, capo: String?,
                   auto: Boolean = false): String = document(markup, title, artist, key, capo, auto)

    private fun document(markup: String, title: String, artist: String, key: String?, capo: String?,
                         auto: Boolean): String {
        val head = arrayListOf("{title: ${directiveText(title)}}", "{artist: ${directiveText(artist)}}")
        val keyText = Py.strip(key ?: "")
        val capoText = if (capo == null) "" else Py.strip(capo)
        if (keyText.isNotEmpty()) head += "{key: ${directiveText(normalizeChord(keyText))}}"
        if (capoText != "" && capoText != "0") head += "{capo: ${directiveText(capoText)}}"
        if (auto) head += "{comment: $AUTO_MARKER}"
        return (head + body(markup)).joinToString("\n") + "\n"
    }

    /** render._chordpro_text: the .cho text of a sheet, its markup in ChordPro ([toChordPro]), then its stray
     * look-alike letters written in Latin ([asLatin]). */
    fun chordProText(markup: String, title: String, artist: String, key: String? = null, capo: Int? = null,
                     auto: Boolean = false): String = asLatin(toChordPro(markup, title, artist, key, capo, auto))

    /** [chordProText] given the capo as text. */
    fun chordProText(markup: String, title: String, artist: String, key: String?, capo: String?,
                     auto: Boolean = false): String = asLatin(toChordPro(markup, title, artist, key, capo, auto))

    /** One entry of the sheet: a line to convert, or a tab environment to keep verbatim. */
    private sealed interface Entry {
        class One(val line: String) : Entry
        class Block(val lines: MutableList<String>) : Entry
    }

    private fun body(content: String): List<String> {
        val entries = entries(content.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
        val out = ArrayList<String>()
        var i = 0
        while (i < entries.size) {
            val entry = entries[i]
            val next = entries.getOrNull(i + 1)
            i++
            if (entry is Entry.Block) {
                out += "{start_of_tab}"
                entry.lines.forEach { out += tabLine(it) }
                out += "{end_of_tab}"
                continue
            }
            val line = (entry as Entry.One).line
            if (isChordLine(line)) {
                if (next is Entry.One && isLyric(next.line)) {
                    out += mergeChordLine(line, next.line)
                    i++
                } else {
                    out += chordOnly(line)
                }
                continue
            }
            val section = section(line)
            if (section != null) {
                val (label, rest) = section
                if (isChordLine(rest)) {
                    out += "{comment: ${directiveText(label)}}"
                    out += chordOnly(rest)
                } else {
                    out += "{comment: ${directiveText(Str.rstrip("$label $rest"))}}"
                }
                continue
            }
            out += textLine(line)
        }
        return trimBlank(out)
    }

    /** _entries: lines to convert one by one, and tab environments to keep verbatim. A run of staff lines outside a
     * `[tab]` block is one block, which goes on across the runs it meets nothing else between, as Python's does. */
    private fun entries(lines: List<String>): List<Entry> {
        val entries = ArrayList<Entry>()
        var bare: Entry.Block? = null
        for ((inBlock, run) in runs(lines)) {
            if (inBlock && run.any(::isStaff)) {
                entries += Entry.Block(trimBlank(run).toMutableList())
                bare = null
                continue
            }
            for (line in run) {
                if (isStaff(line)) {
                    val block = bare ?: Entry.Block(ArrayList()).also { bare = it; entries += it }
                    block.lines += line
                } else {
                    bare = null
                    entries += Entry.One(line)
                }
            }
        }
        return entries
    }

    /** _runs: the sheet split into runs inside and outside `[tab]` blocks, markers removed. */
    private fun runs(lines: List<String>): List<Pair<Boolean, List<String>>> {
        val runs = ArrayList<Pair<Boolean, List<String>>>()
        var run = ArrayList<String>()
        var inBlock = false
        for (raw in lines) {
            if ("[tab]" in raw && !inBlock) {
                if (run.isNotEmpty()) runs += false to run
                run = ArrayList()
                inBlock = true
            }
            val line = PyRe.sub(TAB_MARK, raw) { "" }
            if (!Str.blank(line) || line == raw) run += line // a line holding only markers is no blank line
            if ("[/tab]" in raw && inBlock) {
                runs += true to run
                run = ArrayList()
                inBlock = false
            }
        }
        if (run.isNotEmpty()) runs += inBlock to run
        return runs
    }

    private fun isStaff(line: String): Boolean = PyRe.fullmatch(STAFF, line) != null && Str.count(line, "-") >= 3

    private fun isLyric(line: String): Boolean =
        !Str.blank(line) && PyRe.search(CHORD, line) == null && section(line) == null

    /** _section: a section header's label, and the chords or repeat mark after it on its line. */
    private fun section(line: String): Pair<String, String>? {
        val m = PyRe.fullmatch(SECTION, line) ?: return null
        val label = m.groupValues[1]
        val rest = m.groupValues[2]
        if (rest.isNotEmpty() && !(isChordLine(rest) || PyRe.fullmatch(MARK, rest) != null)) return null
        return label to rest
    }

    private fun chordOnly(line: String): String = chordItems(line).joinToString(" ") { it.second }

    /** One chord or mark of a chord line: where it starts in its text with the tags removed (a UTF-16 offset), where
     * it ends, and its ChordPro token. */
    private class Span(val start: Int, val end: Int, val token: String)

    private val SPAN_ORDER = Comparator<Span> { a, b ->
        when {
            a.start != b.start -> a.start.compareTo(b.start)
            a.end != b.end -> a.end.compareTo(b.end)
            else -> Py.CODE_POINT_ORDER.compare(a.token, b.token)
        }
    }

    /** _chord_items: the chords and marks of a chord line, as (display column, ChordPro token), in order. */
    private fun chordItems(chordLine: String): List<Pair<Int, String>> {
        val line = tagForgotten(PyRe.sub(TAB_MARK, chordLine) { "" })
        val plain = StringBuilder()
        val spans = ArrayList<Span>()
        var pos = 0
        for (m in PyRe.finditer(CHORD, line)) {
            plain.append(line, pos, m.range.first)
            val group = m.groupValues[1]
            // ChordPro draws chord names with markup too, and its <img> opens a local file.
            val name = escapeInline(normalizeChord(Py.strip(group).replace("[", "").replace("]", "")))
            spans += Span(plain.length, plain.length + group.length, if (name.isNotEmpty()) "[$name]" else "")
            plain.append(group)
            pos = m.range.last + 1
        }
        plain.append(line, pos, line.length)
        val text = plain.toString()
        for (m in PyRe.finditer(MARK, text)) {
            val at = m.range.first
            if (spans.none { it.start <= at && at < it.end }) {
                spans += Span(at, m.range.last + 1, "[*${Py.strip(m.value)}]")
            }
        }
        val columns = columnsByOffset(text)
        return spans.sortedWith(SPAN_ORDER).filter { it.token.isNotEmpty() }.map { columns[it.start] to it.token }
    }

    /** display_columns: the display column at which each character of [text] starts, then the one where it ends, as
     * a monospace font shows it: a wide East Asian character (Chinese, kana, Hangul, full-width punctuation) two
     * columns, a combining mark none, a tab up to the next stop. One entry a code point, and one more. */
    fun displayColumns(text: String): List<Int> {
        val cols = ArrayList<Int>(text.length + 1)
        var col = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            i += Character.charCount(cp)
            cols += col
            col = advance(col, cp)
        }
        cols += col
        return cols
    }

    /** [displayColumns] by UTF-16 offset: the column at which the code point at each offset starts (a low
     * surrogate's slot holds its pair's), and at [text]'s length where it ends. */
    private fun columnsByOffset(text: String): IntArray {
        val cols = IntArray(text.length + 1)
        var col = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val n = Character.charCount(cp)
            for (k in 0 until n) cols[i + k] = col
            i += n
            col = advance(col, cp)
        }
        cols[text.length] = col
        return cols
    }

    private fun advance(col: Int, cp: Int): Int =
        if (cp == '\t'.code) (col / TAB_STOP + 1) * TAB_STOP else col + width(cp)

    private fun width(cp: Int): Int {
        if (PyUnicode.combining(cp) != 0) return 0
        val w = PyUnicode.eastAsianWidth(cp)
        return if (w == "W" || w == "F") 2 else 1
    }

    /** _text_line: a lyric or note line; chord names in running text stay as plain text. */
    private fun textLine(line: String): String {
        val named = PyRe.sub(CHORD, line) { normalizeChord(Py.strip(it.groupValues[1])) }
        return finish(escapeInline(Str.expandTabs(named, TAB_STOP)))
    }

    /** _tab_line: a tablature line, verbatim but for chord tags and what ChordPro would misread. */
    private fun tabLine(raw: String): String {
        var line = Str.rstrip(PyRe.sub(CHORD, raw) { it.groupValues[1] })
        if (PyRe.fullmatch(DIRECTIVE_LIKE, line) != null) line = Str.translate(line, BRACKETS)
        return finish(line)
    }

    // What ChordPro 6.050.7 misreads in text, checked against the binary: any [..] is a chord (no escape exists),
    // {..} on its own line is a directive, %{..} is a metadata substitution, <..> is Pango-style markup (and &lt; is
    // not decoded), a line starting with # is a comment, a trailing backslash joins the next line, and a backslash
    // followed by u and four hex digits is decoded as a character.

    /** _escape_inline: the characters that would read as a chord, a directive, a substitution or markup swapped. */
    private fun escapeInline(text: String): String = PyRe.sub(MARKUP_START, Str.translate(text, BRACKETS)) { "‹" }

    private fun escapeBackslashes(line: String): String = PyRe.sub(DECODED_BACKSLASH, line) { ESCAPED_BACKSLASH }

    /** directive_text: text for a directive's value (`{title: …}`), on one line, as [toChordPro] writes it: nothing
     * in it reads as a chord, a directive, a substitution or markup. */
    fun directiveText(text: String): String = escapeBackslashes(escapeInline(Py.split(text).joinToString(" ")))

    /** _finish: the last touches on an output line: no trailing space, no comment-like start. */
    private fun finish(line: String): String {
        val done = escapeBackslashes(Str.rstrip(line))
        return if (done.startsWith("#")) " $done" else done
    }

    private fun trimBlank(lines: List<String>): List<String> {
        var start = 0
        var end = lines.size
        while (start < end && Str.blank(lines[start])) start++
        while (end > start && Str.blank(lines[end - 1])) end--
        return lines.subList(start, end).toList()
    }

    // --- render.py and ug/page.py ------------------------------------------------------------------------------------

    /** render.needs_font_file: whether ChordPro's built-in fonts (PDF core fonts in WinAnsi encoding) would lose
     * some of [text]: anything cp1252 can't encode. */
    fun needsFontFile(text: String): Boolean {
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (!cp1252(cp)) return true
            i += Character.charCount(cp)
        }
        return false
    }

    private val ENCODABLE: List<IntRange> by lazy {
        SheetData.render.ranges("cp1252")
    }

    private fun cp1252(cp: Int): Boolean = cp < 0x80 || ENCODABLE.any { cp in it }

    /** render._as_latin: [text] with its look-alike letters (Cyrillic and Greek ones drawn exactly like Latin ones)
     * written in Latin, when they are its only letters the built-in fonts lose: a stray "х2" (a Cyrillic х) in an
     * English sheet then needs no font file. Text with other such letters (a Russian or a Chinese sheet) is left as
     * written. */
    fun asLatin(text: String): String {
        var lost = false
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            i += Character.charCount(cp)
            if (PyUnicode.category(cp).startsWith("L") && !cp1252(cp)) {
                if (cp !in LOOKALIKES) return text
                lost = true
            }
        }
        return if (lost) Str.translate(text, LOOKALIKES) else text
    }

    /** ug.page.decode_twice: HTML entities decoded, and once more when the result still holds one. UG escapes a
     * sheet's text inside its JSON ("&amp;"), and some sheets were escaped twice on its side ("&amp;amp;feature"). */
    fun decodeTwice(text: String): String {
        val once = PyHtml.unescape(text)
        return if (PyRe.search(ENTITY, once) != null) PyHtml.unescape(once) else once
    }
}
