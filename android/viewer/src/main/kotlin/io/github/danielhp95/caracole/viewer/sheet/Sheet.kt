package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.shapes.Position
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.theory.Chord
import java.math.BigInteger

/** What a chord's place in a line of viewer/sheet.py holds: a chord, by its index into [Sheet.chords], or a repeat
 * mark ("x2") as text. */
sealed interface Item {
    data class Chord(val index: Int) : Item
    data class Mark(val text: String) : Item
}

/** sheet.Line: a line of a section. */
sealed interface Line

/** sheet.Lyrics: a sung line, (chord, text) parts; a null chord for the words before the first chord. */
data class Lyrics(val parts: List<Pair<Item?, String>>) : Line

/** sheet.ChordRow: a line of chords alone, and repeat marks. */
data class ChordRow(val items: List<Item>) : Line

/** sheet.Text. */
data class Text(val text: String) : Line

/** sheet.Tab. */
data class Tab(val lines: List<String>) : Line

/** sheet.Blank: the space between two stanzas of a section. */
data object Blank : Line

/** sheet.Section: [label] as the sheet wrote it (a `{comment: }` with nothing after it is "", no label at all null). */
data class Section(val label: String?, val chorus: Boolean = false, val lines: List<Line> = emptyList())

/** sheet.Sheet: a ChordPro sheet as caracole writes it, read; [chords] as written, each once, in order of
 * appearance; [defines] each `{define}` and `{chord}` as written after its colon. A `{capo}` past what an Int holds
 * is none (Python keeps its whole number). */
data class Sheet(val title: String = "", val artist: String = "", val key: String? = null, val capo: Int? = null,
                 val auto: Boolean = false, val chords: List<String> = emptyList(),
                 val sections: List<Section> = emptyList(), val defines: List<String> = emptyList())

/** sheet.Preamble: what [Sheets.splitPreamble] finds before a sheet's first section. [tabs] is always empty: the
 * rule ends the preamble at the first tab. [end] is the index of the first body line (0 for none). */
data class Preamble(val notes: List<String>, val legend: List<Pair<Chord, Position>>, val tabs: List<Pair<Int, Int>>,
                    val tuning: String?, val capoNote: String?, val end: Int)

/**
 * viewer/sheet.py: the ChordPro file caracole writes (ChordPro.toChordPro), read back for the viewer. Only what that
 * file holds is read: the `title`, `artist`, `key` and `capo` directives, `comment` (a section's name), tab and
 * chorus environments, and lines with `[Chord]` and `[*mark]` in them; and the fingerings a sheet may give its chords
 * (`define` and `chord`, kept as written for Voicings.parseDefine). Other directives and `#` comment lines are
 * skipped. The escapes ChordPro needed (a backslash written `\`) are undone. Lines are Python's (str.splitlines),
 * whitespace and lengths Python's, in code points.
 */
object Sheets {
    private val S get() = SheetData.sheet
    private val DIRECTIVE by lazy { S.pattern("_DIRECTIVE") }
    private val TOKEN by lazy { S.pattern("_TOKEN") }
    private val FRET by lazy { S.pattern("_FRET") }
    private val CHORUS by lazy { S.pattern("_CHORUS") }
    private val TUNING_NAME by lazy { S.pattern("_TUNING_NAME") }
    private val TUNING_LABEL by lazy { S.pattern("_TUNING_LABEL") }
    private val CAPO by lazy { S.pattern("_CAPO") }
    private val NOT_A_LETTER by lazy { PyRegex.compile("[^a-z]") }
    private val ESCAPED_BACKSLASH by lazy { S.text("_ESCAPED_BACKSLASH") }
    private val STANDARD by lazy { S.list("_STANDARD").toSet() }
    private val AUTO_MARKER by lazy { S.text("AUTO_MARKER") }

    /** sheet.COMMENTS: the directives that name a section. */
    val COMMENTS: Set<String> by lazy { java.util.Collections.unmodifiableSet(LinkedHashSet(S.list("COMMENTS"))) }

    private class Building(val label: String?, val chorus: Boolean) {
        val lines = ArrayList<Line>()
    }

