package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigInteger
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap

/** voicings.Position: a chord's shape as chords-db and the page's data hold it, `[frets, fingers, base fret,
 * barres]`: [Voicings.position] makes one, [Voicings.frets], [Voicings.fingers] and [Voicings.base] read one. */
typealias Position = JsonArray

/**
 * viewer/voicings.py: the guitar's chord shapes, chords-db's (voicings.json, voicings-ukulele.json: viewer/'s own
 * files, on the classpath as they are) and a sheet's own (a chord legend's line, a `{define}`).
 *
 * A position's frets and fingers are strings of one character a string, as a chord box draws them left to right
 * (the guitar's low E first): "x" a muted string, "0" an open one, else the fret counted from the base fret. They are
 * read by code point, as Python reads a str, and a digit is any Unicode decimal digit (`\d` and `int()`'s), so
 * "x３２０３３" is the shape "x32033" is. The patterns are voicings.py's own, as Python writes them
 * (caracole/viewer/instruments.json's `voicings`), read by core.py.PyRegex as Python reads them.
 *
 * A position's base fret is Python's int, whole: a `{define}` may give one no Int holds, which [parseDefine] keeps,
 * [plays] and [sheetShapes] read and a page's data carries as Python's do (vectors/viewer/voicings.jsonl's last
 * records, `big_base_records`). Only [base], [notesOf] and [fretsFromNut] answer Ints, the skeleton's types: past an
 * Int they are an [ArithmeticException] where Python answers the larger number.
 *
 * The answers are kept, as Python's caches keep them; positions and the objects handed out are JSON, which nothing
 * can change, and a list handed out is a copy.
 */
object Voicings {
    /** Standard tuning, E2 A2 D3 G3 B3 E4, as MIDI notes, low E first (voicings.TUNING; the skeleton's, whole, so
     * harmony needs theory alone: VoicingsTest holds it to the data). */
    val TUNING: List<Int> = listOf(40, 45, 50, 55, 59, 64)

    private val constants: JsonObject by lazy { ViewerData.table("instruments").getValue("voicings").jsonObject }
    private fun pattern(name: String): Regex =
        PyRegex.compile(constants.getValue("patterns").jsonObject.getValue(name).jsonPrimitive.content)

    /** The most positions chords-db's data files a chord on a root (voicings.MAX_POSITIONS). */
    val MAX_POSITIONS: Int get() = maxPositions
    private val maxPositions: Int by lazy { constants.getValue("MAX_POSITIONS").jsonPrimitive.int }
    private val fretSpan: Int by lazy { constants.getValue("_FRET_SPAN").jsonPrimitive.int }
    private val fingering: Regex by lazy { pattern("_FINGERING") }
    private val entry: Regex by lazy { pattern("_ENTRY") }
    private val defineFrets: Regex by lazy { pattern("_DEFINE_FRETS") }
    private val defineFingers: Regex by lazy { pattern("_DEFINE_FINGERS") }
    private val defineBase: Regex by lazy { pattern("_DEFINE_BASE") }
    private val separators: Regex by lazy { PyRegex.compile("""[\s.,-]+""") }  // parse_fingering's split

    /** A position, `[frets, fingers, base fret, barres]`. */
    fun position(frets: String, fingers: String, base: Int, barres: List<Int> = emptyList()): Position =
        position(frets, fingers, BigInteger.valueOf(base.toLong()), barres)

    private fun position(frets: String, fingers: String, base: BigInteger, barres: List<Int> = emptyList()): Position =
        JsonArray(listOf(JsonPrimitive(frets), JsonPrimitive(fingers), JsonPrimitive(base),
                         JsonArray(barres.map(::JsonPrimitive))))

    fun frets(position: Position): String = position[0].jsonPrimitive.content
    fun fingers(position: Position): String = position[1].jsonPrimitive.content

    /** The base fret, an [ArithmeticException] for one past an Int (see the object's notes). */
    fun base(position: Position): Int = wholeBase(position).intValueExact()

    /** The base fret whole, as Python's int. */
    private fun wholeBase(position: Position): BigInteger = BigInteger(position[2].jsonPrimitive.content)

    /** The fingerings of an instrument's table, "guitar" (voicings.json) or "ukulele" (voicings-ukulele.json):
     * `data[quality][root]`, a root's positions, pitch class 0 (C) first. */
    fun loadVoicings(table: String = "guitar"): Map<String, List<List<Position>>> = tables(table).typed

