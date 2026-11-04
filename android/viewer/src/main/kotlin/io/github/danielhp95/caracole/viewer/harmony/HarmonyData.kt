package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/**
 * harmony.py's constants and patterns, and harmony_tables.py's, as tests/test_conformance_viewer_harmony.py wrote them
 * from the modules themselves into caracole/viewer/harmony.json (that file's docstring is the format's), read once
 * ([ViewerData]). Every pattern
 * is compiled as Python reads it (PyRegex), once; every collection handed out is one nothing can change.
 */
internal object HarmonyData {
    private val json: JsonObject by lazy { ViewerData.table("harmony") }

    /** A quality's numeral: lower case or not, its sign ("°", "ø", "+") and its extension. */
    class Shape(val lower: Boolean, val sign: String, val extension: String)

    val romans: List<String> by lazy { list("ROMANS") }
    val shapes: Map<String, Shape> by lazy {
        frozenMap(json.obj("_SHAPES").mapValues { (_, v) ->
            val (lower, sign, extension) = v.jsonArray
            Shape(lower.jsonPrimitive.boolean, sign.jsonPrimitive.content, extension.jsonPrimitive.content)
        })
    }
    val borrows: Map<String, List<String>> by lazy {
        frozenMap(json.obj("_BORROWS").mapValues { (_, v) -> strings(v) })
    }
    val modeWords: Map<String, String> by lazy { stringMap("_MODE_WORDS") }
    val families: List<String> by lazy { list("_FAMILIES") }
    val bassDegrees: List<String> by lazy { list("_BASS_DEGREES") }
    val inOctave: Map<String, String> by lazy { stringMap("_IN_OCTAVE") }
    val extensionWords: Map<String, String> by lazy { stringMap("_EXTENSION_WORDS") }
    val symbolMeanings: Map<String, String> by lazy { stringMap("_SYMBOL_MEANINGS") }
    val otherScales: Map<String, List<Int>> by lazy {
        frozenMap(json.obj("_OTHER_SCALES").mapValues { (_, v) ->
            Collections.unmodifiableList(v.jsonArray.map { it.jsonPrimitive.int })
        })
    }
    val tokens: Regex by lazy { pattern("_TOKENS") }

    // --- the progressions ----------------------------------------------------------------------------------------

    /** CATALOGUE: (name, numerals, source), in its order. */
    val catalogue: List<Triple<String, List<String>, String>> by lazy {
        Collections.unmodifiableList(json.getValue("CATALOGUE").jsonArray.map { row ->
            val (name, numerals, source) = row.jsonArray
            Triple(name.jsonPrimitive.content, strings(numerals), source.jsonPrimitive.content)
        })
    }
    val loops: Set<List<String>> by lazy {
        Collections.unmodifiableSet(json.getValue("_LOOPS").jsonArray.mapTo(LinkedHashSet()) { strings(it) })
    }
    val onItsTonic: Set<String> by lazy { set("_ON_ITS_TONIC") }
    val turnsOnItsTonic: Set<String> by lazy { set("_TURNS_ON_ITS_TONIC") }
    val naturalMinor: Set<String> by lazy { set("_NATURAL_MINOR") }
    val onTheTonic: Map<String, String> by lazy { stringMap("_ON_THE_TONIC") }
    val steps: Map<String, Int> by lazy { intMap("_STEPS") }
    val accidentals: Map<String, Int> by lazy { intMap("_ACCIDENTALS") }
    val longestCycle: Int by lazy { json.getValue("_LONGEST_CYCLE").jsonPrimitive.int }
    val numeral: Regex by lazy { pattern("_NUMERAL") }
    val romanOnly: Regex by lazy { pattern("_ROMAN_ONLY") }
    val separators: Regex by lazy { pattern("_SEPARATORS") }

    // --- harmony_tables.py's own ---------------------------------------------------------------------------------

    val note: Regex by lazy { tablesPattern("_NOTE") }
    val afterNote: Regex by lazy { tablesPattern("_AFTER_NOTE") }

    private fun pattern(name: String): Regex = PyRegex.compile(json.obj("patterns").getValue(name).jsonPrimitive.content)

    private fun tablesPattern(name: String): Regex =
        PyRegex.compile(json.obj("harmony_tables").obj("patterns").getValue(name).jsonPrimitive.content)

    private fun set(name: String): Set<String> = Collections.unmodifiableSet(LinkedHashSet(list(name)))

    private fun intMap(name: String): Map<String, Int> = frozenMap(json.obj(name).mapValues { (_, v) -> v.jsonPrimitive.int })

    private fun JsonObject.obj(name: String): JsonObject = getValue(name).jsonObject

    private fun strings(e: JsonElement): List<String> = Collections.unmodifiableList(e.jsonArray.map { it.jsonPrimitive.content })

    private fun list(name: String): List<String> = strings(json.getValue(name))

    private fun stringMap(name: String): Map<String, String> =
        frozenMap(json.obj(name).mapValues { (_, v) -> v.jsonPrimitive.content })

    private fun <K, V> frozenMap(map: Map<K, V>): Map<K, V> = Collections.unmodifiableMap(LinkedHashMap(map))
}
