package io.github.danielhp95.caracole.viewer.theory

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/**
 * theory.py's constants and patterns, as tests/test_conformance_viewer_theory.py wrote them from the module itself
 * into caracole/viewer/theory.json (that file's docstring is the format's), read once ([ViewerData]). Every pattern is
 * compiled as Python reads it (PyRegex), once; every collection handed out is one nothing can change.
 */
internal object TheoryData {
    private val json: JsonObject by lazy { ViewerData.table("theory") }

    val qualities: Map<String, Set<Int>> by lazy {
        frozenMap(json.obj("QUALITIES").mapValues { (_, v) -> Chord.frozen(v.ints()) })
    }

    /** QUALITIES by its intervals, a later quality of the same intervals winning, as a dict comprehension does. */
    val byIntervals: Map<Set<Int>, String> by lazy {
        frozenMap(qualities.entries.associate { (name, intervals) -> intervals to name })
    }
    val display: Map<String, String> by lazy { strings("DISPLAY") }
    val natural: Map<String, Int> by lazy { ints("_NATURAL") }
    val letters: String by lazy { json.getValue("_LETTERS").jsonPrimitive.content }
    val sharps: List<String> by lazy { list("SHARPS") }
    val flats: List<String> by lazy { list("FLATS") }
    val accidental: Map<String, Int> by lazy { ints("_ACCIDENTAL") }
    val added: Map<String, Int> by lazy { ints("_ADDED") }
    val altered: Map<String, Int> by lazy { ints("_ALTERED") }
    val modes: List<String> by lazy { list("MODES") }
    val scales: Map<String, List<Int>> by lazy {
        frozenMap(json.obj("SCALES").mapValues { (_, v) -> Collections.unmodifiableList(v.ints()) })
    }
    val majorTonics: List<String> by lazy { list("_MAJOR_TONICS") }
    val degrees: Map<String, List<Int>> by lazy {
        frozenMap(json.obj("_DEGREES").mapValues { (_, v) -> Collections.unmodifiableList(v.ints()) })
    }

    /** _RARE: (letter, accidental) to the name it is spelled. */
    val rare: Map<Pair<String, Int>, String> by lazy {
        frozenMap(json.getValue("_RARE").jsonArray.associate { row ->
            val (letter, accidental, spelled) = row.jsonArray
            (letter.jsonPrimitive.content to accidental.jsonPrimitive.int) to spelled.jsonPrimitive.content
        })
    }
    val defaultSpelling: List<String> by lazy { list("_DEFAULT_SPELLING") }
    val modeWords: Map<String, String> by lazy { strings("_MODE_WORDS") }
    val colours: List<String> by lazy { list("_COLOURS") }
    val standIns: List<String> by lazy { list("_STAND_INS") }
    val thirds: Map<Int, Int> by lazy { frozenMap(ints("_THIRDS").mapKeys { (k, _) -> k.toInt() }) }
    val symmetric: List<String> by lazy { list("_SYMMETRIC") }
    val open: Map<String, Set<Int>> by lazy { frozenMap(json.obj("_OPEN").mapValues { (_, v) -> Chord.frozen(v.ints()) }) }
    val openNotes: Set<Int> by lazy { Chord.frozen(json.getValue("_OPEN_NOTES").ints()) }
    val maxCapo: Int by lazy { json.getValue("MAX_CAPO").jsonPrimitive.int }

    /** _REWRITES: each pattern, compiled, and its replacement's template. */
    val rewrites: List<Pair<Regex, String>> by lazy {
        json.getValue("_REWRITES").jsonArray.map { row ->
            val (pattern, template) = row.jsonArray
            PyRegex.compile(pattern.jsonPrimitive.content) to template.jsonPrimitive.content
        }
    }
    val root: Regex by lazy { pattern("_ROOT") }
    val bass: Regex by lazy { pattern("_BASS") }
    val extension: Regex by lazy { pattern("_EXTENSION") }
    val sus: Regex by lazy { pattern("_SUS") }
    val alteration: Regex by lazy { pattern("_ALTERATION") }
    val key: Regex by lazy { pattern("_KEY") }

    private fun pattern(name: String): Regex = PyRegex.compile(json.obj("patterns").getValue(name).jsonPrimitive.content)

    private fun JsonObject.obj(name: String): JsonObject = getValue(name).jsonObject

    private fun JsonElement.ints(): List<Int> = jsonArray.map { it.jsonPrimitive.int }

    private fun list(name: String): List<String> =
        Collections.unmodifiableList(json.getValue(name).jsonArray.map { it.jsonPrimitive.content })

    private fun strings(name: String): Map<String, String> = frozenMap(json.obj(name).mapValues { (_, v) -> v.jsonPrimitive.content })

    private fun ints(name: String): Map<String, Int> = frozenMap(json.obj(name).mapValues { (_, v) -> v.jsonPrimitive.int })

    private fun <K, V> frozenMap(map: Map<K, V>): Map<K, V> = Collections.unmodifiableMap(LinkedHashMap(map))
}
