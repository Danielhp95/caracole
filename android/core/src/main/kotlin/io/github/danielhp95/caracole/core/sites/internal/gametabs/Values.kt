package io.github.danielhp95.caracole.core.sites.internal.gametabs

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
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
 * What gametabs.py does with the values json.loads makes of a page's `data-tab` (PyJson.loads: its numbers' literals
 * in Python's int or float form, NaN and the infinities by their JSON words): Python's truth of each, `str()` of each,
 * `isinstance(v, int)` and gametabs._number.
 */
internal object Values {
    /** A literal json.loads reads as an int: digits, a minus maybe, no fraction or exponent. */
    fun isInt(e: JsonElement?): Boolean = e is JsonPrimitive && !e.isString && e !is JsonNull && integer(e.content)

    /** A literal json.loads reads as a float (NaN and the infinities among them). */
    fun isFloat(e: JsonElement?): Boolean =
        e is JsonPrimitive && !e.isString && e !is JsonNull && !bool(e) && !integer(e.content)

    fun bool(e: JsonElement?): Boolean = e is JsonPrimitive && !e.isString && (e.content == "true" || e.content == "false")

    /** `isinstance(v, int) and not isinstance(v, bool)`'s value, else null. */
    fun int(e: JsonElement?): BigInteger? = if (isInt(e)) BigInteger((e as JsonPrimitive).content) else null

    /** A text's value, else null. */
    fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Python's truth of the value: none, false, 0, 0.0, "", [] and {} are false; NaN is true. */
    fun truthy(e: JsonElement?): Boolean = when {
        e == null || e is JsonNull -> false
        e is JsonArray -> e.isNotEmpty()
        e is JsonObject -> e.isNotEmpty()
        e is JsonPrimitive && e.isString -> e.content.isNotEmpty()
        e is JsonPrimitive && bool(e) -> e.content == "true"
        e is JsonPrimitive && integer(e.content) -> BigInteger(e.content).signum() != 0
        e is JsonPrimitive -> float(e.content).let { it.isNaN() || it != 0.0 }
        else -> true
    }

    /** `str(v or "")`. */
    fun strOr(e: JsonElement?): String = if (truthy(e)) str(e!!) else ""

    /** `" ".join(str(v or "").split())`. */
    fun collapsed(e: JsonElement?): String = collapse(strOr(e))

    fun collapse(s: String): String = Py.split(s).joinToString(" ")

    /** `str(v)`: a text itself, anything else its repr. */
    fun str(e: JsonElement): String = text(e) ?: repr(e)

    private fun repr(e: JsonElement): String = when {
        e is JsonNull -> "None"
        e is JsonArray -> e.joinToString(", ", "[", "]") { repr(it) }
        e is JsonObject -> e.entries.joinToString(", ", "{", "}") { "${PyStr.repr(it.key)}: ${repr(it.value)}" }
        e is JsonPrimitive && e.isString -> PyStr.repr(e.content)
        e is JsonPrimitive && e.content == "true" -> "True"
        e is JsonPrimitive && e.content == "false" -> "False"
        e is JsonPrimitive && integer(e.content) -> BigInteger(e.content).toString()
        e is JsonPrimitive -> floatRepr(e.content)
        else -> e.toString()
    }

    /** gametabs._number: an int or a float's value as a float, null for anything else (a truth too) and for one not
     * finite; an int too large for a float is Python's OverflowError (math.isfinite converts it first). */
    fun number(e: JsonElement?): Double? {
        if (e !is JsonPrimitive || e.isString || e is JsonNull || bool(e)) return null
        if (integer(e.content)) {
            val d = BigInteger(e.content).toDouble()
            if (d.isInfinite()) throw OverflowError("int too large to convert to float")
            return d
        }
        val d = float(e.content)
        return if (d.isNaN() || d.isInfinite()) null else d
    }

    /** `int(x)` of a finite float: toward zero, exactly. */
    fun truncated(x: Double): BigInteger = BigDecimal(x).toBigInteger()

    /** `round(x)` of a finite float: to the nearest int, ties to the even one, exactly. */
    fun rounded(x: Double): BigInteger = BigDecimal(x).setScale(0, java.math.RoundingMode.HALF_EVEN).toBigInteger()

    private fun integer(literal: String): Boolean =
        literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }

    private fun float(literal: String): Double = when (literal) {
        "NaN" -> Double.NaN
        "Infinity" -> Double.POSITIVE_INFINITY
        "-Infinity" -> Double.NEGATIVE_INFINITY
        else -> PyFloat.parse(literal) ?: error("not a float's literal: $literal")
    }

    private fun floatRepr(literal: String): String = when (literal) {
        "NaN" -> "nan"
        "Infinity" -> "inf"
        "-Infinity" -> "-inf"
        else -> PyJson.floatText(float(literal))
    }
}

/** Python's OverflowError, where gametabs.py lets one through (an int too large for a float in a page's data). */
internal class OverflowError(message: String) : ArithmeticException(message)
