package io.github.danielhp95.caracole.viewer.harp

import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap

/** harp.Layout: a harp's notes, holes 1 to 10, as MIDI numbers; [harp] is its key's pitch class. */
data class Layout(val harp: Int, val blow: List<Int>, val draw: List<Int>) {
    val name: String get() = Harp.HARP_KEYS[harp]

    /** The breath each hole bends on: its higher reed's. */
    val bendBreath: List<String> get() = blow.indices.map { if (draw[it] > blow[it]) "draw" else "blow" }

    /** Each hole's bent notes, a semitone at a time down from its higher reed to a semitone above the other. */
    val bends: List<List<Int>> get() = blow.indices.map {
        val high = maxOf(blow[it], draw[it])
        val low = minOf(blow[it], draw[it])
        (high - 1 downTo low + 1).toList()
    }
}

/** harp.Playing: how a harp plays a chord: [kind] "yes" (its own notes), "part" (its triad), "minor" (the minor triad
 * on its root) or "no"; the breath, the first and last holes, and [played], the chord those holes sound. */
data class Playing(val kind: String, val breath: String?, val holes: Pair<Int, Int>?, val played: Chord?) {
    /** "draw 2–5", "blow 1–3 (as C)", "draw 4–6 (as Dm, minor substitute)", "not on this harp": the chord played
     * named with [names] (Theory.spelling of the key shown). */
    fun text(names: List<String>): String =
        if (played == null || holes == null) "not on this harp" else Harp.entryText(Harp.entry(this), names[played.root])
}

/** harp.HarpChoice: a harp for a song, its position, its key (a pitch class), the position's mode, and how it plays
 * the song's chords: [fit] (the ranking's score), of [chords] distinct chords, [plays] whole or as their triad and
 * [substitutes] as a minor one. */
data class HarpChoice(val position: Int, val harp: Int, val mode: String?, val fit: Double, val chords: Int,
                      val plays: Int, val substitutes: Int) {
    val name: String get() = Harp.HARP_KEYS[harp]
}

/**
 * viewer/harp.py: the 10-hole diatonic harmonica in Richter tuning: its layout in every key, the positions it plays
 * a song in, the chords it plays, the harps to pick for a song (by one rule in one place: [candidates], [CHORD_FIT],
 * [TONIC_WEIGHT] and [ranking]), and the tables a viewer's data carries. Its constants are harp.py's own
 * (caracole/viewer/harp.json); the key card's pentatonic is harmony.py's, written there too.
 *
 * The answers are kept, as Python's caches keep them; a list handed out is a copy, the tables JSON nothing changes.
 */
object Harp {
    private val json: JsonObject by lazy { ViewerData.table("harp") }
    private fun ints(name: String): List<Int> =
        Collections.unmodifiableList(json.getValue(name).jsonArray.map { it.jsonPrimitive.int })

    val HOLES: Int by lazy { json.getValue("HOLES").jsonPrimitive.int }
    /** A C harp's notes, holes 1 to 10, in semitones above hole 1's blow (C4). */
    val BLOW: List<Int> by lazy { ints("BLOW") }
    val DRAW: List<Int> by lazy { ints("DRAW") }
    /** The harps' keys as they are sold, by pitch class. */
    val HARP_KEYS: List<String> by lazy {
        Collections.unmodifiableList(json.getValue("HARP_KEYS").jsonArray.map { it.jsonPrimitive.content })
    }
    val POSITIONS: List<Int> by lazy { ints("POSITIONS") }
    /** What a chord the harp plays counts for its fit, by how it plays it; and a chord on the song's tonic, times
     * [TONIC_WEIGHT]. */
    val CHORD_FIT: Map<String, Double> by lazy {
        Collections.unmodifiableMap(json.getValue("CHORD_FIT").jsonObject.mapValuesTo(LinkedHashMap()) { (_, v) ->
            v.jsonPrimitive.double
        })
    }
    val TONIC_WEIGHT: Int by lazy { json.getValue("TONIC_WEIGHT").jsonPrimitive.int }
    val MINOR_BLUES: List<Int> by lazy { ints("MINOR_BLUES") }
    val MAJOR_BLUES: List<Int> by lazy { ints("MAJOR_BLUES") }

