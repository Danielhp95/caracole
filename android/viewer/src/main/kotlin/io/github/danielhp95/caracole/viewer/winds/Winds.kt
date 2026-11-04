package io.github.danielhp95.caracole.viewer.winds

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.shapes.Kept
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/** winds.Wind: a wind instrument: the lowest and highest notes it reads, how far above them it sounds, the notes it
 * reads at ease (lowest, highest), its keys (or holes) as a fingering's states name them, and its fingering systems,
 * the first its usual one. */
data class Wind(val name: String, val low: Int, val high: Int, val sounds: Int, val easy: Pair<Int, Int>,
                val keys: List<String>, val systems: List<String>)

/** winds.Fingering: a note's fingering: as a chart writes it, and the state of each of the instrument's keys ("x"
 * pressed or covered, "o" not, "h" half). */
data class Fingering(val chart: String, val states: List<String>) {
    /** The states in one string, as the page's data carries them: "xxxxxxxxo". */
    val text: String get() = states.joinToString("")
}

/** winds.Fit: where a melody goes on an instrument: [shift], the whole octaves (in semitones) it sounds the melody
 * above the notes given; [written], the notes it reads; [outside], those of them outside its range. */
data class Fit(val shift: Int, val written: List<Int>, val outside: List<Int>)

/**
 * viewer/winds.py: the concert flute and the soprano recorder: their fingerings (the charts, winds.py's own, as
 * caracole/viewer/winds.json holds them), the octave a melody is played in, and the notes a wind player reads off a
 * chord sheet (the key's scale, each chord's tones); with the tables a viewer's data carries.
 *
 * A chord's tones come in harmony.py's order (`harmony.chord_tones`: by degree, the root, the third, the fifth, the
 * seventh, the ninth…), which [chordSteps] reads from harmony's names of the chord's intervals (`_tone_names`, the
 * bass's `_BASS_DEGREES`): a tone's note is its interval above the root whatever its letter, so the names' numbers
 * alone order them (vectors/viewer/winds.jsonl holds it for every set of intervals).
 *
 * The answers are kept, as Python's caches keep them; a list handed out is a copy.
 */
object Winds {
    private val json: JsonObject by lazy { ViewerData.table("winds") }
    private fun strings(e: JsonElement): List<String> =
        Collections.unmodifiableList(e.jsonArray.map { it.jsonPrimitive.content })
    private fun stringMap(name: String): Map<String, String> =
        Collections.unmodifiableMap(json.getValue(name).jsonObject.mapValuesTo(LinkedHashMap()) { (_, v) -> v.jsonPrimitive.content })

    private val letters: List<String> by lazy { strings(json.getValue("_LETTERS")) }
    /** Each letter's syllable, as Spanish-speaking players read: C is Do. */
    val SOLFEGE: Map<String, String> by lazy { stringMap("SOLFEGE") }
    val FLUTE_KEYS: List<String> by lazy { strings(json.getValue("FLUTE_KEYS")) }
    val RECORDER_HOLES: List<String> by lazy { strings(json.getValue("RECORDER_HOLES")) }
    private val highestStep: Int by lazy { json.getValue("_HIGHEST_STEP").jsonPrimitive.int }
    private val bassDegrees: List<String> by lazy {
        strings(json.getValue("harmony").jsonObject.getValue("_BASS_DEGREES"))
    }

    /** The winds by name: the flute, the recorder. */
    val WINDS: Map<String, Wind> by lazy {
        Collections.unmodifiableMap(json.getValue("WINDS").jsonObject.mapValuesTo(LinkedHashMap()) { (_, v) ->
            val o = v.jsonObject
            fun n(name: String) = o.getValue(name).jsonPrimitive.int
            val (low, high) = o.getValue("easy").jsonArray.map { it.jsonPrimitive.int }
            Wind(o.getValue("name").jsonPrimitive.content, n("low"), n("high"), n("sounds"), low to high,
                 strings(o.getValue("keys")), strings(o.getValue("systems")))
        })
    }
    val FLUTE: Wind get() = WINDS.getValue("flute")
    val RECORDER: Wind get() = WINDS.getValue("recorder")

