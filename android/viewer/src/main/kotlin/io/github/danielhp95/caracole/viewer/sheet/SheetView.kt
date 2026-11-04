package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.shapes.Position
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonObject

/**
 * The reading functions of viewer/page.py that hold no HTML, below the page: what a sheet's page shows of it (its
 * notes before the song, its sections, each line's words, each chord's place), the key it names, and the shapes it
 * gives its chords. Python's page↔version and page↔harpfit cycles end here.
 */
object SheetView {
    private val P get() = SheetData.page

    /** page._SOURCES: where a key came from (keys.SongKey.source), in words for the page. */
    val SOURCES: Map<String, String> by lazy { P.strings("_SOURCES") }

    /** page._OF_THE_SHAPES: the sources whose key is the key of the chords as the sheet writes them. */
    private val OF_THE_SHAPES: Set<String> by lazy { P.list("_OF_THE_SHAPES").toSet() }

    /** _shown: the sheet as its page shows it: the notes before the song ([Sheets.preambleSection]), or null, and
     * the song's sections, each a `section.sec` on the page (what follows the notes in their section, a riff and on,
     * stays a section of the song). */
    fun shown(s: Sheet): Pair<Section?, List<Section>> {
        val sections = ArrayList(s.sections)
        val pre = Sheets.preambleSection(s)
        if (pre != null) {
            var rest = sections[0].lines.subList(pre.lines.size, sections[0].lines.size)
            while (rest.isNotEmpty() && rest[0] == Blank) rest = rest.subList(1, rest.size)
            sections.removeAt(0)
            if (rest.isNotEmpty()) sections.add(0, Section(null, lines = rest.toList()))
        }
        return pre to sections.toList()
    }

    /** _drawn_lines: the text of each line of the song's sections as the page draws one (a `p.l`: a sung line's
     * words, none for a line of chords alone, a line of text's), in the page's order: the lines the data's `pinyin`
     * reads. The notes before the song are none of them. */
    fun drawnLines(s: Sheet): List<String> =
        shown(s).second.flatMap { section ->
            section.lines.filter { it is Lyrics || it is ChordRow || it is Text }.map(::wordsOf)
        }

    /** _words_of: a line's words as its page writes them (a `p.l`'s, its chords left out; a tab whole), "" for a
     * line of chords alone or a blank one. */
    fun wordsOf(line: Line): String = when (line) {
        is Lyrics -> line.parts.joinToString("") { it.second }
        is Text -> line.text
        is Tab -> line.lines.joinToString("\n")
        else -> ""
    }

    /** _written_texts: every text the sheet's page writes in its words, which the data's `hanzi` gives in either
     * script: the notes before the song (each line of their peek, and each line), then each section's label and each
     * line's words, a tab's whole. */
    fun writtenTexts(s: Sheet): List<String> {
        val (pre, sections) = shown(s)
        val out = ArrayList<String>()
        if (pre != null) {
            out += peek(pre, s.chords)
            out += pre.lines.map(::wordsOf)
        }
        for (section in sections) {
            if (!section.label.isNullOrEmpty()) out += section.label
            out += section.lines.map(::wordsOf)
        }
        return out
    }

    /** _peek: the lines the folded notes before the song show in their summary: their first two, chords and all,
     * for notes of more than two lines; none for fewer, which aren't folded. */
    fun peek(section: Section, names: List<String>): List<String> {
        val lines = section.lines.filter { it != Blank }
        return if (lines.size > 2) lines.take(2).map { Py.strip(Sheets.written(it, names)) } else emptyList()
    }

    /** _chords_in: a section's chords in the order they are played, repeats and all. */
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

    /** _played: the sheet's chords in the order they are played, repeats and all. */
    fun played(s: Sheet): List<Int> = s.sections.flatMap(::chordsIn)

    /** _places: each chord's place on the page, in the page's order (the script's `#sheet .c`): (its index, its
     * section among the song's `section.sec`, -1 in the notes before the song). */
    fun places(s: Sheet): List<Pair<Int, Int>> {
        val (pre, sections) = shown(s)
        val places = ArrayList<Pair<Int, Int>>()
        if (pre != null) chordsIn(pre).forEach { places += it to -1 }
        for ((n, section) in sections.withIndex()) chordsIn(section).forEach { places += it to n }
        return places
    }

    /** The sheet's chords as its page reads them: `parse_chord(name, strict=False)` of each. */
    fun chords(s: Sheet): List<Chord?> = s.chords.map { Theory.parseChord(it, strict = false) }

    /** viewer_key: the key of a ChordPro sheet's shapes as its page names it (given [key] and [keySource]), for what
     * says the same beside the page: the PDF's key line. */
    fun viewerKey(cho: String, key: String? = null, keySource: String? = null): Key? {
        val s = Sheets.parse(cho)
        return songKey(s, chords(s), key, keySource).first
    }

    /**
     * _song_key: the key of the shapes the sheet's chords are, and where it came from in words. A key named for a
     * sheet with a capo may be the one the song sounds in (Theory.shapesKey); one the chords gave (`chords`,
     * `audio`) is their shapes', whatever the capo. A letter alone, the sheet's `{key}` or one from no source keys.py
     * names, is its parallel minor where the chords say so (Theory.namedKey); keys.py has read a tab's so already.
     */
    fun songKey(s: Sheet, chords: List<Chord?>, key: String?, source: String?): Pair<Key?, String?> {
        val played = played(s).mapNotNull { chords[it] }
        val capo = s.capo ?: 0
        val found = Theory.parseKey(key)
        if (found != null) {
            if (source != null && source in OF_THE_SHAPES) return found to origin(source)
            val named = if (source == null || source !in SOURCES) Theory.namedKey(key, capo, played) ?: found else found
            return Theory.shapesKey(named, capo, played) to origin(source)
        }
        val named = Theory.namedKey(s.key, capo, played)
        if (named != null) return Theory.shapesKey(named, capo, played) to "from the sheet"
        val estimated = Theory.estimateKey(played)
        return estimated to (if (estimated != null) "estimated from the chords" else null)
    }

    /** _origin: where a key came from, in words: one of [SOURCES]' words, else "from <source>" (its first 40
     * characters, its spaces made one), "from info.json" for none. */
    fun origin(source: String?): String {
        if (source == null) return "from info.json"
        val words = Py.slice(Py.split(source).joinToString(" "), 0, 40)
        return SOURCES[PyUnicode.lower(words)] ?: "from $words"
    }

    /** shapes_of: the shapes the sheet's page shows for its chords (its data's `shapes`: Voicings.sheetShapes, by
     * Voicings.shapeKey), for what shows the same beside the page: the PDF's chord diagrams. */
    fun shapesOf(s: Sheet): JsonObject = Voicings.sheetShapes(givenShapes(s))

    /** _given_shapes: the fingerings the sheet gives its chords, in order: its `{define}`s, then its chord legend's
     * lines, wherever they are (a legend's line in a tab too). */
    fun givenShapes(s: Sheet): List<Pair<Chord, Position>> {
        val given = ArrayList<Pair<Chord, Position>>()
        s.defines.forEach { value -> Voicings.parseDefine(value)?.let { given += it } }
        for (section in s.sections) {
            for (line in section.lines) {
                when (line) {
                    is Tab -> line.lines.forEach { given += Voicings.chordLegend(it) }
                    Blank -> {}
                    else -> given += Voicings.chordLegend(Sheets.written(line, s.chords))
                }
            }
        }
        return given
    }
}