    /** parse_sheet: the sheet a ChordPro text holds. */
    fun parse(cho: String): Sheet {
        var title = ""
        var artist = ""
        var key: String? = null
        var capo: Int? = null
        var auto = false
        val chords = ArrayList<String>()
        val index = HashMap<String, Int>()
        val defines = ArrayList<String>()
        val sections = ArrayList<Building>()
        var section = Building(null, false)
        sections += section
        var tab: ArrayList<String>? = null

        fun chord(name: String): Int = index.getOrPut(name) { chords += name; chords.size - 1 }

        fun start(label: String?, chorus: Boolean = false) {
            section = Building(label, chorus || (!label.isNullOrEmpty() && PyRe.search(CHORUS, label) != null))
            sections += section
        }

        for (raw in PyStr.splitlines(cho)) {
            val line = raw.replace(ESCAPED_BACKSLASH, "\\")
            val open = tab
            if (open != null) {
                val d = PyRe.fullmatch(DIRECTIVE, line)
                if (d != null && Py.asciiLower(d.groupValues[1]) in END_OF_TAB) {
                    section.lines += Tab(open.toList())
                    tab = null
                } else {
                    open += line
                }
                continue
            }
            val d = PyRe.fullmatch(DIRECTIVE, line)
            if (d != null) {
                val name = Py.asciiLower(d.groupValues[1])
                val value = Py.strip(d.groups[2]?.value ?: "")
                when {
                    name == "title" || name == "t" -> title = value
                    name == "artist" -> artist = value
                    name == "key" -> key = value.ifEmpty { null }
                    name == "capo" -> capo = fret(value)
                    name in COMMENTS -> if (value == AUTO_MARKER) auto = true else start(value)
                    name in START_OF_TAB -> tab = ArrayList()
                    name == "start_of_chorus" || name == "soc" -> start(value.ifEmpty { null }, chorus = true)
                    name == "end_of_chorus" || name == "eoc" -> start(null)
                    (name == "define" || name == "chord") && value.isNotEmpty() -> defines += value
                }
                continue
            }
            if (line.startsWith("#")) continue
            section.lines += line(line, ::chord)
        }
        tab?.let { section.lines += Tab(it.toList()) }
        val kept = ArrayList<Section>()
        for (s in sections) {
            var from = 0
            var to = s.lines.size
            while (from < to && s.lines[from] == Blank) from++
            while (to > from && s.lines[to - 1] == Blank) to--
            val lines = s.lines.subList(from, to).toList()
            if (lines.isNotEmpty() || !s.label.isNullOrEmpty()) kept += Section(s.label, s.chorus, lines)
        }
        return Sheet(title, artist, key, capo, auto, chords.toList(), kept.toList(), defines.toList())
    }

    private val END_OF_TAB = setOf("end_of_tab", "eot")
    private val START_OF_TAB = setOf("start_of_tab", "sot")

    /** `int(value) if _FRET.fullmatch(value) and int(value) > 0 else None`, an Int (past Int's range: none). */
    private fun fret(value: String): Int? {
        if (PyRe.fullmatch(FRET, value) == null) return null
        val n = BigInteger(value)
        return if (n.signum() > 0 && n.bitLength() < 32) n.toInt() else null
    }

    /** directive: a directive line as [parse] reads it, its name in lower case and its value, its escapes undone
     * (("comment", "Verse 1") for "{comment: Verse 1}"); null for any other line. */
    fun directive(line: String): Pair<String, String>? {
        val d = PyRe.fullmatch(DIRECTIVE, line.replace(ESCAPED_BACKSLASH, "\\")) ?: return null
        return Py.asciiLower(d.groupValues[1]) to Py.strip(d.groups[2]?.value ?: "")
    }

    /** sheet._line: one line of a section. */
    private fun line(line: String, chord: (String) -> Int): Line {
        if (Str.blank(line)) return Blank
        val pieces = PyRe.split(TOKEN, line).map { it!! } // text, token, text, token, ..., text
        if (pieces.size == 1) return Text(Str.rstrip(line))
        val parts = ArrayList<Pair<Item?, String>>()
        if (pieces[0].isNotEmpty()) parts += null to pieces[0]
        var k = 1
        while (k + 1 < pieces.size) {
            val token = pieces[k]
            val after = pieces[k + 1]
            val item: Item = if (token.startsWith("*")) Item.Mark(Py.strip(token.substring(1)))
                             else Item.Chord(chord(Py.strip(token)))
            parts += item to after
            k += 2
        }
        if (parts.all { Str.blank(it.second) }) return ChordRow(parts.mapNotNull { it.first })
        return Lyrics(parts.toList())
    }

    // --- the preamble ----------------------------------------------------------------------------------------------

    /** written: a line as the sheet writes it, its chords and marks among its words: "Cadd9 (x32033)". */
    fun written(line: Line, names: List<String>): String = when (line) {
        is Text -> line.text
        is ChordRow -> line.items.joinToString(" ") { name(it, names) }
        is Lyrics -> line.parts.joinToString("") { (c, text) -> (c?.let { name(it, names) } ?: "") + text }
        else -> ""
    }

    private fun name(item: Item, names: List<String>): String = when (item) {
        is Item.Chord -> names[item.index]
        is Item.Mark -> item.text
    }

    private fun played(line: Line, names: List<String>): Boolean =
        line !is Text && line != Blank && Voicings.chordLegend(written(line, names)).isEmpty()

