package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap

/** instruments.Instrument: an instrument the viewer draws chords for, field for field (instruments.py's docstring
 * says each). */
data class Instrument(val id: String, val name: String, val kind: String, val tuning: List<Int> = emptyList(),
                      val capo: Boolean = true, val shapes: String = "", val easy: String? = null,
                      val voice: String = "guitar", val sounds: Int = 0, val offset: Int = 0, val about: String = "",
                      val tab: String = "")

/**
 * viewer/instruments.py: the instruments the viewer draws a sheet's chords for (guitar, the ukuleles, piano,
 * harmonica, flute, recorder), their easy keys, and each one's shapes of a chord: the ukuleles' chords-db's
 * (voicings-ukulele.json, filed by the guitar's keys), the piano's computed from the chord's notes.
 *
 * [INSTRUMENTS], [EASY] and the piano's ranges are instruments.py's own, as tests/test_conformance_viewer_shapes.py
 * wrote them into caracole/viewer/instruments.json. What a page's data carries is [pageVoicings] and [entries], their
 * members in Python's order.
 */
object Instruments {
    private val json: JsonObject by lazy { ViewerData.table("instruments") }

    /** The instruments by id, in the menu's order. */
    val INSTRUMENTS: Map<String, Instrument> by lazy {
        val out = LinkedHashMap<String, Instrument>()
        for (e in json.getValue("INSTRUMENTS").jsonArray) {
            val o = e.jsonObject
            fun s(name: String) = o.getValue(name).jsonPrimitive.content
            val inst = Instrument(
                id = s("id"), name = s("name"), kind = s("kind"),
                tuning = Collections.unmodifiableList(o.getValue("tuning").jsonArray.map { it.jsonPrimitive.int }),
                capo = o.getValue("capo").jsonPrimitive.boolean, shapes = s("shapes"),
                easy = (o.getValue("easy") as? JsonPrimitive)?.takeIf { it.isString }?.content,
                voice = s("voice"), sounds = o.getValue("sounds").jsonPrimitive.int,
                offset = o.getValue("offset").jsonPrimitive.int, about = s("about"), tab = s("tab"),
            )
            out[inst.id] = inst
        }
        Collections.unmodifiableMap(out)
    }

    val GUITAR: Instrument get() = INSTRUMENTS.getValue("guitar")
    val UKULELE: Instrument get() = INSTRUMENTS.getValue("ukulele")
    val UKULELE_LOW_G: Instrument get() = INSTRUMENTS.getValue("ukulele-low-g")
    val BARITONE: Instrument get() = INSTRUMENTS.getValue("baritone")
    val PIANO: Instrument get() = INSTRUMENTS.getValue("piano")
    val HARMONICA: Instrument get() = INSTRUMENTS.getValue("harmonica")
    val FLUTE: Instrument get() = INSTRUMENTS.getValue("flute")
    val RECORDER: Instrument get() = INSTRUMENTS.getValue("recorder")

    /** The instrument an address names (`inst=ukulele`), the guitar for none or one caracole has not. */
    fun instrument(name: String?): Instrument = INSTRUMENTS[name ?: ""] ?: GUITAR

    /** EASY: each table's tonics of its easy major keys, then of its easy minor ones. */
    val EASY: Map<String, Pair<List<Int>, List<Int>>> by lazy {
        val out = LinkedHashMap<String, Pair<List<Int>, List<Int>>>()
        for ((table, keys) in json.getValue("EASY").jsonObject) {
            val (majors, minors) = keys.jsonArray.map { side ->
                Collections.unmodifiableList(side.jsonArray.map { it.jsonPrimitive.int })
            }
            out[table] = majors to minors
        }
        Collections.unmodifiableMap(out)
    }

    /** Whether [key] is easy on the instruments of [table]: a major or minor key by its tonic, another mode by its
     * notes, those of an easy major key (D dorian's are C major's). */
    fun isEasy(table: String, key: Key): Boolean {
        val (majors, minors) = EASY[table] ?: throw NoSuchElementException(table)
        if (key.mode == "ionian") return key.tonic in majors
        if (key.mode == "aeolian") return key.tonic in minors
        val degree = Theory.MODES.indexOf(key.mode)
        require(degree >= 0) { "'${key.mode}' is not in list" }
        return Math.floorMod(key.tonic - Theory.SCALES.getValue("ionian")[degree], 12) in majors
    }

    private val easy = ConcurrentHashMap<String, JsonObject>()