    /** The table's file as JSON, its members in its order. */
    internal fun rawVoicings(table: String = "guitar"): JsonObject = tables(table).raw

    private class Table(val raw: JsonObject, val typed: Map<String, List<List<Position>>>)

    private val files = mapOf("guitar" to "voicings.json", "ukulele" to "voicings-ukulele.json")
    private val loaded = ConcurrentHashMap<String, Table>()

    private fun tables(table: String): Table = loaded.getOrPut(table) {
        val name = files[table] ?: throw NoSuchElementException("no fingerings for $table")
        val raw = Json.parseToJsonElement(ViewerAssets.text(name)).jsonObject
        val typed = LinkedHashMap<String, List<List<Position>>>()
        for ((key, roots) in raw) {
            typed[key] = Collections.unmodifiableList(roots.jsonArray.map { positions ->
                Collections.unmodifiableList(positions.jsonArray.map { it.jsonArray })
            })
        }
        Table(raw, Collections.unmodifiableMap(typed))
    }

    /** The MIDI notes [position] sounds on [tuning] (the guitar's unless given), string by string in the position's
     * order; an [IllegalArgumentException] when the position has another number of strings, as zip(strict=True). */
    fun notesOf(position: Position, tuning: List<Int> = TUNING): List<Int> = wholeNotes(position, tuning).map { it.intValueExact() }

    private fun wholeNotes(position: Position, tuning: List<Int>): List<BigInteger> {
        val frets = Py.codePoints(frets(position))
        val base = wholeBase(position)
        val notes = ArrayList<BigInteger>()
        for ((i, string) in tuning.withIndex()) {
            require(i < frets.size) { "zip() argument 2 is shorter than argument 1" }
            if (frets[i] == 'x'.code) continue
            val n = digit(frets[i])
            notes += if (n != 0) base + BigInteger.valueOf(string.toLong() + n - 1) else BigInteger.valueOf(string.toLong())
        }
        require(frets.size == tuning.size) { "zip() argument 2 is longer than argument 1" }
        return notes
    }

    private val TWELVE = BigInteger.valueOf(12)

    /** Whether [position] sounds [chord] on [tuning]: no other note, the root, and a slash chord's bass lowest. */
    fun plays(position: Position, chord: Chord, tuning: List<Int> = TUNING): Boolean {
        val notes = wholeNotes(position, tuning)
        val pcs = notes.map { it.mod(TWELVE).toInt() }.toSet()
        if (notes.isEmpty() || !chord.pitchClasses.containsAll(pcs) || chord.root !in pcs) return false
        return chord.bass == null || notes.min().mod(TWELVE).toInt() == chord.bass
    }

    /**
     * A fingering as a tab writes it ("x32033", "(x32033)", "x-3-2-0-3-3"), as a position: no fingers ("000000"),
     * no barres, its frets counted from the nut when the highest is the 4th or lower, else from the lowest held.
     * Null when the text is no fingering, or sounds no string.
     */
    fun parseFingering(text: String): Position? {
        val m = PyRe.fullmatch(fingering, text) ?: return null
        val raw = Py.strip(PyText.strip(m.groupValues[1], "()"))
        val cps = Py.codePoints(raw)
        val parts = if (cps.size == TUNING.size) cps.map { Py.string(intArrayOf(it)) }
                    else PyRe.split(separators, raw).map { it!! }
        val frets = parts.map { if ("xX".contains(it)) null else number(it)!! }
        val held = frets.filter { it != null && it != 0 }.map { it!! }
        if (frets.all { it == null } || frets.any { it != null && it > 24 }) return null
        val base = if (held.isEmpty() || held.max() <= 4) 1 else held.min()
        if (held.isNotEmpty() && held.max() - base + 1 > fretSpan) return null
        val shown = frets.joinToString("") { f -> if (f == null) "x" else if (f == 0) "0" else (f - base + 1).toString() }
        return position(shown, "0".repeat(TUNING.size), base)
    }