    private val lowest: Int by lazy { json.getValue("_LOWEST").jsonPrimitive.int }
    private val ordinals: Map<Int, String> by lazy {
        json.getValue("_ORDINALS").jsonObject.entries.associate { (k, v) -> k.toInt() to v.jsonPrimitive.content }
    }
    private val modeWords: Map<String, String> by lazy {
        json.getValue("_MODE_WORDS").jsonObject.mapValues { (_, v) -> v.jsonPrimitive.content }
    }
    private val pentatonic: Map<String, List<Int>> by lazy {
        json.getValue("harmony").jsonObject.getValue("pentatonic").jsonObject.mapValues { (_, v) ->
            v.jsonArray.map { it.jsonPrimitive.int }
        }
    }
    private val ionian: List<Int> get() = Theory.SCALES.getValue("ionian")

    /** QUALITIES by its intervals, a later quality of the same intervals winning, as a dict comprehension does. */
    private val qualityOf: Map<Set<Int>, String> by lazy { Theory.QUALITIES.entries.associate { (q, iv) -> iv to q } }

    private val layouts = ConcurrentHashMap<Int, Layout>()

    /** The harp in the key of pitch class [harp]. */
    fun layout(harp: Int): Layout = layouts.getOrPut(Math.floorMod(harp, 12)) {
        val low = lowest + Math.floorMod(harp - 7, 12)
        Layout(Math.floorMod(harp, 12), Collections.unmodifiableList(BLOW.map { low + it }),
               Collections.unmodifiableList(DRAW.map { low + it }))
    }

    /** The mode a harp plays in a position (1 to 12) with no bend; null for the 7th to the 11th. */
    fun positionMode(position: Int): String? {
        val interval = Math.floorMod(7 * (position - 1), 12)
        val degree = ionian.indexOf(interval)
        return if (degree >= 0) Theory.MODES[degree] else null
    }

    /** The key of the harp that plays a song on [tonic] in [position]: a song in G takes a C harp in the 2nd. */
    fun harpFor(tonic: Int, position: Int): Int = Math.floorMod(tonic - 7 * (position - 1), 12)

    /** The position a harp in [harp] plays a song on [tonic] in, 1 to 12. */
    fun positionOf(tonic: Int, harp: Int): Int = Math.floorMod((tonic - harp) * 7, 12) + 1

    /** "1st", "2nd", "3rd", "4th"... "12th". */
    fun ordinal(position: Int): String = "$position${ordinals[position] ?: "th"}"

    // --- the chords a harp plays ---------------------------------------------------------------------------------

    private class Run(val breath: String, val first: Int, val last: Int, val pcs: Set<Int>, val low: Int)

    /** Each run of two or more neighbouring holes on one breath of a C harp, first holes first, the narrowest first. */
    private val runs: List<Run> by lazy {
        val out = ArrayList<Run>()
        for (width in 2..HOLES) for (first in 1..HOLES - width + 1) {
            for ((breath, notes) in listOf("blow" to BLOW, "draw" to DRAW)) {
                val last = first + width - 1
                out += Run(breath, first, last, (first..last).map { Math.floorMod(60 + notes[it - 1], 12) }.toSet(),
                           Math.floorMod(notes[first - 1], 12))
            }
        }
        out
    }

    /** The run of a C harp that sounds exactly [pcs]: one starting on the first of [starts] that has one, else any;
     * the narrowest, then the lowest. */
    private fun run(pcs: Set<Int>, starts: List<Int>): Run? {
        var found = runs.filter { it.pcs == pcs }
        for (start in starts) {
            val on = found.filter { it.low == start }
            if (on.isNotEmpty()) {
                found = on
                break
            }
        }
        return found.minWithOrNull(compareBy<Run>({ it.last - it.first }, { it.first }))
    }

    /** A chord's triad: its root, its third (the major one when it has both) or else its suspension, and its fifth
     * (the perfect one when it has it, else its ♭5 or ♯5). */
    private fun triad(intervals: Set<Int>): Set<Int> {
        val third = if (4 in intervals) setOf(4) else if (3 in intervals) setOf(3) else setOf(2, 5) intersect intervals
        val fifth = if (7 in intervals) setOf(7) else setOf(6, 8) intersect intervals
        return setOf(0) + third + fifth
    }

    private class OnC(val kind: String, val breath: String?, val holes: Pair<Int, Int>?, val quality: String?)