    /** is_legend: whether a line of chords is a chord legend's (chords given with their fingerings, "[Am]
     * [*x02210]", Voicings.chordLegend), which names the tab's shapes as it writes them and plays nothing. */
    fun isLegend(line: Line, names: List<String>): Boolean =
        (line is Lyrics || line is ChordRow) && Voicings.chordLegend(written(line, names)).isNotEmpty()

    /** is_legend_line: [isLegend] for a line of a ChordPro text that [parse] reads as a line of the song (no
     * directive, `#` comment or line of a tab). */
    fun isLegendLine(text: String): Boolean {
        val names = ArrayList<String>()
        val read = line(text.replace(ESCAPED_BACKSLASH, "\\")) { names += it; names.size - 1 }
        return isLegend(read, names)
    }

    /**
     * preamble_section: what a tab says before its first section (its tabber's notes, a link, a chord legend), or
     * null: an unlabelled first section, before another, up to its first tab, with nothing played in it. Its lines are
     * text and chords given with their fingerings; chords alone there are the song's intro and words sung there its
     * first verse. The viewer's rule, and the PDF's.
     */
    fun preambleSection(sheet: Sheet): Section? {
        val first = if (sheet.sections.size > 1) sheet.sections[0] else return null
        if (!first.label.isNullOrEmpty() || first.chorus) return null
        val lines = ArrayList<Line>()
        for (line in first.lines) {
            if (line is Tab) break
            if (played(line, sheet.chords)) return null
            lines += line
        }
        while (lines.isNotEmpty() && lines.last() == Blank) lines.removeAt(lines.size - 1)
        return if (lines.isNotEmpty()) Section(null, lines = lines.toList()) else null
    }

    /** split_preamble: the preamble of a ChordPro text's [lines] by the viewer's rule ([preambleSection]): what it
     * holds, and its end, the index of the first line after it (0 when there is none). */
    fun splitPreamble(lines: List<String>): Preamble {
        val sheet = parse(lines.joinToString("\n"))
        val section = preambleSection(sheet) ?: return Preamble(emptyList(), emptyList(), emptyList(), null, null, 0)
        val notes = ArrayList<String>()
        val legend = ArrayList<Pair<Chord, Position>>()
        for (line in section.lines) {
            val text = written(line, sheet.chords)
            val found = Voicings.chordLegend(text)
            if (found.isNotEmpty()) legend += found
            else if (line is Text) notes += Py.strip(text)
        }
        var tuning: String? = null
        var capo: String? = null
        for (note in notes) {
            if (tuning == null) tuning = tuning(note)
            if (capo == null) {
                val m = PyRe.search(CAPO, note)
                if (m != null) capo = "Capo ${PyInt.parse(m.groupValues[1])}"
            }
        }
        return Preamble(notes.toList(), legend.toList(), emptyList(), tuning, capo, endOf(lines, section.lines.size))
    }

    /** _tuning: the tuning a note names (_TUNING_NAME), else the one after its "Tuning:" label, or null: a note that
     * only talks about the tuning names none, and standard tuning goes unsaid. */
    internal fun tuning(note: String): String? {
        PyRe.search(TUNING_NAME, note)?.let { return it.value }
        val label = PyRe.search(TUNING_LABEL, note) ?: return null
        var value = Py.strip(Str.rstrip(Py.strip(label.groupValues[1]), "."))
        if (value.endsWith(")") && Str.count(value, ")") > Str.count(value, "(")) {
            value = Py.strip(value.substring(0, value.length - 1))
        }
        val letters = PyRe.sub(NOT_A_LETTER, PyUnicode.lower(value)) { "" }.replace("tuning", "")
        return if (value.isNotEmpty() && letters !in STANDARD) value else null
    }

    /** _end_of: the index after the [count]-th content line of the text (a line the parser keeps in a section: not a
     * directive, a `#` comment, or inside a tab), and the blank lines after it. */
    private fun endOf(lines: List<String>, count: Int): Int {
        var seen = 0
        var tab = false
        for ((i, raw) in lines.withIndex()) {
            val line = raw.replace(ESCAPED_BACKSLASH, "\\")
            if (tab) {
                val d = PyRe.fullmatch(DIRECTIVE, line)
                tab = !(d != null && Py.asciiLower(d.groupValues[1]) in END_OF_TAB)
            } else {
                val d = PyRe.fullmatch(DIRECTIVE, line)
                if (d != null) tab = Py.asciiLower(d.groupValues[1]) in START_OF_TAB
                else if (!line.startsWith("#") && (seen != 0 || !Str.blank(line))) seen++
            }
            if (seen == count && !tab) {
                var end = i + 1
                while (end < lines.size && Str.blank(lines[end])) end++
                return end
            }
        }
        return lines.size
    }
}
