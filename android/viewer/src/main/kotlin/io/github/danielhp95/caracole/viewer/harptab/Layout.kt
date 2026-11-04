package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlin.math.abs

/**
 * A tab laid out, as harptab.py's `parse` lays it out (its docstring's "The lines" and "Readable or not"): each line's
 * kind (`_line_kinds`), the lines laid out one after another into the tabber's notes and the sections (`_Layout`,
 * `_lay_out` and its cases), a row's words under it or, in a tab that writes them so, above it (`_above`, `_lyric`), a
 * section's name (`_is_label`, `_label_text`), the tabber's prose (`_is_prose`), the harp's key the words name
 * (`named_key`), the lines shown as written (`_missed`). A row's holes are placed over its words by [Align].
 */
internal object Layout {
    private val B = HarptabData

    /** `\[[^\]]+\]|\([^)]+\)`: a section's name in brackets. */
    private val BRACKETED: Regex by lazy { PyRegex.compile("""\[[^\]]+\]|\([^)]+\)""") }

    /** harptab.parse: the tab [body] read and laid out; [harp] the page's chip, [notation] one to read it by. */
    fun parse(body: String, harp: String?, notation: Notation?): Tab {
        val prepared = Weighing.prepared(body, harp)
        val (reading, scans) = Weighing.read(prepared.read, prepared.chip, notation, prepared.legends)
        val kinds = lineKinds(prepared.lines, scans, prepared.inLegend)
        val (notes, sections) = laidOut(prepared.lines, kinds, scans, prepared.legends, prepared.chip)
        val prose = notes + sections.flatMap { s -> s.items.filterIsInstance<Prose>().map { it.text } }
        val rows = sections.flatMap { s -> s.items.filterIsInstance<Row>() }
        val chromatic = prepared.chip == "Chromatic" ||
            rows.any { r -> r.trusted && r.groups.any { g -> g.holes.any { it.button } } }
        return Tab(notes, sections, reading, namedKey(prose), missed(prepared.lines, kinds, rows), chromatic,
                   oneLegend(prepared.legends), prepared.chip)
    }

    /** harptab._line_kinds: what each line is: "legend", "blank", "holes" (a row), "missed" or "text". */
    fun lineKinds(lines: List<String>, scans: List<Scan>, inLegend: Set<Int>): List<String> = lines.indices.map { n ->
        when {
            n in inLegend -> "legend"
            Py.strip(lines[n]).isEmpty() -> "blank"
            scans[n].isRow -> "holes"
            scans[n].missed -> "missed"
            else -> "text"
        }
    }

    /** A section while it is laid out (harptab.Section). */
    private class Sec(val label: String?) {
        val items = ArrayList<TabItem>()
    }

    /** harptab._Layout: the tab's lines laid out into sections as `parse` goes down them, and what is laid out so far. */
    private class Work(val lines: List<String>, val kinds: List<String>, val scans: List<Scan>, val legends: List<Legend>,
                       val chip: String?, val above: Boolean) {
        val notes = ArrayList<String>()
        val sections = arrayListOf(Sec(null))
        var seenRow = false
        val block = ArrayList<String>()
        var lastText = -1

        /** The block of text laid out: before the first row, the tabber's notes; after it, their prose or words sung
         * to the same tune. */
        fun flush() {
            if (block.isEmpty()) return
            when {
                !seenRow -> block.mapTo(notes) { Py.strip(it) }
                isProse(block) -> block.mapTo(sections.last().items) { Prose(Py.strip(it)) }
                else -> sections.last().items += Words(block.map { HarpTabText.rstrip(it) })
            }
            block.clear()
        }
    }

    /** harptab._laid_out: the tabber's notes before the first row, and the sections. */
    private fun laidOut(lines: List<String>, kinds: List<String>, scans: List<Scan>, legends: List<Legend>,
                        chip: String?): Pair<List<String>, List<TabSection>> {
        val work = Work(lines, kinds, scans, legends, chip, above(lines, kinds, scans))
        var i = 0
        while (i < lines.size) i = layOut(work, i)
        work.flush()
        return work.notes to trimmed(work.sections)
    }

