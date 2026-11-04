package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.shapes.Position
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.winds.Winds
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue

/**
 * viewer/voicings.py, instruments.py, harp.py and winds.py (vectors/viewer/voicings.jsonl, instruments.jsonl,
 * harp_play.jsonl, harp_choices.jsonl, harp_tables.jsonl, winds.jsonl), every record answered by :viewer as Python
 * answered it: the JVM tests' record loops (VoicingsTest, InstrumentsTest, HarpTest, WindsTest), run on the device by
 * CorpusOnDeviceTest. tests/test_conformance_viewer_shapes.py's docstring says each record's shape: a chord is
 * `[root, quality, bass, shown, tones]` with its trailing nulls left out, a key `[tonic, mode]`, `{"err": …}` an
 * answer Python raised (any exception here), and a kept answer `{"value", "sha256"}`: its members compared as a map,
 * their order by the SHA-256 of `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`, which
 * core.json.PyJson.dumps writes alike.
 */
object ShapesReplay : AreaReplay {
    override val area = "shapes"

    private const val H = "test_conformance_viewer_shapes."

    override fun replay(misses: Misses) {
        dataIsTheModules(misses)
        voicings()
        instruments()
        harpPlay()
        harpChoices()
        harpTables()
        winds()
    }

    /** The parts of the data Kotlin also states: the guitar's tuning, the skeleton's constant. */
    private fun dataIsTheModules(misses: Misses) {
        val tuning = io.github.danielhp95.caracole.viewer.ViewerData.table("instruments")
            .getValue("voicings").jsonObject.getValue("TUNING").jsonArray.map { it.jsonPrimitive.int }
        misses.check(tuning == Voicings.TUNING) { "Voicings.TUNING ${Voicings.TUNING}, voicings.py's $tuning" }
        misses.check(Instruments.GUITAR.tuning == Voicings.TUNING) { "the guitar's tuning: ${Instruments.GUITAR.tuning}" }
    }