    private val onC = ConcurrentHashMap<Triple<Int, Set<Int>, Int?>, OnC>()

    /** How a C harp plays the chord: (kind, breath, holes, the quality played: null for the chord itself). */
    private fun onC(root: Int, intervals: Set<Int>, bass: Int?): OnC = onC.getOrPut(Triple(root, intervals, bass)) {
        val pcs = intervals.map { Math.floorMod(root + it, 12) }.toSet() + listOfNotNull(bass)
        val whole = run(pcs, listOfNotNull(bass) + root)
        if (whole != null) return@getOrPut OnC("yes", whole.breath, whole.first to whole.last, null)
        val triad = triad(intervals)
        val quality = qualityOf[triad]
        if (quality != null && triad != intervals + listOfNotNull(bass?.let { Math.floorMod(it - root, 12) })) {
            val part = run(triad.map { Math.floorMod(root + it, 12) }.toSet(), listOf(root))
            if (part != null) return@getOrPut OnC("part", part.breath, part.first to part.last, quality)
        }
        if (4 in intervals && (7 in intervals || (setOf(6, 8) intersect intervals).isEmpty())) {
            val minor = run(listOf(0, 3, 7).map { Math.floorMod(root + it, 12) }.toSet(), listOf(root))
            if (minor != null) return@getOrPut OnC("minor", minor.breath, minor.first to minor.last, "m")
        }
        OnC("no", null, null, null)
    }

    /** How the harp in the key of pitch class [harp] plays [chord] (harp.py's docstring). */
    fun play(chord: Chord, harp: Int): Playing {
        val bass = chord.bass?.let { Math.floorMod(it - harp, 12) }
        val found = onC(Math.floorMod(chord.root - harp, 12), chord.intervals, bass)
        if (found.kind == "no") return Playing("no", null, null, null)
        return Playing(found.kind, found.breath, found.holes,
                       if (found.quality == null) chord else Chord(chord.root, found.quality))
    }

    /** A [Playing] as the tables' entry: null for a chord not on that harp, else `[kind, breath, first, last]`, and
     * for "part" or "minor" the suffix of the chord played there. */
    fun entry(playing: Playing): JsonArray? {
        if (playing.kind == "no" || playing.holes == null || playing.played == null) return null
        val found = mutableListOf<JsonElement>(JsonPrimitive(playing.kind), JsonPrimitive(playing.breath),
                                               JsonPrimitive(playing.holes.first), JsonPrimitive(playing.holes.second))
        if (playing.kind != "yes") found += JsonPrimitive(playing.played.suffix)
        return JsonArray(found)
    }

    /** An entry as the page writes it, the chord's root named [root]: "draw 2–5", "blow 1–3 (as C)", "draw 4–6 (as
     * Dm, minor substitute)", "not on this harp". */
    fun entryText(found: JsonArray?, root: String): String {
        if (found == null) return "not on this harp"
        fun at(i: Int) = found[i].jsonPrimitive.content
        val where = "${at(1)} ${at(2)}–${at(3)}"
        if (at(0) == "yes") return where
        return "$where (as $root${at(4)}" + if (at(0) == "minor") ", minor substitute)" else ")"
    }

    // --- the harps for a song: the ranking, the one rule they are chosen by --------------------------------------

    private val own: Map<String, Int> by lazy {
        POSITIONS.mapNotNull { p -> positionMode(p)?.let { it to p } }.toMap()
    }

    /** The positions a song in [key] may take, in their order: the 1st and the 2nd for a mode with a major third,
     * the 3rd, the 4th and the 5th for one with a minor third, and the position whose own mode is the song's. */
    fun candidates(key: Key): List<Int> {
        val found = if (4 in Theory.SCALES.getValue(key.mode)) mutableListOf(1, 2) else mutableListOf(3, 4, 5)
        val mine = own.getValue(key.mode)
        if (mine !in found) found += mine
        return found
    }

    /** The rule the harps for a song in [key] are ranked by, as a sort key, the least first ([order] is the choice's
     * place in [candidates]): a major key, the candidates' order; any other mode, the most fit, then the position
     * whose mode changes the fewest of the song's notes, then the candidates' order. */
    fun ranking(key: Key, order: Int, choice: HarpChoice): List<Double> {
        if (key.mode == "ionian") return listOf(order.toDouble())
        val changed = if (choice.mode != null) {
            symmetric(Theory.scale(Key(key.tonic, choice.mode)), Theory.scale(key)) / 2
        } else 7
        return listOf(-choice.fit, changed.toDouble(), order.toDouble())
    }

