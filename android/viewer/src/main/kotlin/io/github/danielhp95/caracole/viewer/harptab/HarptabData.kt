package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * What harptab.py states as data, read from data/caracole/viewer/harptab.json (tests/test_conformance_viewer_harptab.py
 * writes it from the module itself, its docstring says the format): the numbers, the presets, the words and every
 * pattern, each compiled through core.py.PyRegex once, on first use (the first compile reads Python's tables).
 */
internal object HarptabData {
    private val json: JsonObject by lazy { ViewerData.table("harptab") }

    private fun number(name: String): Double = json.getValue(name).jsonPrimitive.double
    private fun strings(name: String): List<String> = json.getValue(name).jsonArray.map { it.jsonPrimitive.content }
    private fun stringMap(name: String): Map<String, String> =
        json.getValue(name).jsonObject.mapValuesTo(LinkedHashMap()) { it.value.jsonPrimitive.content }

    val TAB_STOP: Int by lazy { json.getValue("TAB_STOP").jsonPrimitive.int }
    val HOLE_SHARE: Double by lazy { number("HOLE_SHARE") }
    val MISSED_SHARE: Double by lazy { number("MISSED_SHARE") }
    val REACH: Int by lazy { json.getValue("REACH").jsonPrimitive.int }
    val MAX_CUTS: Int by lazy { json.getValue("MAX_CUTS").jsonPrimitive.int }
    val TAB_Q: Double by lazy { number("TAB_Q") }
    val MARGIN: Double by lazy { number("MARGIN") }
    val ROW_TRUST: Double by lazy { number("ROW_TRUST") }
    val LEGEND_WEIGHT: Double by lazy { number("LEGEND_WEIGHT") }
    val ABOVE_LEAD: Double by lazy { number("ABOVE_LEAD") }
    val ABOVE_SHARE: Double by lazy { number("ABOVE_SHARE") }

    val BREATHS: List<String> by lazy { strings("BREATHS") }
    val EFFECTS: List<String> by lazy { strings("EFFECTS") }
    val MEANINGS: List<String> by lazy { strings("MEANINGS") }
    val PLACES: List<String> by lazy { strings("PLACES") }

    val PRESETS: List<Notation> by lazy { json.getValue("PRESETS").jsonArray.map(::notation) }
    val PRESET: Map<String, Notation> by lazy { PRESETS.associateByTo(LinkedHashMap()) { it.name } }
    val DOTS: Symbol by lazy { symbol(json.getValue("DOTS")) }
    val STAR_BENDS: Notation by lazy { notation(json.getValue("STAR_BENDS")) }

    val NUM: String by lazy { json.getValue("_NUM").jsonPrimitive.content }
    val KINDS: Map<String, String> by lazy { stringMap("_KINDS") }
    val SIGNS: String by lazy { json.getValue("_SIGNS").jsonPrimitive.content }
    val CLOSE: Map<String, String> by lazy { stringMap("_CLOSE") }
    val LABEL_WORD: String by lazy { json.getValue("_LABEL_WORD").jsonPrimitive.content }
    val PIN_NAMES: List<String> by lazy { strings("PIN_NAMES") }
    val PIN_WORDS: Map<String, Pair<String, Int>> by lazy {
        json.getValue("_PIN_WORDS").jsonObject.mapValuesTo(LinkedHashMap()) { (_, v) ->
            v.jsonArray[0].jsonPrimitive.content to v.jsonArray[1].jsonPrimitive.int
        }
    }
    val SAY: Map<String, String> by lazy { stringMap("_SAY") }
    val ORDER: List<String> by lazy { strings("_ORDER") }

    /** _VOWELS, as code points. */
    val VOWELS: Set<Int> by lazy { json.getValue("_VOWELS").jsonPrimitive.content.codePoints().toArray().toHashSet() }
    val DIGRAPHS: Set<String> by lazy { strings("_DIGRAPHS").toHashSet() }

    private val patterns: JsonObject by lazy { json.getValue("patterns").jsonObject }
    private fun pattern(name: String): Regex = PyRegex.compile(patterns.getValue(name).jsonPrimitive.content)

    val DECOR: Regex by lazy { pattern("_DECOR") }
    val HOLD: Regex by lazy { pattern("_HOLD") }
    val TIME: Regex by lazy { pattern("_TIME") }
    val ASIDE: Regex by lazy { pattern("_ASIDE") }
    val DOT_BEFORE: Regex by lazy { pattern("_DOT_BEFORE") }
    val LEAD_LABEL: Regex by lazy { pattern("_LEAD_LABEL") }
    val LABEL_WORDS: Regex by lazy { pattern("_LABEL_WORDS") }
    val LABEL_REST: Regex by lazy { pattern("_LABEL_REST") }
    val CHORUS: Regex by lazy { pattern("_CHORUS") }
    val URL: Regex by lazy { pattern("_URL") }
    val INSTRUCTION: Regex by lazy { pattern("_INSTRUCTION") }
    val WORD: Regex by lazy { pattern("_WORD") }
    val LEGEND_LINE: Regex by lazy { pattern("_LEGEND_LINE") }
    val PLACEHOLDER: Regex by lazy { pattern("_PLACEHOLDER") }
    val TWO: Regex by lazy { pattern("_TWO") }
    val THREE: Regex by lazy { pattern("_THREE") }
    val BRACKET: Regex by lazy { pattern("_BRACKET") }
    val SEPARATOR: Regex by lazy { pattern("_SEPARATOR") }
    val VOWEL_RUN: Regex by lazy { pattern("_VOWEL_RUN") }

    /** _CHIPS: each chip's name and the pattern that reads it, in their order. */
    val CHIPS: List<Pair<String, Regex>> by lazy {
        json.getValue("_CHIPS").jsonObject.map { (name, p) -> name to PyRegex.compile(p.jsonPrimitive.content) }
    }
    val KEY_PATTERNS: List<Regex> by lazy {
        json.getValue("_KEY_PATTERNS").jsonArray.map { PyRegex.compile(it.jsonPrimitive.content) }
    }

    /** _LEXICON: each meaning and the words a legend's meaning names it by, in their order. */
    val LEXICON: List<Pair<String, Regex>> by lazy {
        json.getValue("_LEXICON").jsonArray.map {
            it.jsonArray[0].jsonPrimitive.content to PyRegex.compile(it.jsonArray[1].jsonPrimitive.content)
        }
    }

    // The function-local patterns of harptab.py, as it writes them.
    val DIGIT: Regex by lazy { PyRegex.compile("""\d""") }
    val NOT_DIGITS: Regex by lazy { PyRegex.compile("""\D+""") }
    val NUM_ALONE: Regex by lazy { PyRegex.compile(NUM) }
    val LAST_NUM: Regex by lazy { PyRegex.compile("$NUM$") }
    val NUM_IN_BRACKETS: Regex by lazy { PyRegex.compile("""\($NUM\)""") }
    val HOLE_AFTER: Regex by lazy { PyRegex.compile("[-+−–]?$NUM") }
    val HOLE_BEFORE: Regex by lazy { PyRegex.compile("""\d\S{0,2}$""") }

    fun symbol(e: JsonElement): Symbol = e.jsonArray.let {
        Symbol(it[0].jsonPrimitive.content, it[1].jsonPrimitive.content, it[2].jsonPrimitive.content,
               it[3].jsonPrimitive.int)
    }

    fun notation(e: JsonElement): Notation = e.jsonObject.let { o ->
        Notation(o.getValue("name").jsonPrimitive.content, (o.getValue("symbols") as JsonArray).map(::symbol),
                 o.getValue("bare").let { if (it is JsonNull) null else it.jsonPrimitive.content },
                 o.getValue("fold").jsonPrimitive.boolean)
    }
}