    fun voicings() = replay("viewer/voicings.jsonl", 8) { record, misses ->
        val args = record.args
        val out = record.out!!
        when (record.fn) {
            H + "fingerings_of" -> each(misses, record) { i, text ->
                answer { Voicings.parseFingering(text.content()) } to out.jsonArray[i]
            }
            H + "legends_of" -> each(misses, record) { i, line ->
                answer { given(Voicings.chordLegend(line.content())) } to out.jsonArray[i]
            }
            H + "defines_of" -> each(misses, record) { i, value ->
                answer { Voicings.parseDefine(value.content())?.let { (c, p) -> JsonArray(listOf(chord(c), p)) } } to
                    out.jsonArray[i]
            }
            H + "keys_of" -> each(misses, record) { i, name ->
                val c = Theory.parseChord(name.content(), strict = false)
                val got = c?.let {
                    val (fingering, nearest, slash) = Voicings.voicingKeys(it)
                    JsonArray(listOf(JsonPrimitive(fingering), JsonPrimitive(nearest), slash?.let(::JsonPrimitive) ?: JsonNull,
                                     JsonPrimitive(Voicings.shapeKey(it)), JsonPrimitive(Instruments.pianoKey(it))))
                }
                (got ?: JsonNull) to out.jsonArray[i]
            }
            H + "positions_of" -> each(misses, record) { i, item ->
                val (position, tuning) = item.jsonArray
                answer {
                    JsonArray(listOf(ints(Voicings.notesOf(position.jsonArray, ints(tuning))),
                                     JsonArray(Voicings.fretsFromNut(position.jsonArray).map { it?.let(::JsonPrimitive) ?: JsonNull })))
                } to out.jsonArray[i]
            }
            H + "plays_of" -> each(misses, record) { i, item ->
                val (position, row, tuning) = item.jsonArray
                answer { JsonPrimitive(Voicings.plays(position.jsonArray, chord(row)!!, ints(tuning))) } to out.jsonArray[i]
            }
            H + "sheet_shapes_of" -> {
                val given = args[0].jsonArray.map { pair -> chord(pair.jsonArray[0])!! to pair.jsonArray[1].jsonArray }
                val shift = args[2].jsonPrimitive.int
                val shapes = Voicings.sheetShapes(given)
                keptIs(misses, "sheet_shapes(${args[0]})", out.jsonObject.getValue("shapes"), shapes)
                val guitar = args[1].jsonArray.map { name ->
                    Theory.parseChord(name.content(), strict = false)?.let {
                        Instruments.chordShapes(Instruments.GUITAR, it, shift, shapes)
                    } ?: JsonNull
                }
                val want = out.jsonObject.getValue("guitar")
                misses.check(JsonArray(guitar) == want) { "chord_shapes(GUITAR, ${args[1]}, $shift, given): $guitar, Python's $want" }
            }
            H + "page_voicings_of" -> {
                val keys = args[0].jsonArray.map { it.content() }.toSet()
                val got = Voicings.pageVoicings(keys)
                misses.check(JsonArray(got.keys.map(::JsonPrimitive)) == out.jsonObject.getValue("keys") &&
                             sha(got) == out.jsonObject.getValue("sha256").content()) { "page_voicings($keys): ${got.keys}" }
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    fun instruments() = replay("viewer/instruments.jsonl", 7) { record, misses ->
        val args = record.args
        val out = record.out!!
        when (record.fn) {
            H + "instrument_of" -> each(misses, record) { i, name ->
                JsonPrimitive(Instruments.instrument((name as? JsonPrimitive)?.takeIf { it.isString }?.content).id) to
                    out.jsonArray[i]
            }
            "caracole.viewer.instruments.easy_keys" ->
                keptIs(misses, "easy_keys(${args[0]})", out, Instruments.easyKeys(args[0].content()))
            H + "is_easy_of" -> {
                val table = args[0].content()
                val got = JsonArray(args[1].jsonArray.map { JsonPrimitive(Instruments.isEasy(table, key(it)!!)) })
                misses.check(got == out) { "is_easy($table, …): $got, Python's $out" }
            }
            H + "ukulele_quality_of" -> each(misses, record) { i, f ->
                answer { Instruments.ukuleleQuality(f.content()) } to out.jsonArray[i]
            }
            H + "chord_of" -> {
                val name = args[0].content()
                val shift = args[1].jsonPrimitive.int
                val c = Theory.parseChord(name, strict = false)!!
                val want = out.jsonObject
                val onRoot = want.getValue("on_root").jsonArray[0].jsonPrimitive.int
                val shapes = want.getValue("shapes").jsonObject.keys.associateWith {
                    Instruments.chordShapes(Instruments.instrument(it), c, shift)
                }
                val got = JsonObject(mapOf(
                    "chord" to chord(c), "stacked" to ints(Instruments.stacked(c)),
                    "piano" to JsonArray(Instruments.pianoPositions(c).map(::ints)),
                    "piano_key" to JsonPrimitive(Instruments.pianoKey(c)),
                    "on_root" to JsonArray(listOf(JsonPrimitive(onRoot), chord(Instruments.onRoot(c, onRoot)))),
                    "shapes" to JsonObject(shapes),
                ))
                misses.check(got == want) { "chord_of(${JsonPrimitive(name)}, $shift): $got, Python's $want" }
            }
            H + "page_of" -> {
                val fingerings = args[0].jsonArray.map { it.content() }.toSet()
                val chords = args[1].jsonArray.map { chord(it)!! }
                val want = out.jsonObject
                val guitar = Voicings.pageVoicings(fingerings)
                val more = Instruments.pageVoicings(fingerings, chords)
                val entries = Instruments.entries(fingerings)
                val got = JsonObject(mapOf(
                    "voicings" to JsonArray(listOf(JsonArray(guitar.keys.map(::JsonPrimitive)), JsonPrimitive(sha(guitar)))),
                    "instruments" to JsonArray(listOf(JsonArray(more.keys.map(::JsonPrimitive)), JsonPrimitive(sha(more)))),
                    "entries" to JsonPrimitive(sha(entries)),
                    "near" to entries[1].jsonObject.getValue("near"),
                ))
                misses.check(got == want) { "page_of($fingerings, ${args[1]}): $got, Python's $want" }
            }
            "caracole.viewer.instruments.entries" -> keptIs(misses, "entries(set())", out, Instruments.entries(emptySet()))
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    fun harpPlay() = replay("viewer/harp_play.jsonl", 3) { record, misses ->
        val out = record.out!!
        when (record.fn) {
            H + "play_of" -> each(misses, record) { i, row ->
                val c = chord(row)!!
                JsonArray((0 until 12).map { Harp.entry(Harp.play(c, it)) ?: JsonNull }) to out.jsonArray[i]
            }
            H + "texts_of" -> each(misses, record) { i, item ->
                val (row, harp, k) = item.jsonArray
                JsonPrimitive(Harp.play(chord(row)!!, harp.jsonPrimitive.int).text(Theory.spelling(key(k)))) to out.jsonArray[i]
            }
            H + "steps_of" -> each(misses, record) { i, item ->
                val (row, tonic) = item.jsonArray
                ints(Harp.chordSteps(chord(row)!!, tonic.jsonPrimitive.int)) to out.jsonArray[i]
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    fun harpChoices() = replay("viewer/harp_choices.jsonl", 2) { record, misses ->
        val args = record.args
        val out = record.out!!
        when (record.fn) {
            H + "choices_of" -> {
                val names = args[0].jsonArray.map { it.content() }
                val k = key(args[1])!!
                val got = choicesOf(names, k)
                misses.check(sameNumbers(got, out)) { "choices_of($names, $k): $got, Python's $out" }
            }
            "caracole.viewer.harp.candidates" -> misses.check(ints(Harp.candidates(key(args[0])!!)) == out) {
                "candidates(${args[0]}): ${Harp.candidates(key(args[0])!!)}, Python's $out"
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    /** What the harps for a song are chosen by, as the generator's choices_of has it: each candidate's ranking (its
     * choice made as harp.py's _choices makes it), the choices, the header line. */
    private fun choicesOf(names: List<String>, key: Key): JsonObject {
        val chords = names.map { Theory.parseChord(it, strict = false) }
        val distinct = LinkedHashMap<Triple<Int, Set<Int>, Int?>, Chord>()
        for (c in chords) if (c != null) distinct.putIfAbsent(Triple(c.root, c.intervals, c.bass), c)
        val ranked = Harp.candidates(key).withIndex().map { (order, position) ->
            val harp = Harp.harpFor(key.tonic, position)
            var fit = 0.0
            var plays = 0
            var substitutes = 0
            for (c in distinct.values) {
                val kind = Harp.play(c, harp).kind
                fit += Harp.CHORD_FIT.getValue(kind) * (if (c.root == key.tonic) Harp.TONIC_WEIGHT else 1)
                if (kind == "yes" || kind == "part") plays++
                if (kind == "minor") substitutes++
            }
            val choice = io.github.danielhp95.caracole.viewer.harp.HarpChoice(position, harp, Harp.positionMode(position), fit,
                                                                              distinct.size, plays, substitutes)
            JsonArray(Harp.ranking(key, order, choice).map(::JsonPrimitive))
        }
        val found = Harp.choices(key, chords)
        return JsonObject(mapOf(
            "candidates" to ints(Harp.candidates(key)), "ranking" to JsonArray(ranked),
            "choices" to JsonArray(found.map {
                JsonArray(listOf(JsonPrimitive(it.position), JsonPrimitive(it.harp), it.mode?.let(::JsonPrimitive) ?: JsonNull,
                                 JsonPrimitive(it.fit), JsonPrimitive(it.chords), JsonPrimitive(it.plays),
                                 JsonPrimitive(it.substitutes)))
            }),
            "header" to JsonPrimitive(Harp.headerLine(key, chords)),
        ))
    }

    fun harpTables() = replay("viewer/harp_tables.jsonl", 14) { record, misses ->
        val args = record.args
        val out = record.out!!
        when (record.fn) {
            H + "tables_of" -> {
                val names = args[0].jsonArray.map { it.content() }
                val k = key(args[1])!!
                val (_, mapped, alts) = mappedAndAlts(names, k)
                val tables = Harp.tables(k, mapped, alts)
                val want = out.jsonObject
                misses.check(JsonArray(tables.keys.map(::JsonPrimitive)) == want.getValue("order")) {
                    "tables($names, $k)'s members: ${tables.keys}"
                }
                for ((member, digest) in want.getValue("sha256").jsonObject) {
                    misses.check(tables[member]?.let(::sha) == digest.content()) {
                        "tables($names, $k)'s $member: ${tables[member].toString().take(300)}"
                    }
                }
                want["whole"]?.let { keptIs(misses, "tables($names, $k)", it, tables) }
            }
            "caracole.viewer.harp.tables" -> misses.check(Harp.tables(null, emptyMap()) == out) { "tables(None, {})" }
            H + "tables_in" -> {
                val names = args[0].jsonArray.map { it.content() }
                val k = key(args[1])!!
                val (_, mapped, _) = mappedAndAlts(names, k)
                val modes = args[2].jsonArray.map { it.content() }
                keptIs(misses, "tables($names, $k, $modes)", out, Harp.tables(k, modes.associateWith { mapped.getValue(it) }))
            }
            H + "layout_of" -> {
                val l = Harp.layout(args[0].jsonPrimitive.int)
                val got = JsonObject(mapOf(
                    "name" to JsonPrimitive(l.name), "blow" to ints(l.blow), "draw" to ints(l.draw),
                    "bend_breath" to JsonArray(l.bendBreath.map(::JsonPrimitive)), "bends" to JsonArray(l.bends.map(::ints)),
                ))
                misses.check(got == out) { "layout(${args[0]}): $got, Python's $out" }
            }
            "caracole.viewer.harp.ring" -> misses.check(Harp.ring() == out) { "ring(): ${Harp.ring()}" }
            "caracole.viewer.harp.holes" -> keptIs(misses, "holes(${args[0]})", out, Harp.holes(args[0].jsonPrimitive.int))
            "caracole.viewer.harp.key_scales" -> misses.check(Harp.keyScales(args[0].content()) == out) {
                "key_scales(${args[0]}): ${Harp.keyScales(args[0].content())}, Python's $out"
            }
            H + "outside_of" -> {
                val got = JsonArray((0 until 12).map { Harp.outside(args[0].content(), it) })
                misses.check(got == out) { "outside(${args[0]}, …): $got, Python's $out" }
            }
            "caracole.viewer.harp.layouts" -> misses.check(Harp.layouts() == out) { "layouts(): ${Harp.layouts()}" }
            "caracole.viewer.harp.hole_tables" -> keptIs(misses, "hole_tables()", out, Harp.holeTables())
            H + "positions_of" -> {
                val p = args[0].jsonPrimitive.int
                val got = JsonObject(mapOf(
                    "mode" to (Harp.positionMode(p)?.let(::JsonPrimitive) ?: JsonNull), "ordinal" to JsonPrimitive(Harp.ordinal(p)),
                    "harp_for" to ints((0 until 12).map { Harp.harpFor(it, p) }),
                ))
                misses.check(got == out) { "position $p: $got, Python's $out" }
            }
            H + "position_text_of" -> {
                val t = args[0].jsonPrimitive.int
                val got = JsonObject(mapOf(
                    "position_of" to ints((0 until 12).map { Harp.positionOf(t, it) }),
                    "text" to JsonArray((0 until 12).map { JsonPrimitive(Harp.positionText(t, it)) }),
                ))
                misses.check(got == out) { "position_text($t, …): $got, Python's $out" }
            }
            H + "hole_notes_of" -> {
                val harp = args[0].jsonPrimitive.int
                var n = 0
                for (hole in 0 until 12) for (breath in listOf("blow", "draw", "suck")) for (bend in -1 until 5) {
                    for (over in listOf(false, true)) {
                        val want = out.jsonArray[n++]
                        val got = answer { Harp.holeNote(harp, hole, breath, bend, over)?.let(::JsonPrimitive) }
                        misses.check(same(got, want)) { "hole_note($harp, $hole, $breath, $bend, $over): $got, Python's $want" }
                    }
                }
                misses.check(n == out.jsonArray.size) { "hole_notes_of($harp): $n of ${out.jsonArray.size}" }
            }
            H + "entry_text_of" -> each(misses, record) { i, item ->
                val (found, root) = item.jsonArray
                JsonPrimitive(Harp.entryText(found as? JsonArray, root.content())) to out.jsonArray[i]
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    fun winds() = replay("viewer/winds.jsonl", 8) { record, misses ->
        val args = record.args
        val out = record.out!!
        when (record.fn) {
            H + "fingerings_of" -> {
                val wind = Winds.WINDS.getValue(args[0].content())
                val system = (args[1] as? JsonPrimitive)?.takeIf { it.isString }?.content
                val got = answer {
                    JsonArray((50..100).map { note ->
                        JsonArray(Winds.fingerings(wind, note, system).map { JsonArray(listOf(JsonPrimitive(it.chart), JsonPrimitive(it.text))) })
                    })
                }
                misses.check(same(got, out)) { "fingerings(${wind.name}, …, $system): $got, Python's $out" }
            }
            H + "fit_of" -> {
                val notes = ints(args[0])
                val fit = Winds.fit(notes, Winds.WINDS.getValue(args[1].content()))
                val got = JsonArray(listOf(JsonPrimitive(fit.shift), ints(fit.written), ints(fit.outside)))
                misses.check(got == out) { "fit($notes, ${args[1]}): $got, Python's $out" }
            }
            "caracole.viewer.winds.scale_notes" -> misses.check(ints(Winds.scaleNotes(key(args[0])!!)) == out) {
                "scale_notes(${args[0]}): ${Winds.scaleNotes(key(args[0])!!)}, Python's $out"
            }
            H + "steps_of" -> each(misses, record) { i, row ->
                val c = chord(row)!!
                JsonArray(listOf(ints(Winds.chordSteps(c)), ints(Winds.chordNotes(c)))) to out.jsonArray[i]
            }
            H + "interval_steps_of" -> each(misses, record) { i, item ->
                val (set, bass) = item.jsonArray
                ints(Winds.chordSteps(Chord(0, "x", bass.jsonPrimitive.intOrNull, null, ints(set).toSet()))) to out.jsonArray[i]
            }
            H + "solfege_of" -> each(misses, record) { i, name -> answer { Winds.solfege(name.content()) } to out.jsonArray[i] }
            "caracole.viewer.winds.fingering_data" -> keptIs(misses, "fingering_data()", out, Winds.fingeringData())
            H + "tables_of" -> {
                val names = args[0].jsonArray.map { it.content() }
                val k = key(args[1])
                val (chords, mapped, alts) = mappedAndAlts(names, k ?: Key(0, "ionian"))
                keptIs(misses, "winds.tables($names, $k)", out, Winds.tables(chords, k, mapped, alts))
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    // --- the shapes of the records -------------------------------------------------------------------------------

    /** Every record of [name] through [check], with [kinds] kinds of record each found. */
    private fun replay(name: String, kinds: Int, check: (Record, Misses) -> Unit) {
        val misses = Misses(name)
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(name)) {
            counts.merge(record.fn, 1, Int::plus)
            check(record, misses)
        }
        assertEquals("$name: the kinds of record, $counts", kinds, counts.size)
        misses.assertNone()
    }

    /** Each item of the record's batch (its first argument), its answer and Python's. */
    private fun each(misses: Misses, record: Record, got: (Int, JsonElement) -> Pair<JsonElement, JsonElement>) {
        val items = record.args[0].jsonArray
        assertTrue("${record.fn}: a batch of answers", record.out!!.jsonArray.size == items.size)
        for ((i, item) in items.withIndex()) {
            val (answer, want) = got(i, item)
            misses.check(same(answer, want)) { "${record.fn.substringAfterLast('.')}($item): $answer, Python's $want" }
        }
    }

    /** What [block] answers, as JSON, or `{"err": …}` for what it threw. */
    private fun answer(block: () -> Any?): JsonElement = try {
        when (val v = block()) {
            null -> JsonNull
            is JsonElement -> v
            is String -> JsonPrimitive(v)
            else -> throw AssertionError("no JSON for $v")
        }
    } catch (e: Exception) {
        JsonObject(mapOf("err" to JsonPrimitive(e.javaClass.simpleName)))
    }

    /** An answer and Python's: equal, or both errors (of whatever type). */
    private fun same(got: JsonElement, want: JsonElement): Boolean =
        if (want is JsonObject && "err" in want) got is JsonObject && "err" in got else got == want

    /** A kept answer (`{"value", "sha256"}`): its members as Python's, and in Python's order. */
    private fun keptIs(misses: Misses, what: String, want: JsonElement, got: JsonElement) {
        val kept = want.jsonObject
        misses.check(got == kept.getValue("value")) { "$what: ${got.toString().take(400)}, Python's ${kept.getValue("value").toString().take(400)}" }
        misses.check(sha(got) == kept.getValue("sha256").content()) { "$what: its members' order differs from Python's" }
    }

    /** Two JSON values alike, their numbers compared as numbers (Python's 0 and -0.0 are 0.0). */
    private fun sameNumbers(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.keys.all { sameNumbers(a.getValue(it), b.getValue(it)) }
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { sameNumbers(a[it], b[it]) }
        a is JsonPrimitive && b is JsonPrimitive && !a.isString && !b.isString && a !is JsonNull && b !is JsonNull &&
            a.booleanOrNull == null && b.booleanOrNull == null -> a.doubleOrNull == b.doubleOrNull
        else -> a == b
    }

    /** The SHA-256 of `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`. */
    fun sha(value: JsonElement): String = Canonical.sha256Hex(PyJson.dumps(value, compact = true).toByteArray(Charsets.UTF_8))

    /** A sheet's chords as page.py reads them ([names] as written), and in each mode of [key] with their
     * alternatives, as the page's data has them. */
    fun mappedAndAlts(names: List<String>, key: Key): Triple<List<Chord?>, Map<String, List<Chord?>>, Map<String, List<List<Chord>>>> {
        val chords = names.map { Theory.parseChord(it, strict = false) }
        val mapped = LinkedHashMap<String, List<Chord?>>()
        val alts = LinkedHashMap<String, List<List<Chord>>>()
        for (mode in Theory.MODES) {
            val inMode = chords.map { c -> c?.let { Theory.mapChord(it, key, mode) } }
            mapped[mode] = inMode
            alts[mode] = inMode.map { c -> if (c == null) emptyList() else Theory.alternatives(c, Key(key.tonic, mode)) }
        }
        return Triple(chords, mapped, alts)
    }

    private fun given(found: List<Pair<Chord, Position>>): JsonArray = JsonArray(found.map { (c, p) -> JsonArray(listOf(chord(c), p)) })

    /** A chord as the corpus writes it, its trailing nulls left out. */
    fun chord(c: Chord?): JsonElement {
        if (c == null) return JsonNull
        val row = mutableListOf<JsonElement>(JsonPrimitive(c.root), JsonPrimitive(c.quality),
            c.bass?.let(::JsonPrimitive) ?: JsonNull, c.shown?.let(::JsonPrimitive) ?: JsonNull,
            c.tones?.let { ints(it.sorted()) } ?: JsonNull)
        while (row.last() == JsonNull) row.removeAt(row.size - 1)
        return JsonArray(row)
    }

    fun chord(e: JsonElement): Chord? {
        if (e is JsonNull) return null
        val row = e.jsonArray
        fun at(i: Int) = row.getOrNull(i)?.takeIf { it !is JsonNull }
        return Chord(row[0].jsonPrimitive.int, row[1].content(), at(2)?.jsonPrimitive?.int, at(3)?.content(),
                     at(4)?.let { ints(it).toSet() })
    }

    fun key(e: JsonElement): Key? =
        if (e is JsonNull) null else e.jsonArray.let { Key(it[0].jsonPrimitive.int, it[1].content()) }

    private fun ints(xs: List<Int>): JsonArray = JsonArray(xs.map(::JsonPrimitive))
    private fun ints(e: JsonElement): List<Int> = e.jsonArray.map { it.jsonPrimitive.int }
    private fun JsonElement.content(): String = jsonPrimitive.content
}