    private fun symmetric(a: Set<Int>, b: Set<Int>): Int = a.count { it !in b } + b.count { it !in a }

    /** Python's order of two tuples of numbers: element by element as numbers compare (−0.0 is 0.0), then length. */
    private val RANKED = Comparator<List<Double>> { a, b ->
        for (i in 0 until minOf(a.size, b.size)) {
            if (a[i] < b[i]) return@Comparator -1
            if (a[i] > b[i]) return@Comparator 1
        }
        a.size.compareTo(b.size)
    }

    private val chosen = ConcurrentHashMap<Pair<Key, List<Chord>>, List<HarpChoice>>()

    /** The harps for a song in [key] whose chords (as they sound) are [chords], best first, at most three. A chord
     * caracole can't read (null) counts for nothing; a chord played again, once. */
    fun choices(key: Key, chords: List<Chord?>): List<HarpChoice> {
        val distinct = LinkedHashMap<Triple<Int, Set<Int>, Int?>, Chord>()
        for (chord in chords) if (chord != null) distinct.putIfAbsent(Triple(chord.root, chord.intervals, chord.bass), chord)
        val heard = distinct.values.toList()
        return ArrayList(chosen.getOrPut(key to heard) { choose(key, heard) })
    }

    private fun choose(key: Key, chords: List<Chord>): List<HarpChoice> {
        val found = ArrayList<Pair<List<Double>, HarpChoice>>()
        for ((order, position) in candidates(key).withIndex()) {
            val harp = harpFor(key.tonic, position)
            var fit = 0.0
            var plays = 0
            var substitutes = 0
            for (chord in chords) {
                val kind = play(chord, harp).kind
                fit += CHORD_FIT.getValue(kind) * (if (chord.root == key.tonic) TONIC_WEIGHT else 1)
                if (kind == "yes" || kind == "part") plays++
                if (kind == "minor") substitutes++
            }
            val choice = HarpChoice(position, harp, positionMode(position), fit, chords.size, plays, substitutes)
            found += ranking(key, order, choice) to choice
        }
        return Collections.unmodifiableList(found.sortedWith { a, b -> RANKED.compare(a.first, b.first) }
                                                .take(3).map { it.second })
    }

    /** What the header line writes in the brackets of the [n]th harp: "1st position", "2nd", "4th, aeolian". */
    private fun label(n: Int, choice: HarpChoice): String {
        var label = ordinal(choice.position) + if (n == 0) " position" else ""
        if (choice.position != 1 && choice.position != 2 && !choice.mode.isNullOrEmpty()) label += ", " + choice.mode
        return label
    }

    /** "Harmonica: G harp (1st position) · C harp (2nd)": the harps for a song in [key] whose chords (as they sound)
     * are [chords]. */
    fun headerLine(key: Key, chords: List<Chord?>): String =
        "Harmonica: " + choices(key, chords).withIndex().joinToString(" · ") { (n, c) -> "${c.name} harp (${label(n, c)})" }

    // --- the tables a viewer's data carries ----------------------------------------------------------------------

