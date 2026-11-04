package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.harmony.Contained
import io.github.danielhp95.caracole.viewer.harmony.Harmony
import io.github.danielhp95.caracole.viewer.harmony.HarmonyProgressions
import io.github.danielhp95.caracole.viewer.harmony.HarmonyTables
import io.github.danielhp95.caracole.viewer.harmony.Numeral
import io.github.danielhp95.caracole.viewer.harmony.Progression
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
 * viewer/harmony.py and viewer/harmony_tables.py (vectors/viewer/harmony_chords.jsonl, the chord half;
 * harmony_progressions.jsonl and harmony_tables.jsonl), every record answered by :viewer as Python answered it:
 * HarmonyTest's, ProgressionsTest's and HarmonyTablesTest's record loops, run on the device by CorpusOnDeviceTest.
 * tests/test_conformance_viewer_harmony.py's docstring says each record's shape: a chord is `[root, quality, bass,
 * shown, tones]` with its trailing nulls left out, a key `[tonic, mode]`, a numeral `[text, accidental, roman, quality,
 * extension, bass, of]`, a relation `[kind, source, target]`, a progression `[numerals, repeats, name, ending,
 * variations, contains]`, a token `[root, third]`, a kept answer `{"value", "sha256"}`.
 */
object HarmonyReplay : AreaReplay {
    override val area = "harmony"

    private const val HELPER = "test_conformance_viewer_harmony."
    private const val CHORDS = "viewer/harmony_chords.jsonl"
    private const val PROGRESSIONS = "viewer/harmony_progressions.jsonl"
    private const val TABLES = "viewer/harmony_tables.jsonl"

    override fun replay(misses: Misses) {
        chords(misses)
        progressions(misses)
        tables(misses)
    }

    /** vectors/viewer/harmony_chords.jsonl: the chord half. */
    fun chords(misses: Misses) {
        everyChordRecordIsHarmonyPys(misses)
    }

