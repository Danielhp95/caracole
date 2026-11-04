package io.github.danielhp95.caracole.core.library.internal.overrides

import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * An entry's value as overrides.py holds it, read from the canonical JSON `phone_overrides` keeps: the TOML value
 * tomllib reads (a text, an int, a float, a truth, a list, a table) is the JSON value of the same shape, and a
 * message quotes it as Python's `{value!r}` does.
 */
internal object PyValues {
    /** `isinstance(value, str)`'s text, else null. */
    fun text(value: JsonElement): String? = (value as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun literal(value: JsonElement): String? =
        (value as? JsonPrimitive)?.takeIf { !it.isString && it !is JsonNull }?.content

    /** `isinstance(value, int) and not isinstance(value, bool)`: a number written as an integer. */
    fun int(value: JsonElement): BigInteger? {
        val literal = literal(value) ?: return null
        val digits = literal.removePrefix("-")
        if (digits.isEmpty() || !digits.all { it in '0'..'9' }) return null
        return BigInteger(literal)
    }

    /** Python's repr of the value: a text quoted, a truth True or False, a list and a table as Python writes them. */
    fun repr(value: JsonElement): String = when {
        value is JsonNull -> "None"
        value is JsonPrimitive && value.isString -> PyStr.repr(value.content)
        value is JsonPrimitive && value.content == "true" -> "True"
        value is JsonPrimitive && value.content == "false" -> "False"
        value is JsonPrimitive -> value.content
        value is JsonArray -> value.joinToString(", ", "[", "]") { repr(it) }
        value is JsonObject -> value.entries.joinToString(", ", "{", "}") { (k, v) -> PyStr.repr(k) + ": " + repr(v) }
        else -> value.toString()
    }

    /** Python's `str(value)`: a text itself, anything else its repr. */
    fun str(value: JsonElement): String = text(value) ?: repr(value)

    /** overrides._strings: a text as one, a list of texts as it is; anything else refused, [where] naming it. */
    fun strings(value: JsonElement, where: String): List<String> {
        text(value)?.let { return listOf(it) }
        if (value is JsonArray) {
            val texts = value.map { text(it) }
            if (texts.all { it != null }) return texts.map { it!! }
        }
        throw OverridesError("$where: expected a string or a list of strings")
    }
}