    /** The tables for a sheet in [key] whose chords in each mode are `mapped[mode]` (`data.mapped`) and their
     * alternatives `alts[mode]` (`data.alts`), as harp.py's docstring says, members in its order; with no key,
     * none. */
    fun tables(key: Key?, mapped: Map<String, List<Chord?>>, alts: Map<String, List<List<Chord>>>? = null): JsonObject {
        if (key == null) return JsonObject(emptyMap())
        val forms = ArrayList<JsonElement>()
        val known = HashMap<List<JsonElement>, Int>()
        fun form(chord: Chord?): JsonElement {
            if (chord == null) return JsonNull
            val entries = (0 until 12).map { entry(play(chord, Math.floorMod(key.tonic + it, 12))) ?: JsonNull }
            val index = known.getOrPut(entries) { forms.size }
            if (index == forms.size) forms.add(JsonArray(entries))
            return JsonPrimitive(index)
        }
        fun steps(chord: Chord?): JsonElement = if (chord == null) JsonNull else intsOf(chordSteps(chord, key.tonic))
        val harps = LinkedHashMap<String, JsonElement>()
        val chords = LinkedHashMap<String, JsonElement>()
        val alternatives = LinkedHashMap<String, JsonElement>()
        val scales = LinkedHashMap<String, JsonElement>()
        val outsides = LinkedHashMap<String, JsonElement>()
        val notes = LinkedHashMap<String, JsonElement>()
        val altNotes = LinkedHashMap<String, JsonElement>()
        for (mode in Theory.MODES) {
            val inMode = mapped[mode] ?: continue
            val options = alts?.get(mode) ?: emptyList()
            val found = choices(Key(key.tonic, mode), inMode)
            harps[mode] = JsonArray(found.withIndex().map { (n, c) ->
                JsonArray(listOf(JsonPrimitive(c.position), JsonPrimitive(Math.floorMod(c.harp - key.tonic, 12)),
                                 JsonPrimitive(label(n, c))))
            })
            chords[mode] = JsonArray(inMode.map(::form))
            alternatives[mode] = JsonArray(options.map { o -> JsonArray(o.map(::form)) })
            scales[mode] = keyScales(mode)
            outsides[mode] = JsonArray((0 until 12).map { outside(mode, it) })
            notes[mode] = JsonArray(inMode.map(::steps))
            altNotes[mode] = JsonArray(options.map { o -> JsonArray(o.map(::steps)) })
        }
        return JsonObject(linkedMapOf(
            "harpKeys" to JsonArray(HARP_KEYS.map(::JsonPrimitive)), "harps" to JsonObject(harps),
            "harpForms" to JsonArray(forms), "harpChords" to JsonObject(chords), "harpAlts" to JsonObject(alternatives),
            "harpRing" to ring(), "harpHoles" to JsonArray((0 until 12).map(::holes)), "harpScales" to JsonObject(scales),
            "harpOutside" to JsonObject(outsides), "harpNotes" to JsonObject(notes), "harpAltNotes" to JsonObject(altNotes),
        ))
    }

    // --- the overlay's tables: the harps round the circle, each harp's holes, the key on it ----------------------

    /** The 12 harps round the circle of fifths, by position, 1st to 12th: `[offset, ordinal, mode]`. */
    fun ring(): JsonArray = JsonArray(POSITIONS.map { p ->
        JsonArray(listOf(JsonPrimitive(harpFor(0, p)), JsonPrimitive(ordinal(p)), positionMode(p)?.let(::JsonPrimitive) ?: JsonNull))
    })

    /** The harp [offset] semitones above the song's tonic, its notes as steps above the tonic: its ten holes'
     * `blow` and `draw`, and each hole's `bends`, `[breath, steps]`, the shallowest first. */
    fun holes(offset: Int): JsonObject {
        val harp = layout(Math.floorMod(offset, 12))
        fun steps(notes: List<Int>) = intsOf(notes.map { Math.floorMod(it, 12) })
        return JsonObject(linkedMapOf(
            "blow" to steps(harp.blow), "draw" to steps(harp.draw),
            "bends" to JsonArray(harp.bendBreath.zip(harp.bends).map { (breath, bent) ->
                JsonArray(listOf(JsonPrimitive(breath), steps(bent)))
            }),
        ))
    }

    /** The scales of a key in [mode] the harp's key card offers, each `[name, steps]`: "Scale", its pentatonic and
     * "Blues". */
    fun keyScales(mode: String): JsonArray {
        val major = 4 in Theory.SCALES.getValue(mode)
        return JsonArray(listOf(
            JsonArray(listOf(JsonPrimitive("Scale"), intsOf(Theory.SCALES.getValue(mode)))),
            JsonArray(listOf(JsonPrimitive((if (major) "Major" else "Minor") + " pentatonic"),
                             intsOf(pentatonic.getValue(mode)))),
            JsonArray(listOf(JsonPrimitive("Blues"), intsOf(if (major) MAJOR_BLUES else MINOR_BLUES))),
        ))
    }