    /** vectors/viewer/harmony_progressions.jsonl: a section's progression, its parts, the typed numerals' keys and
     * names, the catalogue's rows and keys. */
    fun progressions(misses: Misses) {
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(PROGRESSIONS)) {
            counts.merge(record.fn, 1, Int::plus)
            val args = record.args
            val out = record.out!!
            when (record.fn) {
                HELPER + "progressions_of" -> {
                    val chords = args[0].jsonArray.map { chord(it)!! }
                    val sections = args[1].jsonArray.map { s ->
                        val (name, played) = s.jsonArray
                        name.jsonPrimitive.content to played.jsonArray.map { if (it is JsonNull) null else chords[it.jsonPrimitive.int] }
                    }
                    val key = key(args[2])!!
                    val got = JsonArray(Harmony.progressions(sections, key).map { (name, p) ->
                        JsonArray(listOf(JsonPrimitive(name), progression(p)))
                    })
                    misses.check(got == out) { "progressions($sections, $key): $got, Python's $out" }
                }
                HELPER + "fold_of" -> each(misses, record) { held ->
                    val f = HarmonyProgressions.fold(strings(held))
                    JsonArray(listOf(strings(f.cycle), JsonPrimitive(f.repeats), JsonPrimitive(f.varied), ints(f.seams)))
                }
                HELPER + "contained_of" -> each(misses, record) { item ->
                    val (held, mode, seams) = item.jsonArray
                    JsonArray(HarmonyProgressions.contained(strings(held), mode.jsonPrimitive.content,
                                                            seams.jsonArray.map { it.jsonPrimitive.int }).map(::contained))
                }
                HELPER + "ending_of" -> each(misses, record) { cores -> HarmonyProgressions.ending(strings(cores)).json() }
                HELPER + "typed_of" -> each(misses, record) { typed ->
                    if (typed is JsonArray) {
                        val numerals = strings(typed)
                        JsonArray(listOf(JsonPrimitive(Harmony.progressionKey(numerals)), Harmony.nameOf(numerals).json(),
                                         strings(Harmony.readTyped(numerals))))
                    } else {
                        val text = typed.jsonPrimitive.content
                        JsonArray(listOf(JsonPrimitive(Harmony.progressionKey(text)), Harmony.nameOf(text).json(),
                                         strings(Harmony.readTyped(text))))
                    }
                }
                HELPER + "core_token_of" -> each(misses, record) { text ->
                    val t = text.jsonPrimitive.content
                    JsonArray(listOf(JsonPrimitive(HarmonyProgressions.core(t)), token(HarmonyProgressions.token(t))))
                }
                HELPER + "rows_of" -> {
                    val mode = args[0].jsonPrimitive.content
                    val got = JsonArray(HarmonyProgressions.rows(mode).map { row ->
                        JsonArray(listOf(JsonPrimitive(row.name), JsonArray(row.tokens.map(::token)), strings(row.numerals),
                                         JsonPrimitive(row.own), JsonPrimitive(row.loops),
                                         JsonArray(row.forms.map { form -> JsonArray(form.map(::token)) })))
                    })
                    misses.check(got == out) { "_rows($mode): $got, Python's $out" }
                }
                HELPER + "catalogue_keys" -> {
                    val got = pairs(Harmony.catalogue())
                    misses.check(got == out) { "catalogue_keys(): $got, Python's $out" }
                }
                HELPER + "name_keys" -> {
                    val got = pairs(HarmonyProgressions.nameKeys())
                    misses.check(got == out) { "_name_keys(): $got, Python's $out" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 9 && counts.getValue(HELPER + "progressions_of") > 500)
    }

    /** vectors/viewer/harmony_tables.jsonl: harmony_tables.tables for a sheet, members and order, and its parts. */
    fun tables(misses: Misses) {
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(TABLES)) {
            counts.merge(record.fn, 1, Int::plus)
            val args = record.args
            val out = record.out!!
            when (record.fn) {
                HELPER + "tables_of" -> {
                    val names = strings(args[0])
                    val key = key(args[1])
                    val places = args[2].jsonArray.map { p -> p.jsonArray.let { it[0].jsonPrimitive.int to it[1].jsonPrimitive.int } }
                    val chords = names.map { Theory.parseChord(it, strict = false) }
                    val tables = if (key == null) {
                        HarmonyTables.tables(chords, null, places, emptyMap(), emptyMap())
                    } else {
                        val (_, mapped, alts) = ShapesReplay.mappedAndAlts(names, key)
                        HarmonyTables.tables(chords, key, places, mapped, alts)
                    }
                    val want = out.jsonObject
                    misses.check(JsonArray(tables.keys.map(::JsonPrimitive)) == want.getValue("order")) {
                        "tables($names, $key)'s members: ${tables.keys}, Python's ${want.getValue("order")}"
                    }
                    for ((member, digest) in want.getValue("sha256").jsonObject) {
                        misses.check(tables[member]?.let(ShapesReplay::sha) == digest.jsonPrimitive.content) {
                            "tables($names, $key)'s $member: ${tables[member].toString().take(400)}"
                        }
                    }
                    want["whole"]?.let { keptIs(misses, "tables($names, $key)", it, tables) }
                }
                HELPER + "parts_of" -> each(misses, record) { text ->
                    JsonArray(HarmonyTables.parts(text.jsonPrimitive.content).map {
                        if (it is String) JsonPrimitive(it) else JsonPrimitive(it as Int)
                    })
                }
                HELPER + "text_of" -> {
                    val texts = strings(args[0])
                    val key = key(args[1])!!
                    keptIs(misses, "text_of($texts, $key)", out, HarmonyTables.textOf(texts, key))
                }
                HELPER + "pitch_class_of" -> each(misses, record) { note -> JsonPrimitive(HarmonyTables.pitchClass(note.jsonPrimitive.content)) }
                HELPER + "page_name_of" -> each(misses, record) { item ->
                    val (c, k, s) = item.jsonArray
                    JsonPrimitive(HarmonyTables.pageName(chord(c)!!, Theory.spelling(key(k)), s.jsonPrimitive.int))
                }
                HELPER + "role_of" -> each(misses, record) { item ->
                    val (c, k) = item.jsonArray
                    JsonPrimitive(HarmonyTables.role(chord(c)!!, key(k)!!))
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 6 && counts.getValue(HELPER + "tables_of") > 40)
    }

    /** Each item of the record's batch (its first argument), its answer and Python's. */
    private fun each(misses: Misses, record: io.github.danielhp95.caracole.core.testing.Record, got: (JsonElement) -> JsonElement) {
        val items = record.args[0].jsonArray
        val want = record.out!!.jsonArray
        misses.check(items.size == want.size) { "${record.fn}: ${items.size} items, ${want.size} answers" }
        for ((i, item) in items.withIndex()) {
            val answer = try {
                got(item)
            } catch (e: Exception) {
                JsonPrimitive("raised ${e.javaClass.simpleName}: ${e.message}")
            }
            misses.check(answer == want[i]) { "${record.fn.removePrefix(HELPER)}($item): $answer, Python's ${want[i]}" }
        }
    }

    /** A kept answer (`{"value", "sha256"}`): its members as Python's, and in Python's order. */
    private fun keptIs(misses: Misses, what: String, want: JsonElement, got: JsonElement) {
        val kept = want.jsonObject
        misses.check(got == kept.getValue("value")) {
            "$what: ${got.toString().take(400)}, Python's ${kept.getValue("value").toString().take(400)}"
        }
        misses.check(ShapesReplay.sha(got) == kept.getValue("sha256").jsonPrimitive.content) {
            "$what: its members' order differs from Python's"
        }
    }

    fun progression(p: Progression): JsonArray = JsonArray(listOf(strings(p.numerals), JsonPrimitive(p.repeats), p.name.json(),
        p.ending.json(), JsonPrimitive(p.variations), JsonArray(p.contains.map(::contained))))

    fun contained(c: Contained): JsonArray =
        JsonArray(listOf(JsonPrimitive(c.name), JsonPrimitive(c.times), strings(c.numerals), JsonPrimitive(c.key)))

    private fun token(t: Pair<Int, String>): JsonArray = JsonArray(listOf(JsonPrimitive(t.first), JsonPrimitive(t.second)))

    private fun pairs(map: Map<String, String>): JsonArray =
        JsonArray(map.map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) })

    private fun strings(e: JsonElement): List<String> = e.jsonArray.map { it.jsonPrimitive.content }

    private fun strings(xs: List<String>): JsonArray = JsonArray(xs.map(::JsonPrimitive))

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
