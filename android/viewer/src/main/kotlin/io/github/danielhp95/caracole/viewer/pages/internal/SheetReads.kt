package io.github.danielhp95.caracole.viewer.pages.internal

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Line
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.Text
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory

/**
 * Phase A, waiting on sheet-keys: what the page reads of a sheet that the skeleton's viewer.sheet declares no
 * signature for, each named as sheet-keys' branch names it (`Sheets.written`, `Sheets.isLegend`, `SheetView.peek`,
 * `.chordsIn`, `.played`, `.chords`, `.songKey`), so that Phase B calls those and deletes this file. The first are
 * sheet.py's and page.py's few lines, which the page's frame needs to be checked now (vectors/viewer/pages_parts.jsonl);
 * the key's words are sheet-keys' data (page._SOURCES), so [songKey] waits for it.
 */
internal object SheetReads {
    /** sheet.written: a line as the sheet writes it, its chords and marks among its words: "Cadd9 (x32033)". */
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

    /** sheet.is_legend: whether a line of chords is a chord legend's (chords given with their fingerings). */
    fun isLegend(line: Line, names: List<String>): Boolean =
        (line is Lyrics || line is ChordRow) && Voicings.chordLegend(written(line, names)).isNotEmpty()

    /** page._peek: the first two lines of the notes before the song, chords and all, for notes of more than two;
     * none for fewer, which aren't folded. */
    fun peek(section: Section, names: List<String>): List<String> {
        val lines = section.lines.filter { it != Blank }
        return if (lines.size > 2) lines.take(2).map { Py.strip(written(it, names)) } else emptyList()
    }

    /** page._chords_in: a section's chords in the order they are played, repeats and all. */
    fun chordsIn(section: Section): List<Int> {
        val order = ArrayList<Int>()
        for (line in section.lines) {
            when (line) {
                is Lyrics -> line.parts.forEach { (c, _) -> if (c is Item.Chord) order += c.index }
                is ChordRow -> line.items.forEach { if (it is Item.Chord) order += it.index }
                else -> {}
            }
        }
        return order
    }

    /** page._played: the sheet's chords in the order they are played. */
    fun played(s: Sheet): List<Int> = s.sections.flatMap(::chordsIn)

    /** The sheet's chords as its page reads them: `parse_chord(name, strict=False)` of each. */
    fun chords(s: Sheet): List<Chord?> = s.chords.map { Theory.parseChord(it, strict = false) }

    /** page._song_key: the key of the sheet's shapes and where it came from in words; waiting on sheet-keys'
     * `SheetView.songKey` and its data's page._SOURCES. */
    @Suppress("UNUSED_PARAMETER")
    fun songKey(s: Sheet, chords: List<Chord?>, key: String?, source: String?): Pair<Key?, String?> =
        TODO("lane sheet-keys")
}