    /** harptab._lay_out: the line [i] laid out, by what it is, and the place of the next line to lay out. */
    private fun layOut(work: Work, i: Int): Int {
        val kind = work.kinds[i]
        return when {
            kind == "blank" -> blankLine(work, i)
            kind == "legend" -> legendLines(work, i)
            kind == "holes" || (kind == "missed" && work.seenRow) -> rowLine(work, i)
            else -> textLine(work, i)
        }
    }

    private fun blankLine(work: Work, i: Int): Int {
        work.flush()
        val items = work.sections.last().items
        if (work.seenRow && items.isNotEmpty() && items.last() !is Gap) items += Gap
        return i + 1
    }

    private fun legendLines(work: Work, i: Int): Int {
        work.flush()
        val here = work.legends.first { i in it.at }
        work.sections.last().items += here
        return here.at.last() + 1
    }

    /** harptab._row_line: the line [i] as a row, with its words and its holes over them; a label it leads with that
     * names a section starts one. */
    private fun rowLine(work: Work, i: Int): Int {
        val found = work.scans[i]
        val lyric = lyric(work, i)
        work.flush()
        var label = found.label
        if (!label.isNullOrEmpty() && isLabel("$label:")) {
            work.sections += Sec(label)
            label = null
        }
        val confidence = rowConfidence(found, work.chip)
        val row = Row(found.groups.toList(), lyric, label, found.unknown.toList(), text = work.lines[i], line = i,
                      confidence = confidence, trusted = work.kinds[i] == "holes" && confidence >= B.ROW_TRUST,
                      above = work.above && lyric != null)
        work.sections.last().items += Align.align(row)
        work.seenRow = true
        return i + (if (lyric != null && !work.above) 2 else 1)
    }

    /** harptab._lyric: the words of the row at [i], the line of text under it, or above it in a tab that writes them
     * so (taken from the block); null for a row played alone. */
    private fun lyric(work: Work, i: Int): String? {
        val lines = work.lines
        val scans = work.scans
        if (work.above) {
            if (work.lastText == i - 1 && work.block.isNotEmpty() && sung(lines[i - 1], scans[i - 1])) {
                work.block.removeAt(work.block.size - 1)
                return lines[i - 1]
            }
            return null
        }
        if (i + 1 < lines.size && work.kinds[i + 1] == "text" && sung(lines[i + 1], scans[i + 1])) return lines[i + 1]
        return null
    }

    /** harptab._text_line: a section's name starts a section; else the line joins the block. */
    private fun textLine(work: Work, i: Int): Int {
        val kinds = work.kinds
        val line = work.lines[i]
        val beside = listOf(i - 1, i + 1).any { j -> j in kinds.indices && (kinds[j] == "holes" || kinds[j] == "missed") }
        if (isLabel(line, beside) && (work.seenRow || B.LABEL_WORDS.find(line) != null)) {
            work.flush()
            work.sections += Sec(labelText(line))
        } else {
            work.block += if (work.seenRow) line else Py.strip(line)
            work.lastText = i
        }
        return i + 1
    }

    /** harptab._trimmed: the sections without the gaps at their ends, and without those left with nothing and no
     * name. */
    private fun trimmed(sections: List<Sec>): List<TabSection> {
        for (s in sections) {
            while (s.items.isNotEmpty() && s.items.last() is Gap) s.items.removeAt(s.items.size - 1)
            while (s.items.isNotEmpty() && s.items.first() is Gap) s.items.removeAt(0)
        }
        return sections.filter { it.items.isNotEmpty() || !it.label.isNullOrEmpty() }.map { TabSection(it.label, it.items.toList()) }
    }

    /** harptab._missed: the lines that hold holes but are shown as written. */
    private fun missed(lines: List<String>, kinds: List<String>, rows: List<Row>): List<String> = kinds.indices
        .filter { n -> kinds[n] == "missed" || (kinds[n] == "holes" && rows.none { it.line == n && it.trusted }) }
        .map { Py.strip(lines[it]) }

