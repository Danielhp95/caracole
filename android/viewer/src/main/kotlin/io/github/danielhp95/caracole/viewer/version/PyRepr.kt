package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import java.math.BigInteger

/**
 * A value as Python holds what json.loads, a form or a file gave it, and its `repr`, `str` and truthiness: the one
 * rule version.py's `setting_problem` (Versions.settingProblem) and progressions.py's `songs_with`
 * (Progressions.songsWith) quote a value by. A number is written as Python writes the int or float it reads, never as
 * its JSON literal (core's PyValues keeps the literal, so it isn't this).
 */
internal object PyRepr {
    /** A value as Python holds it: null for none, a String, a BigInteger for any int, a Boolean, a Double, a List, a
     * Map; anything else as it is. A JsonElement is what json.loads makes of it (JsonNull none). */
    fun plain(value: Any?): Any? = when (value) {
        null, JsonNull -> null
        is JsonPrimitive -> when {
            value.isString -> value.content
            value.content == "true" -> true
            value.content == "false" -> false
            isInteger(value.content) -> BigInteger(value.content)
            else -> value.doubleOrNull ?: value.content
        }
        is JsonArray -> value.map(::plain)
        is JsonObject -> value.mapValues { plain(it.value) }
        is Int -> BigInteger.valueOf(value.toLong())
        is Long -> BigInteger.valueOf(value)
        is Short -> BigInteger.valueOf(value.toLong())
        is Byte -> BigInteger.valueOf(value.toLong())
        is Float -> value.toDouble()
        is List<*> -> value.map(::plain)
        is Map<*, *> -> value.entries.associate { (k, v) -> plain(k) to plain(v) }
        else -> value
    }

    /** Python's `repr` of [value], as [plain] holds it. */
    fun repr(value: Any?): String = when (val v = plain(value)) {
        null -> "None"
        is String -> PyStr.repr(v)
        is Boolean -> if (v) "True" else "False"
        is BigInteger -> v.toString()
        is Double -> when {
            v.isNaN() -> "nan"
            v.isInfinite() -> if (v > 0) "inf" else "-inf"
            else -> PyJson.floatText(v)
        }
        is List<*> -> v.joinToString(", ", "[", "]") { repr(it) }
        is Map<*, *> -> v.entries.joinToString(", ", "{", "}") { (k, e) -> "${repr(k)}: ${repr(e)}" }
        else -> v.toString()
    }

    /** Python's `str` of [value]: a text itself, anything else its [repr]. */
    fun str(value: Any?): String = when (val v = plain(value)) {
        is String -> v
        else -> repr(v)
    }

    /** Whether Python reads [value] as false: None, "", 0, 0.0, False, [], {}. */
    fun falsy(value: Any?): Boolean = when (val v = plain(value)) {
        null -> true
        is String -> v.isEmpty()
        is Boolean -> !v
        is BigInteger -> v.signum() == 0
        is Double -> v == 0.0
        is List<*> -> v.isEmpty()
        is Map<*, *> -> v.isEmpty()
        else -> false
    }

    private fun isInteger(literal: String): Boolean =
        literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }
}
