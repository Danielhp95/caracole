package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import java.math.BigInteger
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A reading pinned, overrides.toml's `[harmonica]` (harptab.py's "A reading pinned"): `check_spec`, `pinned` and
 * `spec_of`. A spec is JSON: a notation's name, or a table, `as` a preset (signs by default) and each other entry a
 * symbol and what it means. What check_spec refuses is an IllegalArgumentException in Python's words, its values
 * written as Python's repr writes them (a string quoted, `None`, `True`, a float's shortest digits, a list's or a
 * table's members).
 */
internal object Pins {
    private val B = HarptabData

    private fun names(names: List<String>, last: String = "or"): String =
        if (names.size > 1) "${names.dropLast(1).joinToString(", ")} $last ${names.last()}" else names.last()

    /** harptab._pin_symbol: a pin's table entry as a symbol. */
    private fun pinSymbol(key: String, word: JsonElement): Symbol {
        val stripped = Py.strip(key)
        if (stripped.isEmpty() || key != stripped || Py.len(key) > 12) {
            throw IllegalArgumentException("expected a symbol, as the tab writes it, got ${PyStr.repr(key)}")
        }
        val said = (word as? JsonPrimitive)?.takeIf { it.isString }?.content
        val meant = said?.let { B.PIN_WORDS[it] }
            ?: throw IllegalArgumentException("${PyStr.repr(key)}: expected what a symbol means " +
                                              "(${names(B.PIN_WORDS.keys.toList())}), got ${repr(word)}")
        return Legends.template(key, meant.first, meant.second)
            ?: throw IllegalArgumentException("${PyStr.repr(key)}: a hole alone, or in brackets, can only be a blow or a draw")
    }

    fun checkSpec(spec: JsonElement) {
        if (spec is JsonPrimitive && spec.isString) {
            if (spec.content !in B.PIN_NAMES) throw IllegalArgumentException("expected ${names(B.PIN_NAMES)}, got ${repr(spec)}")
            return
        }
        if (spec !is JsonObject) {
            throw IllegalArgumentException("expected a notation's name or a table of what its symbols mean, got ${repr(spec)}")
        }
        val base = spec["as"] ?: JsonPrimitive(B.PRESETS[0].name)
        if (!(base is JsonPrimitive && base.isString && base.content in B.PRESET)) {
            throw IllegalArgumentException("as: expected ${names(B.PRESET.keys.toList())}, got ${repr(base)}")
        }
        for ((key, word) in spec) if (key != "as") pinSymbol(key, word)
    }

    fun pinned(spec: JsonElement, body: String): Notation? {
        checkSpec(spec)
        val prepared = Weighing.prepared(body, null)
        val lines = prepared.read
        val holey = lines.filter { B.DIGIT.find(it) != null }
        var notation: Notation? = when {
            spec is JsonPrimitive && spec.content == "legend" -> {
                val placed = prepared.legends.flatMap { it.symbols }.mapNotNull { Legends.where(it, holey) }.distinct()
                Legends.withLegend(placed, holey)?.first
            }
            spec is JsonPrimitive -> B.PRESET.getValue(spec.content)
            else -> {
                val table = spec as JsonObject
                val placed = table.filterKeys { it != "as" }.mapNotNull { (key, word) -> Legends.where(pinSymbol(key, word), holey) }
                val base = B.PRESET.getValue((table["as"] as? JsonPrimitive)?.content ?: B.PRESETS[0].name)
                val bare = placed.firstOrNull { it.at == "bare" }?.means ?: ""
                val text = holey.joinToString("\n")
                val changes = placed.filter { it.at != "bare" }.toMutableList()
                changes += changes.toList().mapNotNull { s ->
                    val swapped = HarpTabText.swapcase(s.text)
                    if (!base.fold && s.text != swapped && swapped in text) s.copy(text = swapped) else null
                }
                base.changed(changes, bare = bare)
            }
        }
        if (notation != null && Weighing.dotted(lines)) notation = notation.changed(listOf(B.DOTS))
        return notation
    }

    fun specOf(reading: Reading): JsonElement {
        if (reading.source == "legend") return JsonPrimitive("legend")
        val notation = reading.notation
        val base = B.PRESET.getValue(notation.name)
        val changed = notation.symbols.filter { it != B.DOTS && it !in base.symbols }
        if (changed.isEmpty() && notation.bare == base.bare) return JsonPrimitive(notation.name)
        val spec = LinkedHashMap<String, JsonElement>()
        spec["as"] = JsonPrimitive(notation.name)
        if (notation.bare != base.bare && notation.bare != null) spec["4"] = JsonPrimitive(notation.bare)
        for (s in changed) {
            val key = when (s.at) {
                "before" -> "${s.text}4"
                "around" -> Py.slice(s.text, 0, 1) + "4" + Py.slice(s.text, 1, null)
                "between" -> "4${s.text}4"
                else -> s.text
            }
            spec[key] = JsonPrimitive(if (s.means != "bend" || s.count == 1) s.means
                                      else listOf("double bend", "triple bend")[s.count - 2])
        }
        return JsonObject(spec)
    }

    /** Python's repr of a value read from JSON. */
    fun repr(value: JsonElement): String = when (value) {
        is JsonNull -> "None"
        is JsonPrimitive -> when {
            value.isString -> PyStr.repr(value.content)
            value.content == "true" -> "True"
            value.content == "false" -> "False"
            isInteger(value.content) -> BigInteger(value.content).toString()
            else -> value.content.toDouble().let {
                when {
                    it.isNaN() -> "nan"
                    it == Double.POSITIVE_INFINITY -> "inf"
                    it == Double.NEGATIVE_INFINITY -> "-inf"
                    else -> PyJson.floatText(it)
                }
            }
        }
        is JsonArray -> value.joinToString(", ", "[", "]") { repr(it) }
        is JsonObject -> value.entries.joinToString(", ", "{", "}") { (k, v) -> PyStr.repr(k) + ": " + repr(v) }
    }

    /** A JSON number written as an integer: Python's int. */
    private fun isInteger(s: String): Boolean = s.removePrefix("-").let { it.isNotEmpty() && it.all { c -> c in '0'..'9' } }
}
