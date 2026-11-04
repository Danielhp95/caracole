package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail

/**
 * viewer/theory.py (vectors/viewer/theory.jsonl) and each page's assets (vectors/viewer/theory_assets.jsonl), every
 * record answered by :viewer as Python answered it: TheoryTest's record loops, run on the device by
 * CorpusOnDeviceTest. tests/test_conformance_viewer_theory.py's docstring says each record's shape: a chord is
 * `[root, quality, bass, shown, tones]` with its trailing nulls left out, a key `[tonic, mode]`.
 */
object TheoryReplay : AreaReplay {
    override val area = "theory"

    private const val HELPER = "test_conformance_viewer_theory."

    override fun replay(misses: Misses) {
        everyTheoryRecordIsTheoryPys()
        eachPageInlinesWhatPythonsDoes()
    }

    private fun everyTheoryRecordIsTheoryPys() {
        val misses = Misses("viewer/theory.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/theory.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            val out = record.out!!
            when (record.fn) {
                HELPER + "parsed_of" -> {
                    val names = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                    for ((i, name) in names.withIndex()) {
                        val want = out.jsonArray[i].jsonArray
                        val strict = Theory.parseChord(name)
                        val loose = Theory.parseChord(name, strict = false)
                        val got = if (loose == strict) listOf(chord(strict)) else listOf(chord(strict), chord(loose))
                        misses.check(JsonArray(got) == want) { "parse_chord(${JsonPrimitive(name)}): $got, Python's $want" }
                    }
                }
                HELPER + "chord_in" -> {
                    val name = record.args[0].jsonPrimitive.content
                    val key = key(record.args[1])!!
                    val limit = record.args[2].jsonPrimitive.intOrNull
                    val want = out.jsonObject
                    misses.check(chordIn(name, key, limit) == want) {
                        "chord_in(${JsonPrimitive(name)}, $key, $limit): ${chordIn(name, key, limit)}, Python's $want"
                    }
                }
                HELPER + "key_of" -> {
                    val k = key(record.args)!!
                    misses.check(keyOf(k) == out) { "key_of($k): ${keyOf(k)}, Python's $out" }
                }
                "caracole.viewer.theory.spelling" -> misses.expect(record) { Theory.spelling(null) }
                HELPER + "parsed_keys" -> {
                    for ((i, text) in record.args[0].jsonArray.withIndex()) {
                        val arg: Any? = when {
                            text is JsonNull -> null
                            text.jsonPrimitive.isString -> text.jsonPrimitive.content
                            else -> text.jsonPrimitive.int
                        }
                        val want = out.jsonArray[i]
                        val got = key(Theory.parseKey(arg))
                        misses.check(got == want) { "parse_key($text): $got, Python's $want" }
                    }
                }
                HELPER + "played_of" -> {
                    val names = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                    val capos = record.args[1].jsonArray.map { it.jsonPrimitive.int }
                    val texts = record.args[2].jsonArray.map { it.jsonPrimitive.content }
                    val got = playedOf(names, capos, texts)
                    misses.check(got == out) { "played_of($names, $capos, $texts): $got, Python's $out" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 6 && counts.getValue(HELPER + "chord_in") > 300)
        misses.assertNone()
    }

    private fun chordIn(name: String, key: Key, limit: Int?): JsonObject {
        val c = Theory.parseChord(name, strict = false)!!
        val out = linkedMapOf(
            "chord" to chord(c),
            "parts" to JsonArray(listOf(ints(c.intervals), ints(c.pitchClasses), JsonPrimitive(c.suffix))),
            "map" to JsonArray(Theory.MODES.map { chord(Theory.mapChord(c, key, it)) }),
            "alternatives" to JsonArray(Theory.alternatives(c, key).map(::chord)),
        )
        if (limit != null) out["limited"] = JsonArray(Theory.alternatives(c, key, limit).map(::chord))
        return JsonObject(out)
    }

    private val SOUNDING = listOf(0, 2, 5, 7, 11, 12)

    /** The page kinds by the names the generator gives them. */
    private val PAGES = mapOf(
        "sheet" to ViewerAssets.Page.SHEET, "songbook" to ViewerAssets.Page.SONGBOOK,
        "harmonica" to ViewerAssets.Page.HARMONICA,
    )

    private fun keyOf(k: Key): JsonObject {
        val hints = (0 until 8).map { Triple(it, 2, Theory.capoHints(k, capo = it)) } +
            listOf(0, 1, 9).map { Triple(0, it, Theory.capoHints(k, it)) }
        return JsonObject(mapOf(
            "spelling" to JsonArray(Theory.spelling(k).map(::JsonPrimitive)),
            "name" to JsonPrimitive(Theory.keyName(k)),
            "scale" to ints(Theory.scale(k)),
            "capo_hints" to JsonArray(hints.map { (capo, limit, found) ->
                JsonArray(listOf(JsonPrimitive(capo), JsonPrimitive(limit),
                    JsonArray(found.map { (fret, shapes) -> JsonArray(listOf(JsonPrimitive(fret), key(shapes))) })))
            }),
            "sounding" to JsonArray(SOUNDING.map { JsonArray(listOf(JsonPrimitive(it), key(Theory.sounding(k, it)))) }),
        ))
    }

    private fun playedOf(names: List<String>, capos: List<Int>, texts: List<String>): JsonObject {
        val played = names.mapNotNull { Theory.parseChord(it, strict = false) }
        val named = ArrayList<JsonElement>()
        for (capo in capos) {
            for (text in texts) {
                val parsed = Theory.parseKey(text)
                if (parsed == null) {
                    named.add(JsonNull)
                    continue
                }
                val found = Theory.namedKey(text, capo, played)
                named.add(JsonArray(listOf(key(found), key(Theory.bareKey(parsed, capo, played)),
                    key(Theory.shapesKey(found ?: parsed, capo, played)))))
            }
        }
        return JsonObject(mapOf("estimate" to key(Theory.estimateKey(played)), "named" to JsonArray(named)))
    }

    private fun eachPageInlinesWhatPythonsDoes() {
        val misses = Misses("viewer/theory_assets.jsonl")
        val kinds = HashSet<String>()
        for (record in Corpus.records("viewer/theory_assets.jsonl")) {
            assertEquals(HELPER + "page_assets", record.fn)
            val kind = record.args[0].jsonPrimitive.content
            kinds += kind
            val page = PAGES[kind] ?: throw AssertionError("no page kind $kind")
            val want = record.out!!.jsonObject
            for ((part, got) in listOf("styles" to page.styles, "scripts" to page.scripts)) {
                val names = want.getValue(part).jsonArray.map { it.jsonPrimitive.content }
                misses.check(got == names) { "$kind's $part: $got, Python's $names" }
                for (name in got) misses.check(ViewerAssets.text(name).isNotEmpty()) { "$name reads empty" }
            }
        }
        assertEquals(PAGES.keys, kinds)
        misses.assertNone()
    }

    /** A chord as the corpus writes it: `[root, quality, bass, shown, tones]`, its trailing nulls left out. */
    fun chord(c: Chord?): JsonElement {
        if (c == null) return JsonNull
        val row = mutableListOf<JsonElement>(JsonPrimitive(c.root), JsonPrimitive(c.quality),
            c.bass?.let(::JsonPrimitive) ?: JsonNull, c.shown?.let(::JsonPrimitive) ?: JsonNull,
            c.tones?.let(::ints) ?: JsonNull)
        while (row.last() == JsonNull) row.removeAt(row.size - 1)
        return JsonArray(row)
    }

    fun key(k: Key?): JsonElement =
        if (k == null) JsonNull else JsonArray(listOf(JsonPrimitive(k.tonic), JsonPrimitive(k.mode)))

    fun key(e: JsonElement): Key? =
        if (e is JsonNull) null else e.jsonArray.let { Key(it[0].jsonPrimitive.int, it[1].jsonPrimitive.content) }

    private fun ints(xs: Collection<Int>): JsonArray = JsonArray(xs.sorted().map(::JsonPrimitive))
}