    /** harptab._one_legend: the tab's legends as one; null for a tab with none. */
    private fun oneLegend(legends: List<Legend>): Legend? = if (legends.isEmpty()) null else
        Legend(legends.flatMap { it.lines }, legends.flatMap { it.symbols }, legends.flatMap { it.at })

    /** harptab._row_confidence: a row's own P × T. */
    private fun rowConfidence(found: Scan, chip: String?): Double {
        val holes = found.holes.flatMap { it.holes }
        return found.explained * (if (holes.isNotEmpty()) holes.count { Weighing.playable(it, chip) }.toDouble() / holes.size else 0.0)
    }

    /** harptab._is_prose: whether a block of text after the first row is the tabber's, not words sung to the tune. */
    fun isProse(block: List<String>): Boolean =
        block.size == 1 || block.any { B.URL.find(it) != null } || B.INSTRUCTION.find(block[0]) != null

    /** harptab.named_key: the harp's key the tabber's words name, the first they name, or null. */
    fun namedKey(lines: List<String>): String? {
        for (line in lines) for (pattern in B.KEY_PATTERNS) {
            val m = pattern.find(line) ?: continue
            return m.groups[1]!!.value.replace("♭", "b").replace("♯", "#")
        }
        return null
    }

    /** harptab._syllables: a line's runs of vowels, accents folded. */
    fun syllables(line: String): Int =
        PyRe.finditer(B.VOWEL_RUN, PyUnicode.casefold(HarpTabText.foldAccents(line))).count()

    /** harptab._above: whether a tab writes each row's words above it: those above fit its rows, syllables to holes,
     * better than those below by ABOVE_LEAD and ABOVE_SHARE of its rows at least. */
    fun above(lines: List<String>, kinds: List<String>, scans: List<Scan>): Boolean {
        fun fit(j: Int, holes: Int): Double {
            if (!(j in lines.indices && kinds[j] == "text" && sung(lines[j], scans[j]))) return 0.0
            val tokens = Py.split(lines[j])
            val worded = tokens.count { t -> t.codePoints().filter { PyUnicode.isAlpha(it) }.count() >= 2 }
            if (2 * worded < tokens.size) return 0.0
            val found = syllables(lines[j])
            val most = maxOf(found, holes)
            return if (most != 0) 1 - abs(found - holes).toDouble() / most else 0.0
        }
        val rows = kinds.indices.filter { kinds[it] == "holes" }
        val up = Py.fsum(rows.map { fit(it - 1, scans[it].holes.size) })
        val down = Py.fsum(rows.map { fit(it + 1, scans[it].holes.size) })
        return up - down >= maxOf(B.ABOVE_LEAD, B.ABOVE_SHARE * rows.size)
    }

    /** harptab._sung: whether a line of text by a row may be its words. */
    private fun sung(line: String, found: Scan): Boolean =
        !isLabel(line, besideRow = true) && B.URL.find(line) == null && !found.holey

    /** harptab._is_label: whether a line names a section; beside a row, one that starts as one but goes on in words
     * is sung. */
    fun isLabel(line: String, besideRow: Boolean = false): Boolean {
        val words = Py.split(line)
        val stripped = Py.strip(line)
        if (words.isEmpty() || Py.len(stripped) > 32 || B.URL.find(stripped) != null) return false
        if (BRACKETED.matchEntire(stripped) != null && words.size <= 4) return true
        if (B.LABEL_WORDS.find(stripped) != null && words.size <= 4 &&
            (!besideRow || ":" in stripped || Py.strip(PyRe.sub(B.LABEL_REST, stripped) { "" }).isEmpty())) return true
        val last = stripped.codePointBefore(stripped.length)
        return words.size <= 3 && (last == ':'.code || last == '-'.code) && !stripped.endsWith("--")
    }

    /** harptab._label_text: a section's name without its brackets and its colon. */
    fun labelText(line: String): String {
        val stripped = Py.strip(line)
        return Py.strip(PyText.strip(stripped, "[]()").trimEnd { it in ":-;. " }).ifEmpty { stripped }
    }
}
