package io.github.danielhp95.caracole.core.sync.internal.units

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * How Python reads a JSON value peer_sync.value_of_document is given (json.loads's): `doc["k"]`, iterating it, its
 * truth, its type. Each failure is the KeyError or TypeError Python raises ([Unread]), which value_of_document turns
 * into a UnitError, so the phone refuses exactly the documents the computer refuses.
 */
internal object Python {
    /** A KeyError or a TypeError of Python's, by [kind]. */
    class Unread(val kind: String, message: String) : Exception(message)

    /** `value[name]`: a KeyError for a member it hasn't got, a TypeError for a value that isn't an object. */
    fun member(value: JsonElement, name: String): JsonElement {
        if (value !is JsonObject) throw Unread("TypeError", "${typeName(value)} indices must be integers, not 'str'")
        return value[name] ?: throw Unread("KeyError", repr(name))
    }

    /** `for item in value`: an array's items, an object's keys, a text's characters; a TypeError for anything else. */
    fun iterate(value: JsonElement): List<JsonElement> = when {
        value is JsonArray -> value
        value is JsonObject -> value.keys.map(::JsonPrimitive)
        value is JsonPrimitive && value.isString -> codePoints(value.content).map(::JsonPrimitive)
        else -> throw Unread("TypeError", "'${typeName(value)}' object is not iterable")
    }

    /** `isinstance(value, str)`'s text, else a TypeError. */
    fun text(value: JsonElement): String {
        if (value is JsonPrimitive && value.isString) return value.content
        throw Unread("TypeError", "${pyValue(value)} isn't text")
    }

    /** `bool(value)`. */
    fun truthy(value: JsonElement): Boolean = when {
        value is JsonNull -> false
        value is JsonPrimitive && value.isString -> value.content.isNotEmpty()
        value is JsonPrimitive -> when (value.content) {
            "true" -> true
            "false" -> false
            else -> !isZero(value.content)
        }
        value is JsonArray -> value.isNotEmpty()
        value is JsonObject -> value.isNotEmpty()
        else -> true
    }

    /** `type(value) is int`: a number written as an integer, `-?[0-9]+` (json.loads reads no other one as an int). */
    fun isInt(value: JsonElement): Boolean =
        value is JsonPrimitive && !value.isString && value !is JsonNull && isIntegerLiteral(value.content)

    /** A literal json.loads reads as an int. */
    fun isIntegerLiteral(literal: String): Boolean {
        val digits = literal.removePrefix("-")
        return digits.isNotEmpty() && digits.all { it in '0'..'9' }
    }

    /** `value == n` in Python, for a JSON number (2 == 2.0, True == 1 but not 2); false for anything else. */
    fun numberEquals(value: JsonElement?, n: Int): Boolean {
        if (value !is JsonPrimitive || value.isString || value is JsonNull) return false
        val literal = value.content
        return when {
            literal == "true" -> n == 1
            literal == "false" -> n == 0
            isIntegerLiteral(literal) -> BigInteger(literal) == BigInteger.valueOf(n.toLong())
            else -> literal.toDoubleOrNull()?.let { it == n.toDouble() } ?: false
        }
    }

    /** Whether a number's literal reads as zero: an int's digits, or the float json.loads makes of it. */
    private fun isZero(literal: String): Boolean = when {
        literal == "NaN" || literal == "Infinity" || literal == "-Infinity" -> false
        isIntegerLiteral(literal) -> literal.removePrefix("-").all { it == '0' }
        else -> literal.toDoubleOrNull() == 0.0
    }

    private fun codePoints(s: String): List<String> {
        val out = ArrayList<String>()
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            val n = Character.charCount(cp)
            out.add(s.substring(i, i + n))
            i += n
        }
        return out
    }

    private fun typeName(value: JsonElement): String = when {
        value is JsonNull -> "NoneType"
        value is JsonArray -> "list"
        value is JsonObject -> "dict"
        value is JsonPrimitive && value.isString -> "str"
        value is JsonPrimitive && (value.content == "true" || value.content == "false") -> "bool"
        value is JsonPrimitive && isIntegerLiteral(value.content) -> "int"
        else -> "float"
    }

    private fun pyValue(value: JsonElement): String = when {
        value is JsonNull -> "None"
        value is JsonPrimitive && value.isString -> repr(value.content)
        value is JsonPrimitive && value.content == "true" -> "True"
        value is JsonPrimitive && value.content == "false" -> "False"
        else -> value.toString()
    }

    /** A text as Python's repr quotes it (its quotes; control characters are left as they are). */
    fun repr(s: String): String = if ('\'' in s && '"' !in s) "\"$s\"" else "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
}
