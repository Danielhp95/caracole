package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonElement

/** harptab.Symbol: a mark of a notation, its text as tabs write it, what it means (MEANINGS), where it is written
 * (PLACES: before the hole, after it, around it as `()`, between two holes; a legend's "bare" for a hole written
 * alone, "" where the tab writes it) and a bend's semitones. */
data class Symbol(val text: String, val means: String, val at: String, val count: Int = 1)

/** harptab.Notation: how a tab writes its holes; [bare] the breath of a hole with no breath mark ("blow", "draw", or
 * null where a hole needs one), [fold] whether its letters read in either case. Each compiles into its tokenizer
 * ([HarpTabs.scan]). */
data class Notation(val name: String, val symbols: List<Symbol>, val bare: String? = "blow", val fold: Boolean = false) {
    /** Notation.changed: this notation with [symbols] in place of its own written the same way in the same place
     * (the others added), as a legend or the owner changes it; [bare] `""` keeps its own, [name] null or empty its
     * own. */
    fun changed(symbols: List<Symbol> = emptyList(), name: String? = null, bare: String? = "",
                fold: Boolean? = null): Notation {
        val keys = symbols.map { key(it.text) to it.at }.toHashSet()
        val kept = this.symbols.filter { (key(it.text) to it.at) !in keys }
        return Notation(name?.takeIf { it.isNotEmpty() } ?: this.name, kept + symbols,
                        if (bare == "") this.bare else bare, fold ?: this.fold)
    }

    internal fun key(text: String): String = if (fold) PyUnicode.casefold(text) else text

    /** Notation.meaning: the symbol it reads [text] written [at] as, or null. */
    fun meaning(text: String, at: String): Symbol? {
        val key = key(text)
        return symbols.firstOrNull { it.at == at && key(it.text) == key }
    }
}

/** A symbol a tab used, as written: `Scan.used`'s and [Reading.used]'s keys, `(text, means, at, count)`, a hole
 * written alone `("", bare, "bare", 1)`. */
data class Used(val text: String, val means: String, val at: String, val count: Int)

/** harptab.Reading: a tab read under a notation, where that came from ([source]: "guessed", "legend", "pinned"), its
 * P ([explained]), T ([playable]) and score (Q, weighed by the legend), its margin over the best notation that reads
 * it differently ([runner]), whether it is [confident] enough to draw, and the symbols it used ([used], sorted as
 * Python sorts them). */
data class Reading(val notation: Notation, val source: String, val explained: Double, val playable: Double,
                   val score: Double, val margin: Double, val runner: String?, val confident: Boolean,
                   val used: List<Pair<Used, Int>> = emptyList()) {
    val q: Double get() = explained * playable

    /** Reading.standard: caracole guessed harptabs.com's own key, and the tab used nothing else. */
    val standard: Boolean get() = Weighing.standard(this)

    /** Reading.said: "b blow · d draw · * bend · (w) wah". */
    fun said(): String = symbols().joinToString(" · ") { (text, word) -> "$text $word" }

    /** Reading.symbols: the symbols the tab was read by, each as it writes it most, and what it means in words. */
    fun symbols(): List<Pair<String, String>> = Weighing.said(LinkedHashMap<Used, Int>().also { m ->
        for ((k, v) in used) m[k] = v
    })
}

/** harptab.Hole: one hole played, its number (1 to 10), breath ("blow" or "draw"), the semitones it is bent down,
 * whether it is overblown (or overdrawn), whether a chromatic's slide is pressed. */
data class Hole(val hole: Int, val breath: String, val bend: Int = 0, val over: Boolean = false,
                val button: Boolean = false) {
    /** Hole.label: as the page writes it: "4", "−4", "−3′′", "6°". */
    fun label(): String = (if (breath == "draw") "−" else "") + hole + "′".repeat(bend) + (if (over) "°" else "") +
        (if (button) "<" else "")
}

/** harptab.Group: what one place of a row plays, a hole (kind "note") or holes together ("chord", "shake",
 * "split"), or what its notation couldn't read ("unread") or the tabber's words ("words"), both with no holes; the
 * column its text starts at and that of its first hole's number, in code points as Python counts them (tabs
 * expanded), its text as written, whether it is held, its other effects, whether it runs into the next. */
data class Group(val holes: List<Hole>, val kind: String, val col: Int, val digit: Int, val text: String,
                 val hold: Boolean = false, val effects: List<String> = emptyList(), val join: Boolean = false) {
    /** Group.end: the column after its text, in code points. */
    val end: Int get() = col + Py.len(text)

    fun label(): String {
        if (holes.isEmpty() && (kind == "unread" || kind == "words")) return text
        val inner = holes.joinToString(" ") { it.label() }
        return when (kind) {
            "note" -> inner
            "chord" -> "($inner)"
            "shake" -> "{$inner}"
            "split" -> "[$inner]"
            else -> throw NoSuchElementException(kind)
        }
    }
}

