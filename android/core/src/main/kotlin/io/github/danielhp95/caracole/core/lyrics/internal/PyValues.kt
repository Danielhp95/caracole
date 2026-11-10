package io.github.danielhp95.caracole.core.lyrics.internal

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.internal.PyRepr
import io.github.danielhp95.caracole.core.py.PyFloat
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Duration
import java.time.Instant

/**
 * What the lyrics sites' readers ask of a JSON value as Python's json.loads gives it (core.json.PyJson.loads: a number
 * a literal in Python's int or float form), and of a stored time:
 *
 * - [isInt], `isinstance(v, int) and not isinstance(v, bool)`; [intOrBool], `isinstance(v, int)` alone (a bool is an
 *   int to Python: True is 1), each as the BigInteger it holds;
 * - [number], `float(v)` of an int or a float, never a bool (lyrics._float, megalobiz._number);
 * - [string], a text's or null; [truthy], Python's `bool(v)`;
 * - [repr], Python's `repr` of the value (`{v!r}` in a parse error's words), [reprFloat] a float's;
 * - [before], stamps.before: a stored time older than [Instant] − [Duration], or none, or unreadable.
 */
internal object PyValues {
    private fun literal(v: JsonElement?): String? = (v as? JsonPrimitive)?.takeIf { !it.isString && v !is JsonNull }?.content

    private fun isBool(literal: String) = literal == "true" || literal == "false"

    private fun isIntLiteral(literal: String): Boolean {
        val digits = literal.removePrefix("-")
        return digits.isNotEmpty() && digits.all { it in '0'..'9' }
    }

    fun isInt(v: JsonElement?): Boolean = literal(v)?.let(::isIntLiteral) == true

    fun bigInt(v: JsonElement?): BigInteger? = literal(v)?.takeIf(::isIntLiteral)?.let(::BigInteger)

    /** `isinstance(v, int)`: an int, or a bool as 1 or 0. */
    fun intOrBool(v: JsonElement?): BigInteger? {
        val literal = literal(v) ?: return null
        return when {
            literal == "true" -> BigInteger.ONE
            literal == "false" -> BigInteger.ZERO
            isIntLiteral(literal) -> BigInteger(literal)
            else -> null
        }
    }

    /** `float(v)` of a JSON int or float, null for anything else (a bool among them); an int too big for a float is
     * Python's OverflowError, an ArithmeticException. */
    fun number(v: JsonElement?): Double? {
        val literal = literal(v) ?: return null
        if (isBool(literal)) return null
        if (isIntLiteral(literal)) {
            val d = BigInteger(literal).toDouble()
            if (d.isInfinite()) throw ArithmeticException("int too large to convert to float")
            return d
        }
        return PyFloat.parse(literal)
    }

    fun string(v: JsonElement?): String? = (v as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Python's `bool(v)` of a JSON value. */
    fun truthy(v: JsonElement?): Boolean = when (v) {
        null, JsonNull -> false
        is JsonObject -> v.isNotEmpty()
        is JsonArray -> v.isNotEmpty()
        is JsonPrimitive -> when {
            v.isString -> v.content.isNotEmpty()
            v.content == "false" -> false
            v.content == "true" -> true
            isIntLiteral(v.content) -> BigInteger(v.content).signum() != 0
            else -> PyFloat.parse(v.content)?.let { it != 0.0 } ?: true
        }
    }

    /** Python's repr of a float: `nan`, `inf`, `-inf`, else what json.dumps writes (float.__repr__). */
    fun reprFloat(x: Double): String = when {
        x.isNaN() -> "nan"
        x == Double.POSITIVE_INFINITY -> "inf"
        x == Double.NEGATIVE_INFINITY -> "-inf"
        else -> PyJson.floatText(x)
    }

    /** Python's repr of a value json.loads gave (null: a key `.get` didn't find, None). */
    fun repr(v: JsonElement?): String = when (v) {
        null, JsonNull -> "None"
        is JsonObject -> v.entries.joinToString(", ", "{", "}") { (k, e) -> PyRepr.str(k) + ": " + repr(e) }
        is JsonArray -> v.joinToString(", ", "[", "]") { repr(it) }
        is JsonPrimitive -> when {
            v.isString -> PyRepr.str(v.content)
            v.content == "true" -> "True"
            v.content == "false" -> "False"
            isIntLiteral(v.content) -> BigInteger(v.content).toString()
            else -> reprFloat(PyFloat.parse(v.content) ?: Double.NaN)
        }
    }

    /** stamps.before(value, now − [age]): a stored time older than that, or missing, or unreadable. */
    fun before(value: String?, now: Instant, age: Duration): Boolean {
        val cutoff = Stamps.micros(now) - age.seconds * 1_000_000L - age.nano / 1000
        val at = Stamps.parse(value) ?: return true
        return at < cutoff
    }
}