    /**
     * The chords a line of a tab's chord legend gives fingerings for ("Dsus4   (xx0233)", "Em7 022033  G 320033"),
     * each with its position, in order; empty for a line that is anything else, or more than a legend.
     */
    fun chordLegend(line: String): List<Pair<Chord, Position>> {
        val entries = ArrayList<Pair<Chord, Position>>()
        var at = 0
        val end = rstrip(line).length
        while (at < end) {
            val m = entry.matchAt(line, at)
            val chord = m?.let { Theory.parseChord(it.groupValues[1]) }
            val position = m?.let { parseFingering(it.groupValues[2]) }
            if (m == null || chord == null || position == null) return emptyList()
            entries += chord to position
            at = m.range.last + 1
        }
        return entries
    }

    /**
     * The chord a ChordPro `{define}` (or `{chord}`) names, and its position: "Cadd9 base-fret 1 frets x 3 2 0 3 3
     * fingers 0 2 1 0 3 4". Null when it names no chord caracole reads, or gives no guitar fingering that fits a
     * diagram. Its base fret is kept whole, as int() reads it (more than 4300 digits an error, as Python's).
     */
    fun parseDefine(value: String): Pair<Chord, Position>? {
        val (name, rest) = splitOnce(value)
        val chord = if (name.isNotEmpty()) Theory.parseChord(name) else null
        val fretsFound = defineFrets.find(rest)
        if (chord == null || fretsFound == null) return null
        val frets = Py.split(fretsFound.groupValues[1]).map { if (it in MUTED) "x" else it }
        if (frets.all { it == "x" } || frets.any { it != "x" && bigNumber(it) > fretSpan.toBigInteger() }) return null
        val fingersFound = defineFingers.find(rest)
        val fingers = fingersFound?.let { Py.split(it.groupValues[1]) } ?: List(TUNING.size) { "0" }
        val baseFound = defineBase.find(rest)
        val base = if (baseFound != null) bigNumber(baseFound.groupValues[1]).max(BigInteger.ONE) else BigInteger.ONE
        val shown = fingers.map { if (Py.len(it) == 1 && "123456789".contains(it)) it else "0" }
        return chord to position(frets.joinToString(""), shown.joinToString(""), base)
    }

    private val MUTED = setOf("-1", "x", "X", "n", "N")

    /**
     * The shapes a sheet gives its chords ([chordLegend], [parseDefine]), first, then chords-db's: `{"mine": how many
     * are the sheet's, "list": positions}`, filed by [shapeKey]. A shape that doesn't play its chord is left out, and
     * one shape is shown once: one chords-db has too is chords-db's, with its fingers, unless the sheet gave fingers
     * of its own. Its members in the order the sheet first gives each chord.
     */
    fun sheetShapes(given: List<Pair<Chord, Position>>): JsonObject {
        val data = loadVoicings()
        class Entry(var mine: Int, val list: MutableList<Position>)
        val shapes = LinkedHashMap<String, Entry>()
        for ((chord, gave) in given) {
            var position = gave
            if (!plays(position, chord)) continue
            val key = shapeKey(chord)
            val entry = shapes.getOrPut(key) {
                val (fingering, _, slash) = voicingKeys(chord)
                val filed = listOfNotNull(slash, fingering).filter { it in data && data.getValue(it)[chord.root].isNotEmpty() }
                Entry(0, filed.firstOrNull()?.let { ArrayList(data.getValue(it)[chord.root]) } ?: ArrayList())
            }
            val frets = wholeFrets(position)
            val same = entry.list.indexOfFirst { wholeFrets(it) == frets }.takeIf { it >= 0 }
            if (same != null && same < entry.mine) continue  // the sheet gave it already
            if (same != null) {
                val known = entry.list.removeAt(same)
                if (PyText.strip(fingers(position), "0").isEmpty()) position = known  // no fingers given: chords-db's
            }
            entry.list.add(entry.mine, position)
            entry.mine++
        }
        return JsonObject(shapes.mapValuesTo(LinkedHashMap()) { (_, e) ->
            JsonObject(linkedMapOf("mine" to JsonPrimitive(e.mine), "list" to JsonArray(e.list)))
        })
    }

    /** Where [sheetShapes] files a chord's shapes: the chord as shown, "<root>,<suffix>,<bass>" ("0,add9," for Cadd9,
     * "2,sus4,6" for Dsus4/F#). */
    fun shapeKey(chord: Chord): String = "${chord.root},${chord.suffix},${chord.bass ?: ""}"

    /** The frets [position] holds, counted from the nut (null for a muted string): the same shape written from
     * another base fret is the same. */
    fun fretsFromNut(position: Position): List<Int?> = wholeFrets(position).map { it?.intValueExact() }