/**
 * harptab.Scan: a line as holes, as one notation reads it: its [groups] (what it couldn't read among them), the
 * share of its characters (spaces aside) they, the holds and its notation's marks explain ([coverage]), what is left
 * unread ([unknown]), the label it leads with, the symbols it read as written ([used], in the order it counted
 * them), its words standing free ([free]), the share of it that is the tabber's words ([prose]), its longest run of
 * tokens holding holes ([run]) and its tokens. Two scans are equal by everything but [used], as Python's.
 *
 * The seam lane harptab-layout builds on: [isRow], [missed], [holey] and [explained] are Python's properties.
 */
class Scan(val groups: List<Group>, val coverage: Double, val unknown: List<String>, val label: String? = null,
           val used: Map<Used, Int> = emptyMap(), val free: Int = 0, val prose: Double = 0.0, val run: Int = 0,
           val tokens: Int = 0) {
    /** Scan.explained: the share of its characters, its words aside, its notation explains. */
    val explained: Double
        get() {
            val rest = 1 - prose
            return if (rest > 0) pyMin(1.0, coverage / rest) else 0.0
        }

    /** Its groups that play. */
    val holes: List<Group> get() = groups.filter { it.holes.isNotEmpty() }

    /** Scan.is_row. */
    val isRow: Boolean
        get() {
            val holes = holes
            return holes.isNotEmpty() && (coverage >= HarptabData.HOLE_SHARE || (explained >= HarptabData.HOLE_SHARE &&
                run >= minOf(3, tokens) && holes.size >= free))
        }

    /** Scan.missed: holes its notation couldn't read enough of to make it a row. */
    val missed: Boolean get() = !isRow && holes.size >= 3 && coverage >= HarptabData.MISSED_SHARE

    /** Scan.holey: a line of holes too few or too mixed to be a row, never a row's words. */
    val holey: Boolean get() = holes.size >= 2 && holes.size >= 2 * free

    override fun equals(other: Any?): Boolean = other is Scan && groups == other.groups &&
        coverage == other.coverage && unknown == other.unknown && label == other.label && free == other.free &&
        prose == other.prose && run == other.run && tokens == other.tokens

    override fun hashCode(): Int = listOf(groups, coverage, unknown, label, free, prose, run, tokens).hashCode()

    override fun toString(): String = "Scan(groups=$groups, coverage=$coverage, unknown=$unknown, label=$label, " +
        "used=$used, free=$free, prose=$prose, run=$run, tokens=$tokens)"

    companion object {
        /** A blank line's scan, as `_weighed` writes it: `Scan((), 0.0, ())`. */
        val BLANK = Scan(emptyList(), 0.0, emptyList())
    }
}

/** An item of a tab's section (harptab.Item): a row, the tabber's words, prose, a gap, a legend. */
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

/** harptab.Legend: a tab's own legend, its lines as written, what they say ([symbols]: "bare" for a hole written
 * alone, "" where the tab writes it) and where they are ([at], their places in the tab). */
data class Legend(val lines: List<String>, val symbols: List<Symbol>, val at: List<Int> = emptyList()) : TabItem

/** harptab.Section. */
data class TabSection(val label: String?, val items: List<TabItem> = emptyList())

/** harptab.Tab: a harmonica tab read and laid out (lane harptab-layout). */
data class Tab(val notes: List<String>, val sections: List<TabSection>, val reading: Reading, val key: String?,
               val missed: List<String>, val chromatic: Boolean, val legend: Legend? = null, val harp: String? = null)

/** A tab's text as it is read (harptab._prepared): the page's chip as caracole reads it ("Diatonic", "Chromatic", or
 * null), its lines (tabs expanded, the ends' spaces off), its legends and their lines' places. */
data class Prepared(val chip: String?, val lines: List<String>, val legends: List<Legend>, val inLegend: Set<Int>) {
    /** The lines a reading reads: its legends' blanked. */
    val read: List<String> get() = lines.mapIndexed { n, line -> if (n in inLegend) "" else line }
}

/**
 * viewer/harptab.py: a harmonica tab read under each notation (lane harptab-read: the notations, `scan`, the
 * legends, the candidates and their scores, `read`, `readings`, a pin) and laid out (lane harptab-layout: `parse`).
 * The notations are harptab.py's data (data/caracole/viewer/harptab.json); each compiles into its tokenizer through
 * core.py.PyRegex, so every pattern means what Python's does.
 */
