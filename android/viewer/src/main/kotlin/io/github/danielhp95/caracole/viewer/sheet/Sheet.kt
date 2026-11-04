package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.JsonObject

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

/** sheet.Section. */
data class Section(val label: String?, val chorus: Boolean = false, val lines: List<Line> = emptyList())

/** sheet.Sheet: a ChordPro sheet as caracole writes it, read; [chords] as written, each once, in order of
 * appearance; [defines] each `{define}` and `{chord}` as written after its colon (lane sheet-keys). */
data class Sheet(val title: String = "", val artist: String = "", val key: String? = null, val capo: Int? = null,
                 val auto: Boolean = false, val chords: List<String> = emptyList(),
                 val sections: List<Section> = emptyList(), val defines: List<String> = emptyList())

/** viewer/sheet.py (lane sheet-keys). */
object Sheets {
    fun parse(cho: String): Sheet = TODO("lane sheet-keys")
}

/** The reading functions of viewer/page.py that hold no HTML, below the page (lane sheet-keys): Python's page↔version
 * and page↔harpfit cycles end here. */
object SheetView {
    /** page._shown: the notes before the song (its preamble section, or null), and the sections shown. */
    fun shown(s: Sheet): Pair<Section?, List<Section>> = TODO("lane sheet-keys")
    fun drawnLines(s: Sheet): List<String> = TODO("lane sheet-keys")
    fun writtenTexts(s: Sheet): List<String> = TODO("lane sheet-keys")
    fun places(s: Sheet): List<Pair<Int, Int>> = TODO("lane sheet-keys")
    fun viewerKey(cho: String, key: String? = null, keySource: String? = null): Key? = TODO("lane sheet-keys")
    fun shapesOf(s: Sheet): JsonObject = TODO("lane sheet-keys")
}