    /** "C#4" → 61. */
    private fun midi(name: String): Int {
        val letter = letters.indexOf(name.dropLast(1))
        require(letter >= 0) { "${name.dropLast(1)} is not in tuple" }
        return letter + 12 * (name.last() - '0' + 1)
    }

    private val fluteExtras: Map<String, String> by lazy { stringMap("_FLUTE_EXTRAS") }
    private val fluteThumb: Map<String, String?> by lazy {
        json.getValue("_FLUTE_THUMB").jsonObject.mapValues { (_, v) -> (v as? JsonPrimitive)?.takeIf { it.isString }?.content }
    }

    private fun flute(chart: String): Fingering {
        val (left, right) = chart.split("|").also { require(it.size == 2) { "not one bar: $chart" } }
        val leftParts = Py.split(left)
        val rightParts = Py.split(right)
        val thumb = leftParts[0]
        val fingers = leftParts[1]
        val pressed = HashSet<String?>()
        require(thumb in fluteThumb) { thumb }
        pressed += fluteThumb[thumb]
        for (d in fingers) if (d != '-') pressed += "L$d"
        for (d in rightParts[0]) if (d != '-') pressed += "R$d"
        for (k in leftParts.drop(2) + rightParts.drop(1)) pressed += fluteExtras.getValue(k)
        return Fingering(chart, Collections.unmodifiableList(FLUTE_KEYS.map { if (it in pressed) "x" else "o" }))
    }

    private fun recorder(chart: String): Fingering {
        val (left, right) = chart.split("|").also { require(it.size == 2) { "not one bar: $chart" } }
        val leftParts = Py.split(left)
        require(leftParts.size == 2) { chart }
        val (thumb, fingers) = leftParts
        val rightParts = Py.split(right)
        val holes = rightParts[0]
        val states = ArrayList<String>()
        states += when (thumb) { "T" -> "x"; "t" -> "h"; "-" -> "o"; else -> throw NoSuchElementException(thumb) }
        for (c in fingers + holes) states += if (c == '-') "o" else if (c == 'h') "h" else "x"
        states += if (rightParts.size > 1) "x" else "o"
        return Fingering(chart, Collections.unmodifiableList(states))
    }

    private val fingeringsBy: Map<Pair<String, String>, Map<Int, List<Fingering>>> by lazy {
        val flute = json.getValue("_FLUTE_CHART").jsonObject
        val recorder = stringMap("_RECORDER_CHART")
        val german = stringMap("_GERMAN")
        mapOf(
            ("flute" to "boehm") to flute.entries.associate { (n, charts) -> midi(n) to charts.jsonArray.map { flute(it.jsonPrimitive.content) } },
            ("recorder" to "baroque") to recorder.entries.associate { (n, c) -> midi(n) to listOf(recorder(c)) },
            ("recorder" to "german") to recorder.entries.associate { (n, c) -> midi(n) to listOf(recorder(german[n] ?: c)) },
        )
    }

    /** The fingerings of [note] (as the instrument reads it) on [wind] in [system] (its first by default, an empty
     * name too, as Python's `system or …`), the standard one first; none for a note outside its range. An unknown
     * system is an [IllegalArgumentException]. */
    fun fingerings(wind: Wind, note: Int, system: String? = null): List<Fingering> {
        val chosen = system?.takeIf { it.isNotEmpty() } ?: wind.systems[0]
        require(chosen in wind.systems) { "the ${wind.name} has no $chosen fingering" }
        return ArrayList(fingeringsBy.getValue(wind.name to chosen)[note] ?: emptyList())
    }

    // --- the octave a melody is played in ------------------------------------------------------------------------

    private val fits = Kept<Pair<List<Int>, Wind>, Fit>(1024)

