package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.harmony.Harmony
import io.github.danielhp95.caracole.viewer.harmony.Numeral
import io.github.danielhp95.caracole.viewer.harmony.Relation
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
import org.junit.Assert.assertTrue
import org.junit.Assert.fail

/**
 * viewer/harmony.py (vectors/viewer/harmony_chords.jsonl: lane harmony's chord half; harmony-progressions adds its
 * progressions and tables), every record answered by :viewer as Python answered it: HarmonyTest's record loop, run on
 * the device by CorpusOnDeviceTest. tests/test_conformance_viewer_harmony.py's docstring says each record's shape: a
 * chord is `[root, quality, bass, shown, tones]` with its trailing nulls left out, a key `[tonic, mode]`, a numeral
 * `[text, accidental, roman, quality, extension, bass, of]`, a relation `[kind, source, target]`.
 */
object HarmonyReplay : AreaReplay {
    override val area = "harmony"

    private const val HELPER = "test_conformance_viewer_harmony."
    private const val CHORDS = "viewer/harmony_chords.jsonl"

    override fun replay(misses: Misses) {
        everyChordRecordIsHarmonyPys(misses)
    }

    private fun everyChordRecordIsHarmonyPys(misses: Misses) {
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(CHORDS)) {
            counts.merge(record.fn, 1, Int::plus)
            val out = record.out!!
            when (record.fn) {
                HELPER + "chord_in_keys" -> chordInKeys(misses, record.args, out.jsonObject)
                HELPER + "in_sequence" -> {
                    val names = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                    val key = key(record.args[1])!!
                    val got = inSequence(names, key)
                    for (part in listOf("goes_to", "numerals", "glossary")) {
                        val want = out.jsonObject.getValue(part)
                        misses.check(got.getValue(part) == want) {
                            "in_sequence($names, $key)'s $part: ${got.getValue(part)}, Python's $want"
                        }
                    }
                }
                HELPER + "tooltips" -> {
                    val chord = chord(record.args[0])!!
                    val key = key(record.args[1])!!
                    val next = chord(record.args[2])
                    val got = JsonArray(tooltips(chord, key, next).map(::JsonPrimitive))
                    misses.check(got == out) { "tooltips($chord, $key, $next): $got, Python's $out" }
                }
                HELPER + "key_scales" -> for (row in out.jsonArray) {
                    val (tonic, mode, wantScale, box) = row.jsonArray
                    val key = Key(tonic.jsonPrimitive.int, mode.jsonPrimitive.content)
                    misses.check(ints(Harmony.keyScale(key)) == wantScale) {
                        "key_scale($key): ${Harmony.keyScale(key)}, Python's $wantScale"
                    }
                    misses.check(ints(Harmony.pentatonic(key)) == box) { "pentatonic($key): ${Harmony.pentatonic(key)}, Python's $box" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts",
                   counts.size == 4 && counts.getValue(HELPER + "chord_in_keys") > 100 &&
                       counts.getValue(HELPER + "in_sequence") > 100)
    }

    private fun chordInKeys(misses: Misses, args: JsonArray, out: JsonObject) {
        val chord = chord(args[0])!!
        val keys = args[1].jsonArray.map { key(it)!! }
        val nexts = args[2].jsonArray.map(::chord)
        val alone = tones(Harmony.chordTones(chord, null))
        misses.check(alone == out.getValue("alone")) { "chord_tones($chord, None): $alone, Python's ${out.getValue("alone")}" }
        val want = out.getValue("in").jsonArray
        for ((i, key) in keys.withIndex()) {
            val (wantFamily, wantTones, wantSolo, wantReads) = want[i].jsonArray
            val gotFamily = Harmony.family(chord, key)?.let(::JsonPrimitive) ?: JsonNull
            misses.check(gotFamily == wantFamily) { "family($chord, $key): $gotFamily, Python's $wantFamily" }
            val gotTones = tones(Harmony.chordTones(chord, key))
            misses.check(gotTones == wantTones) { "chord_tones($chord, $key): $gotTones, Python's $wantTones" }
            val gotSolo = scale(Harmony.soloScale(chord, key))
            misses.check(gotSolo == wantSolo) { "solo_scale($chord, $key): $gotSolo, Python's $wantSolo" }
            for ((j, next) in nexts.withIndex()) {
                val (wantNumeral, wantRelation, wantExplain) = wantReads.jsonArray[j].jsonArray
                val gotNumeral = numeral(Harmony.numeral(chord, key, next))
                misses.check(gotNumeral == wantNumeral) { "numeral($chord, $key, $next): $gotNumeral, Python's $wantNumeral" }
                val gotRelation = relation(Harmony.relation(chord, key, next))
                misses.check(gotRelation == wantRelation) {
                    "relation($chord, $key, $next): $gotRelation, Python's $wantRelation"
                }
                val gotExplain = JsonPrimitive(Harmony.explain(chord, key, next))
                misses.check(gotExplain == wantExplain) { "explain($chord, $key, $next): $gotExplain, Python's $wantExplain" }
            }
        }
    }

    /** The record's `in_sequence`: the chords a sheet plays, read as page.py reads them, in [key]. */
    fun inSequence(names: List<String>, key: Key): Map<String, JsonElement> {
        val played = names.mapNotNull { Theory.parseChord(it, strict = false) }
        val goes = Harmony.goesTo(played)
        return mapOf(
            "goes_to" to JsonArray(goes.map(TheoryReplay::chord)),
            "numerals" to JsonArray(played.zip(goes).map { (c, g) -> JsonPrimitive(Harmony.numeral(c, key, g).text) }),
            "glossary" to JsonArray(Harmony.glossary(played, key).map { (symbol, meaning, example) ->
                JsonArray(listOf(JsonPrimitive(symbol), JsonPrimitive(meaning), JsonPrimitive(example)))
            }),
        )
    }

    /** The tooltip's line on every transposition, as harmony_tables.py writes a text. */
    fun tooltips(chord: Chord, key: Key, next: Chord?): List<String> = (0 until 12).map { s ->
        Harmony.explain(shifted(chord, s)!!, Key(Math.floorMod(key.tonic + s, 12), key.mode), shifted(next, s))
    }

    /** harmony_tables.shifted: [chord] [s] semitones up. */
    fun shifted(chord: Chord?, s: Int): Chord? {
        if (chord == null || s == 0) return chord
        return chord.copy(root = Math.floorMod(chord.root + s, 12), bass = chord.bass?.let { Math.floorMod(it + s, 12) })
    }

    /** A chord as the corpus writes it, `[root, quality, bass, shown, tones]`, its trailing nulls left out. */
    fun chord(e: JsonElement): Chord? {
        if (e is JsonNull) return null
        val row = e.jsonArray
        fun at(i: Int): JsonElement = if (i < row.size) row[i] else JsonNull
        return Chord(
            row[0].jsonPrimitive.int, row[1].jsonPrimitive.content,
            at(2).let { if (it is JsonNull) null else it.jsonPrimitive.int },
            at(3).let { if (it is JsonNull) null else it.jsonPrimitive.content },
            at(4).let { if (it is JsonNull) null else it.jsonArray.map { t -> t.jsonPrimitive.int }.toSet() },
        )
    }

    fun key(e: JsonElement): Key? = TheoryReplay.key(e)

    fun numeral(n: Numeral): JsonArray = JsonArray(listOf(JsonPrimitive(n.text), JsonPrimitive(n.accidental),
        JsonPrimitive(n.roman), JsonPrimitive(n.quality), JsonPrimitive(n.extension), n.bass.json(), n.of.json()))

    fun relation(r: Relation): JsonArray = JsonArray(listOf(JsonPrimitive(r.kind), r.source.json(), r.target.json()))

    private fun tones(found: List<Pair<String, String>>): JsonArray =
        JsonArray(found.map { (note, interval) -> JsonArray(listOf(JsonPrimitive(note), JsonPrimitive(interval))) })

    private fun scale(found: Pair<String, List<String>>): JsonArray =
        JsonArray(listOf(JsonPrimitive(found.first), JsonArray(found.second.map(::JsonPrimitive))))

    private fun ints(xs: List<Int>): JsonArray = JsonArray(xs.map(::JsonPrimitive))

    private fun String?.json(): JsonElement = this?.let(::JsonPrimitive) ?: JsonNull
}