    /** The easy keys of [table] in every mode, as the page's data gives them (`easy[table][mode]`): each `[tonic,
     * name]`, in the order of the pitch classes. */
    fun easyKeys(table: String): JsonObject = easy.getOrPut(table) {
        JsonObject(Theory.MODES.associateWithTo(LinkedHashMap()) { mode ->
            JsonArray((0 until 12).filter { isEasy(table, Key(it, mode)) }.map {
                JsonArray(listOf(JsonPrimitive(it), JsonPrimitive(Theory.keyName(Key(it, mode)))))
            })
        })
    }

    // --- the ukuleles' shapes ------------------------------------------------------------------------------------

    /** The quality the ukulele shows for a chord the guitar files under [fingering] (Voicings.voicingKeys): the same
     * where the ukulele file has it, else its nearest: C5 is C, C9 C7. */
    fun ukuleleQuality(fingering: String): String {
        val data = Voicings.loadVoicings("ukulele")
        if (fingering in data) return fingering
        val chord = if (fingering in Theory.QUALITIES) Chord(0, fingering) else Chord(0, "")
        return Voicings.nearest(chord, data.keys)
    }

    /** The ukulele's shapes for a chord the guitar files under [fingering], on every root (C first). */
    fun ukuleleShapes(fingering: String): List<List<Position>> =
        Voicings.loadVoicings("ukulele").getValue(ukuleleQuality(fingering))

    // --- the piano's ---------------------------------------------------------------------------------------------

    /** The right hand's lowest note and its highest start (F3 to E4), and the left hand's bass (F2 to E3). */
    val LOW: Int by lazy { json.getValue("LOW").jsonPrimitive.int }
    val HIGH: Int by lazy { json.getValue("HIGH").jsonPrimitive.int }
    val BASS: Int by lazy { json.getValue("BASS").jsonPrimitive.int }

    /** The chord's intervals as a pianist stacks them up from the root: the third (or a sus chord's second or
     * fourth), the fifth, the seventh or sixth, then what is left above the octave. */
    fun stacked(chord: Chord): List<Int> {
        val intervals = chord.intervals
        fun first(vararg options: Int): Int? = options.firstOrNull { it in intervals }
        val third = first(4, 3) ?: first(5, 2)
        val fifth = first(7, 6, 8)
        val seventh = first(10, 11, 9)
        val ranks = HashMap<Int, Int>()
        ranks[0] = 0
        for ((i, rank) in listOf(third to 1, fifth to 2, seventh to 3)) if (i != null) ranks[i] = rank
        return intervals.sortedWith(compareBy<Int>({ ranks[it] ?: 4 }, { if (it in ranks) it else it + 12 }))
    }

    /** The piano's positions of [chord], each `[bass, *right hand]` as MIDI notes, low to high: root position, then
     * its first and second inversions, each moved by octaves so its lowest note is from F3 to E4; the bass, the
     * root or a slash chord's bass, from F2 to E3. */
    fun pianoPositions(chord: Chord): List<List<Int>> {
        val rootPosition = ArrayList<Int>()
        for (interval in stacked(chord)) {
            val pc = Math.floorMod(chord.root + interval, 12)
            if (rootPosition.isEmpty()) {
                rootPosition += LOW + Math.floorMod(pc - LOW, 12)
            } else {
                val last = rootPosition.last()
                rootPosition += last + Math.floorMod(pc - last, 12).let { if (it == 0) 12 else it }
            }
        }
        val positions = arrayListOf<List<Int>>(rootPosition)
        repeat(minOf(3, rootPosition.size) - 1) {
            val before = positions.last()
            val moved = (before.drop(1) + (before[0] + 12)).sorted()
            val octaves = -12 * Math.floorDiv(moved[0] - LOW, 12)
            positions += moved.map { it + octaves }
        }
        val low = chord.bass ?: chord.root
        val bass = BASS + Math.floorMod(low - BASS, 12)
        return positions.map { listOf(bass) + it }
    }

    /** Where the page's `voicings` file a chord's piano positions on every root: "piano:", its suffix as shown, "|"
     * and its bass's interval above the root, if any ("piano:m7|", "piano:|4" for C/E). */
    fun pianoKey(chord: Chord): String =
        "piano:${chord.suffix}|${chord.bass?.let { Math.floorMod(it - chord.root, 12) } ?: ""}"

    /** [chord] with [root] as its root, its bass moved with it. */
    fun onRoot(chord: Chord, root: Int): Chord =
        if (chord.bass == null) chord.copy(root = root)
        else chord.copy(root = root, bass = Math.floorMod(chord.bass - chord.root + root, 12))

    private val pianoTables = Kept<Chord, List<List<List<Int>>>>(4096)

