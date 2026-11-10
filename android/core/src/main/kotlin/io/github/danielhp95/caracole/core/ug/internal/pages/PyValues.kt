package io.github.danielhp95.caracole.core.ug.internal.pages

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal
import java.math.BigInteger

/**
 * What ug/page.py asks of a value json.loads gave, as Python answers it: its truth (`not d.get("type")`), `float()`
 * of it (`_number`), `str()` of it (`_text`, a list's and an object's as their repr), and the value with each lone
 * surrogate of its strings U+FFFD (`_whole`).
 *
 * A value is PyJson.loads' (or a corpus line's): a number is a JsonPrimitive whose content is its literal, a float
 * where it holds `.`, `e` or `E`, or is `NaN`, `Infinity` or `-Infinity`, an int otherwise; `true` and `false` are
 * Python's bools (an int, 1 and 0, to `float()`).
 */
internal object PyValues {
    private fun isBool(p: JsonPrimitive): Boolean = !p.isString && p !is JsonNull && (p.content == "true" || p.content == "false")

    private fun isFloat(literal: String): Boolean =
        literal == "NaN" || literal == "Infinity" || literal == "-Infinity" || literal.any { it == '.' || it == 'e' || it == 'E' }

    /** The double a number's literal is, as Python's json reads a float and `float()` takes an int: the nearest. A
     * literal past the doubles' range is infinite, where `float()` of so big an int raises OverflowError, which
     * ug/page.py doesn't catch: no page UG writes has one. */
    private fun double(literal: String): Double = PyFloat.parse(literal)!!

    /** bool(value). */
    fun truthy(value: JsonElement?): Boolean = when (value) {
        null, JsonNull -> false
        is JsonObject -> value.isNotEmpty()
        is JsonArray -> value.isNotEmpty()
        is JsonPrimitive -> when {
            value.isString -> value.content.isNotEmpty()
            isBool(value) -> value.content == "true"
            isFloat(value.content) -> double(value.content).let { it != 0.0 }  // NaN is true, as in Python
            else -> BigInteger(value.content).signum() != 0
        }
    }

    /** ug/page.py's `_number`: `float(value)`, null for what it refuses (TypeError, ValueError) and for a value
     * that isn't finite. */
    fun number(value: JsonElement?): Double? {
        val n = when (value) {
            null, JsonNull, is JsonObject, is JsonArray -> null
            is JsonPrimitive -> when {
                value.isString -> PyFloat.parse(value.content)
                isBool(value) -> if (value.content == "true") 1.0 else 0.0
                else -> double(value.content)
            }
        }
        return n?.takeIf { it.isFinite() }
    }

    /** ug/page.py's `json_int`: a whole number (`float(value)` integral), else null. */
    fun jsonInt(value: JsonElement?): BigInteger? {
        val n = number(value) ?: return null
        if (n != Math.floor(n)) return null
        return BigDecimal(n).toBigInteger()
    }

    /** ug/page.py's `_text`: "" for null, else `str(value)`. */
    fun text(value: JsonElement?): String = when (value) {
        null, JsonNull -> ""
        is JsonPrimitive -> if (value.isString) value.content else repr(value)
        else -> repr(value)
    }

    /** repr(value), as `str()` writes a list's or an object's members. */
    fun repr(value: JsonElement): String = when (value) {
        JsonNull -> "None"
        is JsonObject -> value.entries.joinToString(", ", "{", "}") { (k, v) -> PyStr.repr(k) + ": " + repr(v) }
        is JsonArray -> value.joinToString(", ", "[", "]") { repr(it) }
        is JsonPrimitive -> when {
            value.isString -> PyStr.repr(value.content)
            isBool(value) -> if (value.content == "true") "True" else "False"
            isFloat(value.content) -> floatRepr(double(value.content))
            else -> BigInteger(value.content).toString()
        }
    }

    /** repr(x) of a float: json.dumps' text but `inf`, `-inf` and `nan`. */
    fun floatRepr(x: Double): String = when {
        x.isNaN() -> "nan"
        x == Double.POSITIVE_INFINITY -> "inf"
        x == Double.NEGATIVE_INFINITY -> "-inf"
        else -> PyJson.floatText(x)
    }

    /**
     * ug/page.py's `_whole`: [value] with each lone surrogate of its strings, its keys too, U+FFFD. A Kotlin string
     * holds a surrogate pair json.loads made one character as that pair; a half alone is a surrogate with no other
     * half beside it. Two keys that become one keep the first one's place and the last one's value, as Python's dict
     * comprehension does.
     */
    fun whole(value: JsonElement): JsonElement = when (value) {
        is JsonObject -> {
            val out = LinkedHashMap<String, JsonElement>(value.size)
            for ((k, v) in value) out[whole(k)] = whole(v)
            JsonObject(out)
        }
        is JsonArray -> JsonArray(value.map { whole(it) })
        is JsonPrimitive -> if (value.isString && lone(value.content) >= 0) JsonPrimitive(whole(value.content)) else value
    }

    /** [s] with each lone surrogate U+FFFD. */
    fun whole(s: String): String {
        val first = lone(s)
        if (first < 0) return s
        val out = StringBuilder(s.length)
        out.append(s, 0, first)
        var i = first
        while (i < s.length) {
            val c = s[i]
            when {
                Character.isHighSurrogate(c) && i + 1 < s.length && Character.isLowSurrogate(s[i + 1]) -> {
                    out.append(c).append(s[i + 1])
                    i += 2
                    continue
                }
                Character.isSurrogate(c) -> out.append('�')
                else -> out.append(c)
            }
            i++
        }
        return out.toString()
    }

    /** Where [s]'s first lone surrogate is, or -1. */
    private fun lone(s: String): Int {
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (Character.isHighSurrogate(c) && i + 1 < s.length && Character.isLowSurrogate(s[i + 1])) {
                i += 2
                continue
            }
            if (Character.isSurrogate(c)) return i
            i++
        }
        return -1
    }

    /** Whether a JSON text escapes half of a surrogate pair (`\udc00`, `\uD83D`): the one way a lone surrogate gets
     * into what json.loads gives, and so where [whole] has anything to do. */
    fun escapesASurrogate(json: String): Boolean {
        var i = json.indexOf("\\u")
        while (i >= 0) {
            if (i + 3 < json.length && (json[i + 2] == 'd' || json[i + 2] == 'D') &&
                (json[i + 3] in '8'..'9' || json[i + 3] in 'a'..'f' || json[i + 3] in 'A'..'F')) return true
            i = json.indexOf("\\u", i + 2)
        }
        return false
    }
}