    /** What the key card says under the holes of the harp [offset] semitones above the song's tonic, a key in [mode],
     * as a text (steps for the notes): the notes it blows or draws outside the key's scale ("Outside B minor: C."),
     * or that none is. */
    fun outside(mode: String, offset: Int): JsonArray {
        val words = " " + (modeWords[mode] ?: mode)
        val scale = Theory.SCALES.getValue(mode)
        val out = ionian.map { Math.floorMod(offset + it, 12) }.filter { it !in scale }
        if (out.isEmpty()) {
            return JsonArray(listOf(JsonPrimitive("Every note it blows or draws is in "), JsonPrimitive(0),
                                    JsonPrimitive("$words.")))
        }
        val text = mutableListOf<JsonElement>(JsonPrimitive("Outside "), JsonPrimitive(0), JsonPrimitive("$words: "))
        for ((n, step) in out.withIndex()) {
            if (n > 0) text += JsonPrimitive(", ")
            text += JsonPrimitive(step)
        }
        text += JsonPrimitive(".")
        return JsonArray(text)
    }

    /** A chord's notes (its bass too) as steps above [tonic], the lowest step first. */
    fun chordSteps(chord: Chord, tonic: Int): List<Int> = chord.pitchClasses.map { Math.floorMod(it - tonic, 12) }.sorted()

    /** Each harp's notes, by its key's pitch class: `[blow, draw]`, its ten holes' MIDI notes each. */
    fun layouts(): JsonArray = JsonArray((0 until 12).map { JsonArray(listOf(intsOf(layout(it).blow), intsOf(layout(it).draw))) })

    // --- a hole's note, for a harmonica tab's page ---------------------------------------------------------------

    /**
     * The MIDI note hole [hole] (1 to 10) sounds on the harp in the key of pitch class [harp], blown or drawn
     * ([breath]), bent down [bend] semitones, or overblown ([over]); null for what the harp can't play. A negative
     * [bend] counts from the deepest, as Python's index does (an [IndexOutOfBoundsException] past it).
     */
    fun holeNote(harp: Int, hole: Int, breath: String, bend: Int = 0, over: Boolean = false): Int? {
        if (hole !in 1..HOLES || (breath != "blow" && breath != "draw")) return null
        val layout = layout(Math.floorMod(harp, 12))
        val i = hole - 1
        val blow = layout.blow[i]
        val draw = layout.draw[i]
        if (over) {
            val lower = if (draw > blow) "blow" else "draw"
            return if (breath == lower) maxOf(blow, draw) + 1 else null
        }
        if (bend != 0) {
            val bends = layout.bends[i]
            if (layout.bendBreath[i] != breath || bend > bends.size) return null
            val at = if (bend - 1 < 0) bend - 1 + bends.size else bend - 1
            if (at !in bends.indices) throw IndexOutOfBoundsException("list index out of range")
            return bends[at]
        }
        return if (breath == "blow") blow else draw
    }

    /** Each harp's every note, by its key's pitch class: `blow[i]` and `draw[i]`, hole i + 1's note on that breath
     * and each bend down it has there; `over[i]`, `[breath, note]`, its overblow or overdraw. */
    fun holeTables(): JsonArray = JsonArray((0 until 12).map { harp ->
        val table = linkedMapOf("blow" to ArrayList<JsonElement>(), "draw" to ArrayList(), "over" to ArrayList())
        for (hole in 1..HOLES) {
            for (breath in listOf("blow", "draw")) {
                val notes = arrayListOf(holeNote(harp, hole, breath)!!)
                while (true) notes += holeNote(harp, hole, breath, notes.size) ?: break
                table.getValue(breath).add(intsOf(notes))
            }
            val breath = listOf("blow", "draw").first { holeNote(harp, hole, it, over = true) != null }
            val note = holeNote(harp, hole, breath, over = true)
            table.getValue("over").add(JsonArray(listOf(JsonPrimitive(breath), JsonPrimitive(note))))
        }
        JsonObject(table.mapValuesTo(LinkedHashMap()) { (_, v) -> JsonArray(v) })
    })

    /** The position a harp in [harp] plays a song on [tonic] in, in words, with its mode past the 2nd: "1st
     * position", "4th position, aeolian", "7th position". */
    fun positionText(tonic: Int, harp: Int): String {
        val position = positionOf(tonic, harp)
        val mode = positionMode(position)
        return ordinal(position) + " position" + if (mode != null && position != 1 && position != 2) ", $mode" else ""
    }

    private fun intsOf(xs: List<Int>): JsonArray = JsonArray(xs.map(::JsonPrimitive))
}
