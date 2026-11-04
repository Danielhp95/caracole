package io.github.danielhp95.caracole.viewer.harptab

import kotlinx.serialization.json.JsonElement

/** harptab.Symbol: a mark of a notation, its text as tabs write it, what it means (MEANINGS), where it is written
 * (PLACES) and a bend's semitones. */
data class Symbol(val text: String, val means: String, val at: String, val count: Int = 1)

/** harptab.Notation: how a tab writes its holes; [bare] the breath of a hole with no breath mark, [fold] whether its
 * letters read in either case. */
data class Notation(val name: String, val symbols: List<Symbol>, val bare: String? = "blow", val fold: Boolean = false)

/** A symbol a tab used, as written ([Reading.used]'s keys). */
data class Used(val text: String, val means: String, val at: String, val count: Int)

/** harptab.Reading: a tab read under a notation, its P ([explained]), T ([playable]) and score (Q, the legend's
 * weight), its margin over the best notation that reads it differently ([runner]), and the symbols it used. */
data class Reading(val notation: Notation, val source: String, val explained: Double, val playable: Double,
                   val score: Double, val margin: Double, val runner: String?, val confident: Boolean,
                   val used: List<Pair<Used, Int>> = emptyList())

/** harptab.Hole. */
data class Hole(val hole: Int, val breath: String, val bend: Int = 0, val over: Boolean = false,
                val button: Boolean = false)

/** harptab.Group: holes read together, of a [kind], at the column its text starts at. */
data class Group(val holes: List<Hole>, val kind: String, val col: Int, val digit: Int, val text: String,
                 val hold: Boolean = false, val effects: List<String> = emptyList(), val join: Boolean = false)

/** An item of a tab's section (harptab.Item): a row, the tabber's words, prose, a gap. */
sealed interface TabItem

/** harptab.Row: a line of holes with its words. */
data class Row(val groups: List<Group>, val lyric: String?, val label: String? = null,
               val unknown: List<String> = emptyList(), val parts: List<Pair<List<Group>, String>> = emptyList(),
               val placement: Map<String, Int> = emptyMap(), val text: String = "", val line: Int = -1,
               val confidence: Double = 1.0, val trusted: Boolean = true, val above: Boolean = false) : TabItem

/** harptab.Words. */
data class Words(val lines: List<String>) : TabItem

/** harptab.Prose. */
data class Prose(val text: String) : TabItem

/** harptab.Gap. */
data object Gap : TabItem

/** harptab.Legend: a tab's legend, its lines, the symbols it names and where. */
data class Legend(val lines: List<String>, val symbols: List<Symbol>, val at: List<Int> = emptyList())

/** harptab.Section. */
data class TabSection(val label: String?, val items: List<TabItem> = emptyList())

/** harptab.Tab: a harmonica tab read and laid out (lane harptab-layout). */
data class Tab(val notes: List<String>, val sections: List<TabSection>, val reading: Reading, val key: String?,
               val missed: List<String>, val chromatic: Boolean, val legend: Legend? = null, val harp: String? = null)

/** viewer/harptab.py: a harmonica tab read under each notation (lane harptab-read) and laid out (lane
 * harptab-layout). */
object HarpTabs {
    fun parse(body: String, harp: String? = null, notation: Notation? = null): Tab = TODO("lane harptab-layout")
    fun readings(body: String, harp: String? = null): List<Reading> = TODO("lane harptab-read")
    /** harptab.check_spec: refuses (IllegalArgumentException, Python's words) a pin that can't be one. */
    fun checkSpec(spec: JsonElement): Unit = TODO("lane harptab-read")
    fun specOf(r: Reading): JsonElement = TODO("lane harptab-read")
}
