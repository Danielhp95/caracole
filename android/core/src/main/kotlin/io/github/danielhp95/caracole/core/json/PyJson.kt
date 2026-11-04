package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral
import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode

/**
 * `json.dumps(value, ensure_ascii=False)`, byte for byte: the kv text db.kv_set_json writes, which Db.kvSetJson
 * writes so (the canonical-JSON spec's "kv text"; tests/conformance/vectors/canonical/pydumps.jsonl).
 *
 * Members in the JsonObject's own order (insertion order), or by code point with [sortKeys] (`sort_keys=True`);
 * `", "` and `": "` between them, or `","` and `":"` when [compact] (`separators=(",", ":")`); strings escaped as
 * Python escapes them; a number written as its literal, the JsonPrimitive's content as given. Not canonical:
 * Canonical.write is.
 *
 * A number's literal is Python's when a text Python wrote gave it, or when [float] made it from a Double. Never
 * `JsonPrimitive(Double)`: its literal is `Double.toString`'s (`1.0E-7`, `1.9999999999999998E23`, `4.9E-324`), not
 * the repr Python writes (`1e-07`, `2e+23`, `5e-324`), so neither this text nor Canonical's digest would be Python's.
 */
@OptIn(ExperimentalSerializationApi::class)
object PyJson {
    fun dumps(value: JsonElement, sortKeys: Boolean = false, compact: Boolean = false): String {
        val out = StringBuilder()
        write(out, value, sortKeys, if (compact) "," else ", ", if (compact) ":" else ": ")
        return out.toString()
    }

    /** The Python float [value] as a JSON number: its literal [floatText]'s, for PyJson.dumps and Canonical alike. */
    fun float(value: Double): JsonPrimitive = JsonUnquotedLiteral(floatText(value))

    /**
     * `json.dumps(value)` of the float [value] (tests/conformance/vectors/canonical/float_text.jsonl): `NaN`,
     * `Infinity` and `-Infinity`, else Python's repr. Its digits are the fewest that read back as [value] (with the
     * reading's ties to the even double), the nearest to it of those (ties to the even digit); written plain between
     * 1e-4 and 1e16 (`0.0001`, `238.0`, `9999999999999998.0`), else as one digit, the rest after a point and an
     * exponent of two digits or more (`1e-05`, `1e+16`, `2.5e-10`). Exact arithmetic from the double's bits, never
     * `Double.toString`'s digits.
     */
    fun floatText(value: Double): String {
        if (value.isNaN()) return "NaN"
        if (value == Double.POSITIVE_INFINITY) return "Infinity"
        if (value == Double.NEGATIVE_INFINITY) return "-Infinity"
        val sign = if (value.toRawBits() < 0) "-" else ""
        if (value == 0.0) return sign + "0.0"
        val (digits, point) = shortest(value.toRawBits() and Long.MAX_VALUE)
        return sign + reprLayout(digits, point)
    }

    private val FIVE = BigInteger.valueOf(5)

    /** m × 2^e, exactly. */
    private fun dyadic(m: Long, e: Int): BigDecimal = if (e >= 0) {
        BigDecimal(BigInteger.valueOf(m).shiftLeft(e))
    } else {
        BigDecimal(BigInteger.valueOf(m).multiply(FIVE.pow(-e)), -e)
    }

    /** A positive finite double's shortest digits (no trailing zero) and the point's place: 0.digits × 10^point. */
    private fun shortest(bits: Long): Pair<String, Int> {
        val biased = (bits ushr 52).toInt()
        val fraction = bits and 0xFFFFFFFFFFFFFL
        val m = if (biased == 0) fraction else fraction or (1L shl 52)
        val e = if (biased == 0) -1074 else biased - 1075
        val exact = dyadic(m, e)
        // What reads as this double: halfway to each neighbour, the one below nearer at a power of two; each end
        // included when m is even, as a reading rounds a tie to the even double.
        val up = dyadic(1, e - 1)
        val low = exact.subtract(if (fraction == 0L && biased > 1) dyadic(1, e - 2) else up)
        val high = exact.add(up)
        val ends = m and 1L == 0L
        fun reads(c: BigDecimal): Boolean {
            val above = c.compareTo(low)
            val below = c.compareTo(high)
            return if (ends) above >= 0 && below <= 0 else above > 0 && below < 0
        }
        val lead = exact.precision() - exact.scale() - 1 // exact is in [10^lead, 10^(lead+1))
        for (count in 1..17) {
            val scale = count - 1 - lead // the multiples of 10^-scale have `count` digits from the lead
            val floor = exact.setScale(scale, RoundingMode.FLOOR)
            val ceiling = exact.setScale(scale, RoundingMode.CEILING)
            val down = reads(floor)
            val upward = reads(ceiling)
            if (!down && !upward) continue
            val pick = when {
                !upward -> floor
                !down -> ceiling
                else -> when (exact.subtract(floor).compareTo(ceiling.subtract(exact))) {
                    -1 -> floor
                    1 -> ceiling
                    else -> if (floor.unscaledValue().testBit(0)) ceiling else floor
                }
            }
            val plain = pick.stripTrailingZeros()
            val digits = plain.unscaledValue().toString()
            return digits to digits.length - plain.scale()
        }
        throw IllegalStateException("no 17 digits read as the double ${java.lang.Long.toHexString(bits)}")
    }

    /** float_repr_style 'short' with repr's 'r' layout (CPython's format_float_short). */
    private fun reprLayout(digits: String, point: Int): String {
        if (point <= -4 || point > 16) {
            val exponent = point - 1
            val magnitude = if (exponent < 0) -exponent else exponent
            return digits.substring(0, 1) + (if (digits.length > 1) "." + digits.substring(1) else "") +
                (if (exponent < 0) "e-" else "e+") + (if (magnitude < 10) "0" else "") + magnitude
        }
        return when {
            point <= 0 -> "0." + "0".repeat(-point) + digits
            point >= digits.length -> digits + "0".repeat(point - digits.length) + ".0"
            else -> digits.substring(0, point) + "." + digits.substring(point)
        }
    }

    private fun write(out: StringBuilder, value: JsonElement, sortKeys: Boolean, item: String, key: String) {
        when (value) {
            is JsonNull -> out.append("null")
            is JsonPrimitive -> if (value.isString) JsonText.quote(out, value.content) else out.append(value.content)
            is JsonArray -> {
                out.append('[')
                value.forEachIndexed { k, element ->
                    if (k > 0) out.append(item)
                    write(out, element, sortKeys, item, key)
                }
                out.append(']')
            }
            is JsonObject -> {
                out.append('{')
                val names = if (sortKeys) value.keys.sortedWith(Canonical.KEY_ORDER) else value.keys
                names.forEachIndexed { k, name ->
                    if (k > 0) out.append(item)
                    JsonText.quote(out, name)
                    out.append(key)
                    write(out, value.getValue(name), sortKeys, item, key)
                }
                out.append('}')
            }
        }
    }

    // --- milestone 4's additions (lane py-sites) ---------------------------------------------------------------------

    /**
     * json.loads: order kept, a duplicate key at its first place with its last value, NaN and Infinity, big ints,
     * lone surrogates as UTF-16 units; numbers as literals in Python's int or float form ([float]).
     */
    fun loads(text: String): JsonElement = TODO("lane py-sites")

    /** json.dumps(v, indent=, ensure_ascii=, sort_keys=), Python's separators for an indent (",", ": "). */
    fun dumps(value: JsonElement, indent: Int?, ensureAscii: Boolean = false, sortKeys: Boolean = false): String =
        TODO("lane py-sites")
}