object HarpTabs {
    val SIGNS: Notation get() = HarptabData.PRESETS[0]
    val BRACKETS: Notation get() = HarptabData.PRESETS[1]
    val LETTERS: Notation get() = HarptabData.PRESETS[2]
    val SIGNS_AFTER: Notation get() = HarptabData.PRESETS[3]
    val BARRETT: Notation get() = HarptabData.PRESETS[4]

    /** The presets, the commonest first: a tie goes to the first. */
    val PRESETS: List<Notation> get() = HarptabData.PRESETS
    val PRESET: Map<String, Notation> get() = HarptabData.PRESET

    /** Each candidate's, in a tab that writes a dot before a hole. */
    val DOTS: Symbol get() = HarptabData.DOTS

    /** A candidate where the page's chip says Diatonic: `signs` with `*` a bend after the hole. */
    val STAR_BENDS: Notation get() = HarptabData.STAR_BENDS

    /** What a pin may name: a preset, or the tab's own legend. */
    val PIN_NAMES: List<String> get() = HarptabData.PIN_NAMES

    /** harptab.expand: a line as the page lays it out, tabs to their stops, a no-break space a space. */
    fun expand(line: String): String = HarpTabText.expand(line)

    /** harptab.scan: the holes [line] holds as [notation] reads it. */
    fun scan(line: String, notation: Notation = SIGNS): Scan = Scanner.scan(line, notation)

    /** harptab.legend: the tab's legends. */
    fun legend(lines: List<String>): List<Legend> = Legends.legend(lines)

    /** harptab._prepared: a tab's text as it is read. */
    fun prepared(body: String, harp: String?): Prepared = Weighing.prepared(body, harp)

    /** harptab.read: how the tab's [lines] (tabs expanded, its legends' lines blanked) are best read, and each line
     * as that notation reads it; [notation] given is read as it is ("pinned"). */
    fun read(lines: List<String>, harpChip: String? = null, notation: Notation? = null,
             legends: List<Legend> = emptyList()): Pair<Reading, List<Scan>> = Weighing.read(lines, harpChip, notation, legends)

    fun parse(body: String, harp: String? = null, notation: Notation? = null): Tab = TODO("lane harptab-layout")

    /** harptab._candidates: the notations a tab's [lines] are read under, the commonest first, each with its source,
     * and its legends' symbols placed (what each candidate's agreement is counted against). */
    fun candidates(lines: List<String>, harpChip: String?, legends: List<Legend>): Pair<List<Pair<Notation, String>>, List<Symbol>> =
        Weighing.candidates(lines, harpChip, legends)

    /** harptab._weighed: each candidate scored on the tab's [lines]: Q = P × T, weighed by the legend's [found]. */
    fun weighed(lines: List<String>, candidates: List<Pair<Notation, String>>, harpChip: String?,
                found: List<Symbol>): Weighed = Weighing.weighed(lines, candidates, harpChip, found)

    /** harptab._meaning: what a legend's meaning says, by _LEXICON: the meaning its earliest word names, or null. */
    fun meaning(text: String): String? = Legends.meaning(text)

    /** harptab._entry: one line of a legend as a symbol, or null. */
    fun entry(sym: String, meaning: String): Symbol? = Legends.entry(sym, meaning)

    /** harptab.readings: every reading caracole weighs for the tab [body], best first; the first is `parse`'s. */
    fun readings(body: String, harp: String? = null): List<Reading> = Weighing.readings(body, harp)

    /** harptab.check_spec: refuses (IllegalArgumentException, Python's words) a pin that can't be one. */
    fun checkSpec(spec: JsonElement): Unit = Pins.checkSpec(spec)

    /** harptab.pinned: the notation the pin [spec] names for the tab [body], null for "legend" in a tab with none;
     * IllegalArgumentException for a spec [checkSpec] refuses. */
    fun pinned(spec: JsonElement, body: String): Notation? = Pins.pinned(spec, body)

    /** harptab.spec_of: the pin that reads a tab as [r] does: "legend", a preset's name, or a table. */
    fun specOf(r: Reading): JsonElement = Pins.specOf(r)

    /** harptab.said: the symbols [used], each as the tab writes it most, and what it means in words. */
    fun said(used: Map<Used, Int>): List<Pair<String, String>> = Weighing.said(used)
}

/** Python's min(a, b) of two floats: b only when it is below a. */
internal fun pyMin(a: Double, b: Double): Double = if (b < a) b else a
