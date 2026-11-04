package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * viewer/harmony_tables.py: what harmony.py says of a sheet, as the tables a viewer's data carries (page.py `_data`),
 * for viewer.js to look up. Its docstring is the tables' format: per mode, by reading (a chord read otherwise somewhere
 * gets one more, which `places` names for that place), `numerals`, `families`, `relations`, `explains` (a **text**,
 * written for every transposition: a string, a list of strings and pitch classes, or `{"by": [12 texts]}`),
 * `altNumerals`, `solo` and `altSolo`, `keyScale`, `pentatonic`, `pentatonicName` and `progressions`; and for every
 * mode alike `tones`, `tuning`, `scaleWords` and `scales`.
 *
 * Every object is built in Python's insertion order (a key set again keeps its place, as a dict's does), a chord's
 * reading the one most of its places have (Counter.most_common's first, ties to the first seen), so that
 * `PyJson.dumps` writes the bytes `json.dumps` writes. Its patterns are harmony_tables.py's own ([HarmonyData]).
 */
object HarmonyTables {
    /** SHIFTS: the twelve transpositions, 0 to 11 semitones up. */
    val SHIFTS: IntRange = 0 until 12

    /** shifted: [chord] [s] semitones up. */
    fun shifted(chord: Chord?, s: Int): Chord? {
        if (chord == null || s == 0) return chord
        return chord.copy(root = Math.floorMod(chord.root + s, 12), bass = chord.bass?.let { Math.floorMod(it + s, 12) })
    }

    /** pitch_class: the pitch class of a note as harmony.chord_tones spells it: its letter's, and a semitone for each
     * sharp or flat after it ("B#" 0, "Fbb" 3). */
    fun pitchClass(note: String): Int {
        val letter = Py.slice(note, 0, 1)
        val rest = Py.slice(note, 1, null)
        return Math.floorMod(Theory.notePc(letter) + note.count { it == '#' } + note.count { it == '♯' } -
                                 rest.count { it == 'b' } - note.count { it == '♭' }, 12)
    }

    /** page_name: the chord [s] semitones up as viewer.js's `nameOf` names it, with [names] (theory.spelling of the
     * key shown). */
    fun pageName(chord: Chord, names: List<String>, s: Int = 0): String {
        val bass = chord.bass?.let { "/" + names[Math.floorMod(it + s, 12)] } ?: ""
        return names[Math.floorMod(chord.root + s, 12)] + chord.suffix + bass
    }

    /** _parts: [text] cut at each note it names: its other words (strings), and each note's pitch class (an Int). */
    fun parts(text: String): List<Any> {
        val out = ArrayList<Any>()
        var at = 0
        for (m in PyRe.finditer(HarmonyData.note, text)) {
            val letter = m.groupValues[1]
            var accidental = m.groupValues[2]
            var end = m.range.last + 1
            if (accidental.isNotEmpty() && HarmonyData.afterNote.matchAt(text, end) == null) {  // "Bb" in "Bbass"
                accidental = ""
                end = m.range.first + 1
            }
            if (HarmonyData.afterNote.matchAt(text, end) == null) continue  // a word: "Dorian"
            out.add(text.substring(at, m.range.first))
            out.add(Theory.notePc(letter, accidental))
            at = end
        }
        out.add(text.substring(at))
        return out.filter { it != "" }
    }

    /** fill: a text's parts on the transposition [s], each pitch class named by [names], as viewer.js does. */
    fun fill(parts: List<Any>, names: List<String>, s: Int): String =
        parts.joinToString("") { if (it is Int) names[Math.floorMod(it + s, 12)] else it as String }

    /** text_of: the texts of one line on every transposition (`texts[s]`, in [key] s semitones up) as a **text**. */
    fun textOf(texts: List<String>, key: Key): JsonElement {
        if (texts.all { it == texts[0] }) return JsonPrimitive(texts[0])
        val parts = parts(texts[0])
        if (SHIFTS.all { s -> fill(parts, Theory.spelling(Key(Math.floorMod(key.tonic + s, 12), key.mode)), s) == texts[s] }) {
            return JsonArray(parts.map { if (it is Int) JsonPrimitive(it) else JsonPrimitive(it as String) })
        }
        return JsonObject(mapOf("by" to JsonArray(texts.map(::JsonPrimitive))))
    }

    /** role: a chord's role in one letter: its family's first ("h", "a", "p"), else its relation's ("b", "s", "l",
     * "o"). */
    fun role(chord: Chord, key: Key): String =
        Py.slice(HarmonyChords.family(chord, key) ?: HarmonyChords.relation(chord, key, null).kind, 0, 1)

    private fun numeral(n: Numeral): JsonArray = JsonArray(listOf(JsonPrimitive(n.text), JsonPrimitive(n.accidental),
        JsonPrimitive(n.roman), JsonPrimitive(n.quality), JsonPrimitive(n.extension), n.bass.json(), n.of.json()))

    /**
     * The tables for a sheet whose chords are [chords] (by index) and whose places are [places], each (chord index,
     * section) in the page's order (section -1 for the notes before the song, no part of its progressions), in [key];
     * [mapped] and [alts] are each mode's chords and alternatives, as the page's data has them. With no key, `tones`
     * alone.
     */
    fun tables(chords: List<Chord?>, key: Key?, places: List<Pair<Int, Int>>, mapped: Map<String, List<Chord?>>,
               alts: Map<String, List<List<Chord>>>): JsonObject {
        val tones = LinkedHashMap<String, JsonElement>()

        fun addTones(chord: Chord?, modeKey: Key?) {
            if (chord == null) return
            for (s in SHIFTS) {
                val shown = modeKey?.let { Key(Math.floorMod(it.tonic + s, 12), it.mode) }
                val name = pageName(chord, Theory.spelling(shown), s)
                if (name !in tones) {
                    val found = HarmonyChords.chordTones(shifted(chord, s)!!, shown)
                    tones[name] = JsonPrimitive(listOf(found.joinToString(" ") { it.first }, found.joinToString(" ") { it.second },
                                                       found.joinToString(" ") { pitchClass(it.first).toString() }).joinToString("|"))
                }
            }
        }

        if (key == null) {
            for (chord in chords) addTones(chord, null)
            return JsonObject(mapOf("tones" to JsonObject(tones)))
        }
        val members = listOf("numerals", "families", "relations", "explains", "places", "altNumerals", "solo", "altSolo",
                             "keyScale", "pentatonic", "pentatonicName", "progressions")
        val byMode = members.associateWith { LinkedHashMap<String, JsonElement>() }
        val words = ArrayList<String>()
        val scales = LinkedHashMap<String, JsonElement>()
        val sections = places.map { it.second }.filter { it >= 0 }.toSortedSet().toList()

        fun solo(chord: Chord, modeKey: Key): Int {
            val name = HarmonyChords.soloScale(chord, modeKey).first
            val space = name.indexOf(' ')
            if (space < 0) throw IndexOutOfBoundsException("a scale's name with no word after its root: $name")
            val word = name.substring(space + 1)
            if (word !in words) words.add(word)
            for (s in SHIFTS) {
                val shown = Key(Math.floorMod(modeKey.tonic + s, 12), modeKey.mode)
                val full = Theory.spelling(shown)[Math.floorMod(chord.root + s, 12)] + " " + word
                if (full !in scales) {
                    val (scale, notes) = HarmonyChords.soloScale(shifted(chord, s)!!, shown)
                    scales[full] = JsonPrimitive(scale + "|" + notes.joinToString(" "))
                }
            }
            return words.indexOf(word)
        }

        for (mode in Theory.MODES) {
            val modeKey = Key(key.tonic, mode)
            val here = mapped.getValue(mode)
            val options = alts.getValue(mode)
            // (place, chord index, section) for each chord played in a section of the song.
            val played = places.withIndex().filter { (_, p) -> p.second >= 0 && here[p.first] != null }
                .map { (k, p) -> Triple(k, p.first, p.second) }
            val goes = HarmonyChords.goesTo(played.map { here[it.second]!! })
            val after = HashMap<Int, Chord?>()
            for ((j, place) in played.withIndex()) after[place.first] = goes[j]
            // Each chord read as most of its places read it (the first of those, in a tie), or with no chord after it.
            val heard = HashMap<Int, LinkedHashMap<String, Int>>()
            val goesFor = HashMap<Pair<Int, String>, Chord?>()
            for ((k, i, _) in played) {
                val line = HarmonyChords.explain(here[i]!!, modeKey, after[k])
                heard.getOrPut(i) { LinkedHashMap() }.merge(line, 1, Int::plus)
                if (!goesFor.containsKey(i to line)) goesFor[i to line] = after[k]
            }
            val readings = ArrayList<Pair<Chord?, Chord?>>()
            for ((i, chord) in here.withIndex()) {
                val lines = heard[i]
                readings.add(chord to if (lines == null) null else goesFor.getValue(i to commonest(lines)))
            }
            val lines = readings.map { (c, g) -> c?.let { HarmonyChords.explain(it, modeKey, g) } }.toMutableList()
            val byPlace = LinkedHashMap<Int, Int>()
            for ((k, i, _) in played) {
                val line = HarmonyChords.explain(here[i]!!, modeKey, after[k])
                if (line != lines[i]) {
                    if (line !in lines.subList(here.size, lines.size)) {
                        readings.add(here[i] to after[k])
                        lines.add(line)
                    }
                    byPlace[k] = here.size + lines.subList(here.size, lines.size).indexOf(line)
                }
            }
            byMode.getValue("numerals")[mode] = JsonArray(readings.map { (c, g) ->
                if (c == null) JsonNull else numeral(HarmonyChords.numeral(c, modeKey, g))
            })
            byMode.getValue("families")[mode] = JsonArray(readings.map { (c, _) ->
                if (c == null) JsonNull else HarmonyChords.family(c, modeKey).json()
            })
            byMode.getValue("relations")[mode] = JsonArray(readings.map { (c, g) ->
                if (c == null) JsonNull else JsonPrimitive(HarmonyChords.relation(c, modeKey, g).kind)
            })
            byMode.getValue("explains")[mode] = JsonArray(readings.map { (c, g) ->
                if (c == null) JsonNull else textOf(SHIFTS.map { s ->
                    HarmonyChords.explain(shifted(c, s)!!, Key(Math.floorMod(key.tonic + s, 12), mode), shifted(g, s))
                }, modeKey)
            })
            byMode.getValue("places")[mode] = JsonObject(byPlace.entries.associate { (k, r) -> k.toString() to JsonPrimitive(r) })
            byMode.getValue("altNumerals")[mode] = JsonArray(options.map { offered ->
                JsonArray(offered.map { a -> JsonPrimitive(role(a, modeKey) + HarmonyChords.numeral(a, modeKey, null).text) })
            })
            byMode.getValue("solo")[mode] = JsonArray(here.map { c -> if (c == null) JsonNull else JsonPrimitive(solo(c, modeKey)) })
            byMode.getValue("altSolo")[mode] = JsonArray(options.map { offered -> JsonArray(offered.map { JsonPrimitive(solo(it, modeKey)) }) })
            for (c in here) addTones(c, modeKey)
            for (offered in options) for (a in offered) addTones(a, modeKey)
            byMode.getValue("keyScale")[mode] = ints(HarmonyChords.keyScale(modeKey).map { Math.floorMod(it - key.tonic, 12) })
            val box = HarmonyChords.pentatonic(modeKey).map { Math.floorMod(it - key.tonic, 12) }
            byMode.getValue("pentatonic")[mode] = ints(box)
            byMode.getValue("pentatonicName")[mode] = JsonPrimitive(if (4 in box) "major pentatonic" else "minor pentatonic")
            byMode.getValue("progressions")[mode] = progressions(sections, played, here, after, modeKey)
        }
        val out = LinkedHashMap<String, JsonElement>()
        out["tones"] = JsonObject(tones)
        for (member in members) out[member] = JsonObject(byMode.getValue(member))
        out["tuning"] = ints(Voicings.TUNING.map { Math.floorMod(it, 12) })
        out["scaleWords"] = JsonArray(words.map(::JsonPrimitive))
        out["scales"] = JsonObject(scales)
        return JsonObject(out)
    }

    /** _progressions: each section's `[section, numerals, repeats, name, ending, key, chords, variations, contains]`,
     * its chords read as [tables] reads them. */
    private fun progressions(sections: List<Int>, played: List<Triple<Int, Int, Int>>, here: List<Chord?>,
                             after: Map<Int, Chord?>, key: Key): JsonArray {
        val chordsOf = LinkedHashMap<Int, MutableList<Chord?>>()
        val textsOf = HashMap<Int, MutableList<Pair<Int, String>>>()
        for (n in sections) {
            chordsOf[n] = ArrayList()
            textsOf[n] = ArrayList()
        }
        for ((k, i, n) in played) {
            chordsOf.getValue(n).add(here[i])
            textsOf.getValue(n).add(i to HarmonyChords.numeral(here[i]!!, key, after[k]).text)
        }
        val found = ArrayList<JsonElement>()
        for ((name, p) in HarmonyProgressions.progressions(sections.map { it.toString() to chordsOf.getValue(it) }, key)) {
            val n = name.toInt()
            val texts = textsOf.getValue(n)
            val held = texts.filterIndexed { j, x -> j == 0 || x.second != texts[j - 1].second }
            val words = held.map { it.second }
            val k = p.numerals.size
            // The chords of the cycle where the section first plays it whole (after a pass that varies it, maybe).
            val at = (0..words.size - k).firstOrNull { j -> words.subList(j, j + k) == p.numerals }
            val indexes = at?.let { ints(held.subList(it, it + k).map { h -> h.first }) } ?: JsonNull
            found.add(JsonArray(listOf(JsonPrimitive(n), JsonArray(p.numerals.map(::JsonPrimitive)), JsonPrimitive(p.repeats),
                                       p.name.json(), p.ending.json(), JsonPrimitive(HarmonyProgressions.progressionKey(p.numerals)),
                                       indexes, JsonPrimitive(p.variations),
                                       JsonArray(p.contains.map { c ->
                                           JsonArray(listOf(JsonPrimitive(c.name), JsonPrimitive(c.times), JsonPrimitive(c.key)))
                                       }))))
        }
        return JsonArray(found)
    }

    /** Counter.most_common(1)[0][0]: the line counted most, the first seen of those tied (heapq.nlargest's max). */
    private fun commonest(counts: LinkedHashMap<String, Int>): String {
        var best: String? = null
        var most = 0
        for ((line, n) in counts) if (best == null || n > most) {
            best = line
            most = n
        }
        return best ?: throw NoSuchElementException("no line counted")
    }

    private fun ints(xs: List<Int>): JsonArray = JsonArray(xs.map(::JsonPrimitive))

    private fun String?.json(): JsonElement = this?.let(::JsonPrimitive) ?: JsonNull
}