    /** The piano's positions of [chord]'s kind on every root (C first): a copy of the answer kept. */
    fun pianoTable(chord: Chord): List<List<List<Int>>> =
        kept(chord).map { positions -> positions.map { ArrayList(it) } }

    private fun kept(chord: Chord): List<List<List<Int>>> = pianoTables.getOrPut(chord) {
        (0 until 12).map { pianoPositions(onRoot(chord, it)) }
    }

    // --- what a chord shows, and what a page carries -----------------------------------------------------------

    /** The shapes the viewer shows [chord] moved [shift] semitones on [inst] (viewer.js `shapesOf`): on the guitar
     * the shapes the sheet gives that very chord first ([given]: Voicings.sheetShapes), else chords-db's for its
     * slash chord, else for its quality; on a ukulele the ukulele's for its quality; on the piano its positions. */
    fun chordShapes(inst: Instrument, chord: Chord, shift: Int = 0, given: JsonObject? = null): JsonArray {
        val root = Math.floorMod(chord.root + shift, 12)
        if (inst.kind == "keys") return ints2(pianoPositions(onRoot(chord, root)))
        val (fingering, _, slash) = Voicings.voicingKeys(chord)
        if (inst.shapes == "ukulele:") return JsonArray(ukuleleShapes(fingering)[Math.floorMod(root + inst.offset, 12)])
        val shown = "$root,${chord.suffix},${chord.bass?.let { Math.floorMod(it + shift, 12) } ?: ""}"
        if (!given.isNullOrEmpty() && shown in given) return given.getValue(shown).jsonObject.getValue("list").jsonArray
        val data = Voicings.loadVoicings()
        if (slash != null && slash in data && data.getValue(slash)[root].isNotEmpty()) {
            return JsonArray(data.getValue(slash)[root])
        }
        return JsonArray(data[fingering]?.get(root) ?: emptyList())
    }

    /** What the instruments add to a page's `voicings`, beside the guitar's (Voicings.pageVoicings): the ukulele's
     * shapes of each quality it shows for a guitar key of the page's ([fingerings]; a slash key has none) under
     * "ukulele:", and for each chord's kind ([chords]) the piano's positions ([pianoKey]), each on every root. */
    fun pageVoicings(fingerings: Set<String>, chords: List<Chord>): JsonObject {
        val out = LinkedHashMap<String, JsonElement>()
        val uke = Voicings.rawVoicings("ukulele")
        for (fingering in fingerings.sortedWith(Py.CODE_POINT_ORDER)) {
            if ('/' !in fingering) {
                val quality = ukuleleQuality(fingering)
                out["ukulele:$quality"] = uke.getValue(quality)
            }
        }
        for (chord in chords) {
            out.getOrPut(pianoKey(chord)) { JsonArray(kept(onRoot(chord, 0)).map(::ints2)) }
        }
        return JsonObject(out)
    }

    /** The instruments as the page's data lists them (`instruments`), in the menu's order: each one's fields, a
     * fretted one's `tuning`, and for a ukulele `near`: each guitar key of [fingerings] it shows as another quality,
     * with that quality. */
    fun entries(fingerings: Set<String>): JsonArray {
        val sorted = fingerings.sortedWith(Py.CODE_POINT_ORDER)
        return JsonArray(INSTRUMENTS.values.map { inst ->
            val entry = linkedMapOf<String, JsonElement>(
                "id" to JsonPrimitive(inst.id), "name" to JsonPrimitive(inst.name), "kind" to JsonPrimitive(inst.kind),
                "capo" to JsonPrimitive(inst.capo), "shapes" to JsonPrimitive(inst.shapes),
                "offset" to JsonPrimitive(inst.offset), "easy" to (inst.easy?.let(::JsonPrimitive) ?: JsonNull),
                "voice" to JsonPrimitive(inst.voice), "sounds" to JsonPrimitive(inst.sounds),
                "about" to JsonPrimitive(inst.about), "tab" to JsonPrimitive(inst.tab.ifEmpty { inst.name }),
            )
            if (inst.tuning.isNotEmpty()) entry["tuning"] = JsonArray(inst.tuning.map(::JsonPrimitive))
            if (inst.shapes == "ukulele:") {
                val near = LinkedHashMap<String, JsonElement>()
                for (f in sorted) {
                    if ('/' in f) continue
                    val q = ukuleleQuality(f)
                    if (q != f) near[f] = JsonPrimitive(q)
                }
                entry["near"] = JsonObject(near)
            }
            JsonObject(entry)
        })
    }

    private fun ints2(rows: List<List<Int>>): JsonArray = JsonArray(rows.map { row -> JsonArray(row.map(::JsonPrimitive)) })
}