    /** The octave a melody (its notes as they sound, or its lowest and highest) is played in on [wind]: as few of the
     * notes it then reads as can be outside its range, then outside its easy range, then moved as little as can be
     * (up rather than down). */
    fun fit(notes: List<Int>, wind: Wind): Fit = fits.getOrPut(ArrayList(notes) to wind) {
        fun cost(shift: Int): List<Int> {
            val read = notes.map { it + shift - wind.sounds }
            return listOf(read.count { it !in wind.low..wind.high }, read.count { it !in wind.easy.first..wind.easy.second },
                          Math.abs(shift), -shift)
        }
        var best = -48
        var bestCost = cost(best)
        for (shift in -36..48 step 12) {
            val c = cost(shift)
            if (compare(c, bestCost) < 0) {
                best = shift
                bestCost = c
            }
        }
        val written = notes.map { it + best - wind.sounds }
        Fit(best, Collections.unmodifiableList(written), Collections.unmodifiableList(written.filter { it !in wind.low..wind.high }))
    }

    private fun compare(a: List<Int>, b: List<Int>): Int {
        for (i in a.indices) if (a[i] != b[i]) return a[i].compareTo(b[i])
        return 0
    }

    // --- off a chord sheet ---------------------------------------------------------------------------------------

    /** The key's scale as a flute and a recorder read it: from its tonic in C4 to B4 up to the tonic's octave. */
    fun scaleNotes(key: Key): List<Int> {
        val tonic = 60 + Math.floorMod(key.tonic, 12)
        return Theory.SCALES.getValue(key.mode).map { tonic + it } + (tonic + 12)
    }

    private val steps = Kept<Pair<Set<Int>, Int?>, List<Int>>(1024)

    /** The chord's tones as semitones above its root, in harmony.chord_tones' order, each above the one before, an
     * 11th or a 13th an octave lower: C9 is [0, 4, 7, 10, 14], C11 [0, 4, 7, 10, 14, 5]. */
    fun chordSteps(chord: Chord): List<Int> = ArrayList(kept(chord))

    private fun kept(chord: Chord): List<Int> {
        val bass = chord.bass?.let { Math.floorMod(it - chord.root, 12) }
        return steps.getOrPut(chord.intervals to bass) {
            val intervals = chord.intervals
            val tones = intervals.map { toneName(it, intervals) to it }.toMutableList()
            if (bass != null && bass !in intervals) tones += bassDegrees[bass] to bass
            tones.sortWith(compareBy({ number(it.first) }, { it.second }))
            val out = ArrayList<Int>()
            for ((_, pc) in tones) out += if (out.isEmpty()) pc else out.last() + Math.floorMod(pc - out.last(), 12).let { if (it == 0) 12 else it }
            Collections.unmodifiableList(out.map { if (it > highestStep) it - 12 else it })
        }
    }

    /** harmony._tone_names: an interval of the chord by its name, "R", "♭3", "5", "♭7", "9"…. A copy of harmony.py's,
     * until lane harmony's viewer.harmony.Harmony ports `_tone_names` (and `_number`, below): then this reads that
     * one. vectors/viewer/winds.jsonl's `interval_steps_of` replays every set of intervals, so the two can't drift. */
    private fun toneName(i: Int, iv: Set<Int>): String {
        val seventh = 10 in iv || 11 in iv
        val third = 3 in iv || 4 in iv
        val diminished = 3 in iv && 6 in iv && 7 !in iv && !seventh
        return when (i) {
            0 -> "R"
            1 -> if (seventh) "♭9" else "♭2"
            2 -> if (seventh || third) "9" else "2"
            3 -> if (4 in iv) "♯9" else "♭3"
            4 -> "3"
            5 -> if (third) "11" else "4"
            6 -> if (7 in iv) "♯11" else "♭5"
            7 -> "5"
            8 -> if (7 in iv) "♭13" else "♯5"
            9 -> if (diminished) "♭♭7" else if (seventh) "13" else "6"
            10 -> "♭7"
            11 -> "7"
            else -> throw NoSuchElementException("no interval $i")
        }
    }