    private fun wholeFrets(position: Position): List<BigInteger?> {
        val base = wholeBase(position)
        return Py.codePoints(frets(position)).map { f ->
            if (f == 'x'.code) null else digit(f).let { if (it != 0) base + BigInteger.valueOf(it - 1L) else BigInteger.ZERO }
        }
    }

    private val keys = Kept<Chord, Triple<String, Boolean, String?>>(4096)

    /**
     * Where a chord's fingerings are filed: (quality, whether it is only the nearest one, slash key). A quality
     * without fingerings shows the largest one with them whose notes are all the chord's, keeping its third
     * (Cmaj7#11 shows Cmaj7); failing that, the plain major or minor triad. A major or minor slash chord looks for
     * its own fingerings first (the slash key, which may still have none on a given root).
     */
    fun voicingKeys(chord: Chord): Triple<String, Boolean, String?> = keys.getOrPut(chord) {
        val data = loadVoicings()
        var quality = chord.quality
        var nearest = false
        if (chord.tones != null || quality !in data) {
            quality = nearest(chord, data.keys)
            nearest = true
        }
        var slash: String? = null
        if (chord.bass != null && !nearest && (quality == "" || quality == "m")) {
            val candidate = "$quality/${Math.floorMod(chord.bass - chord.root, 12)}"
            slash = candidate.takeIf { it in data }
        }
        Triple(quality, nearest, slash)
    }

    /** voicings._nearest: the first of the largest qualities of [filed] whose notes are all [chord]'s, keeping its
     * third; else the major or minor triad by its third. */
    internal fun nearest(chord: Chord, filed: Set<String>): String {
        val intervals = chord.intervals
        val third = listOf(3, 4).firstOrNull { it in intervals }
        var best: String? = null
        for ((q, notes) in Theory.QUALITIES) {
            if (q !in filed || !intervals.containsAll(notes) || (third != null && third !in notes)) continue
            if (best == null || notes.size > Theory.QUALITIES.getValue(best).size) best = q
        }
        return best ?: if (third == 3) "m" else ""
    }

    /** The fingerings a page needs: those filed under [keys], on every root, by key in code-point order. */
    fun pageVoicings(keys: Set<String>): JsonObject {
        val raw = rawVoicings()
        val out = LinkedHashMap<String, kotlinx.serialization.json.JsonElement>()
        for (key in keys.sortedWith(Py.CODE_POINT_ORDER)) raw[key]?.let { out[key] = it }
        return JsonObject(out)
    }

    /** str.split(None, 1), padded: the first word and the rest, its leading whitespace skipped. */
    private fun splitOnce(value: String): Pair<String, String> {
        var i = skipSpaces(value, 0)
        val start = i
        while (i < value.length && !PyUnicode.isSpace(value.codePointAt(i))) i += Character.charCount(value.codePointAt(i))
        val name = value.substring(start, i)
        return name to value.substring(skipSpaces(value, i))
    }

    private fun skipSpaces(s: String, from: Int): Int {
        var i = from
        while (i < s.length && PyUnicode.isSpace(s.codePointAt(i))) i += Character.charCount(s.codePointAt(i))
        return i
    }

    /** str.rstrip(). */
    private fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }

    /** A Unicode decimal digit's value: its place in its run of ten (Unicode writes each script's 0-9 in a row). */
    internal fun digit(cp: Int): Int {
        require(PyUnicode.isDecimal(cp)) { "invalid literal for int() with base 10: '${Py.string(intArrayOf(cp))}'" }
        var start = cp
        while (PyUnicode.isDecimal(start - 1)) start--
        return (cp - start) % 10
    }

    /** int() of a run of decimal digits, or null past what an Int holds. */
    internal fun number(text: String): Int? = bigNumber(text).takeIf { it <= Int.MAX_VALUE.toBigInteger() }?.toInt()

    private fun bigNumber(text: String): BigInteger {
        val cps = Py.codePoints(text)
        require(cps.isNotEmpty()) { "invalid literal for int() with base 10: ''" }
        require(cps.size <= 4300) { "Exceeds the limit (4300 digits) for integer string conversion" }
        val digits = StringBuilder(cps.size)
        for (cp in cps) digits.append('0' + digit(cp))
        return BigInteger(digits.toString())
    }
}