    /** harmony._number: a name's degree, 1 for the root. */
    private fun number(label: String): Int = if (label == "R") 1 else label.trimStart('♭', '♯').toInt()

    /** The chord's tones as a flute and a recorder read them: the root in C4 to B4, then [chordSteps] above it. */
    fun chordNotes(chord: Chord): List<Int> = kept(chord).map { 60 + chord.root + it }

    /** A note's name in solfège, its sharps or flats kept: "C" Do, "Bb" Sib, "F#" Fa#. */
    fun solfege(name: String): String {
        val first = Py.slice(name, 0, 1)
        if (first.isEmpty()) throw IndexOutOfBoundsException("string index out of range")
        return (SOLFEGE[first] ?: throw NoSuchElementException(first)) + Py.slice(name, 1, null)
    }

    // --- the tables a viewer's data carries ----------------------------------------------------------------------

    private val fingeringTable: JsonObject by lazy {
        val low = minOf(FLUTE.low, RECORDER.low)
        val recorder = linkedMapOf<String, JsonElement>("holes" to JsonArray(RECORDER.keys.map(::JsonPrimitive)))
        for (system in RECORDER.systems) {
            recorder[system] = JsonArray((low..RECORDER.high).map { JsonPrimitive(fingerings(RECORDER, it, system)[0].text) })
        }
        JsonObject(linkedMapOf(
            "low" to JsonPrimitive(low),
            "flute" to JsonObject(linkedMapOf(
                "keys" to JsonArray(FLUTE.keys.map(::JsonPrimitive)),
                "notes" to JsonArray((low..FLUTE.high).map { n -> JsonArray(fingerings(FLUTE, n).map { JsonPrimitive(it.text) }) }),
            )),
            "recorder" to JsonObject(recorder),
            "solfege" to JsonObject(SOLFEGE.mapValuesTo(LinkedHashMap()) { (_, v) -> JsonPrimitive(v) }),
        ))
    }

    /** The fingerings the page carries, the same for every page: `{"low": 60, "flute": {"keys", "notes"},
     * "recorder": {"holes", "baroque", "german"}, "solfege"}`. */
    fun fingeringData(): JsonObject = fingeringTable

    /** The tables for a sheet whose chords are [chords], in [key], with each mode's chords and their alternatives
     * [mapped] and [alts] as the page's data has them: `windForms`, `windChords` and `windAlts`. With no key, the
     * sheet's own chords alone, under the mode "". */
    fun tables(chords: List<Chord?>, key: Key?, mapped: Map<String, List<Chord?>>,
               alts: Map<String, List<List<Chord>>>): JsonObject {
        val forms = ArrayList<JsonElement>()
        val known = HashMap<List<Int>, Int>()
        fun form(chord: Chord?): JsonElement {
            if (chord == null) return JsonNull
            val steps = chordSteps(chord)
            val index = known.getOrPut(steps) { forms.size }
            if (index == forms.size) forms.add(JsonArray(steps.map(::JsonPrimitive)))
            return JsonPrimitive(index)
        }
        val windChords = LinkedHashMap<String, JsonElement>()
        val windAlts = LinkedHashMap<String, JsonElement>()
        if (key == null) {
            windChords[""] = JsonArray(chords.map(::form))
        } else {
            for (mode in Theory.MODES) {
                windChords[mode] = JsonArray(mapped.getValue(mode).map(::form))
                windAlts[mode] = JsonArray(alts.getValue(mode).map { o -> JsonArray(o.map(::form)) })
            }
        }
        return JsonObject(linkedMapOf("windForms" to JsonArray(forms), "windChords" to JsonObject(windChords),
                                      "windAlts" to JsonObject(windAlts)))
    }
}
