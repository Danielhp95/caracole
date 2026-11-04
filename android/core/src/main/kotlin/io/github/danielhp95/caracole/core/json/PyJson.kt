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
 * Python escapes them; a number written as its literal, the JsonPrimitive's content as given; a value nested deeper
 * than [MAX_DEPTH], a [RecursionError]. Not canonical: Canonical.write is.
 *
 * A number's literal is Python's when a text Python wrote gave it, or when [float] made it from a Double. Never
 * `JsonPrimitive(Double)`: its literal is `Double.toString`'s (`1.0E-7`, `1.9999999999999998E23`, `4.9E-324`), not
 * the repr Python writes (`1e-07`, `2e+23`, `5e-324`), so neither this text nor Canonical's digest would be Python's.
 */
@OptIn(ExperimentalSerializationApi::class)
object PyJson {
    fun dumps(value: JsonElement, sortKeys: Boolean = false, compact: Boolean = false): String {
        val out = StringBuilder()
        write(out, value, sortKeys, if (compact) "," else ", ", if (compact) ":" else ": ", 0)
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

    private fun write(out: StringBuilder, value: JsonElement, sortKeys: Boolean, item: String, key: String, level: Int) {
        when (value) {
            is JsonNull -> out.append("null")
            is JsonPrimitive -> if (value.isString) JsonText.quote(out, value.content) else out.append(value.content)
            is JsonArray -> {
                if (level >= MAX_DEPTH) throw tooDeep("encoding a JSON object")
                out.append('[')
                value.forEachIndexed { k, element ->
                    if (k > 0) out.append(item)
                    write(out, element, sortKeys, item, key, level + 1)
                }
                out.append(']')
            }
            is JsonObject -> {
                if (level >= MAX_DEPTH) throw tooDeep("encoding a JSON object")
                out.append('{')
                val names = if (sortKeys) value.keys.sortedWith(Canonical.KEY_ORDER) else value.keys
                names.forEachIndexed { k, name ->
                    if (k > 0) out.append(item)
                    JsonText.quote(out, name)
                    out.append(key)
                    write(out, value.getValue(name), sortKeys, item, key, level + 1)
                }
                out.append('}')
            }
        }
    }

    // --- milestone 4's additions (lane py-sites) ---------------------------------------------------------------------

    /**
     * Python's json.JSONDecodeError, a ValueError: [msg] at [pos], counted in code points as Python counts them, its
     * message `"<msg>: line L column C (char P)"`. (An integer of more than 4,300 digits is Python's plain
     * ValueError, an [IllegalArgumentException] too; a byte that isn't the text's encoding, its UnicodeDecodeError.)
     */
    class DecodeError(val msg: String, val pos: Int, val lineno: Int, val colno: Int) :
        IllegalArgumentException("$msg: line $lineno column $colno (char $pos)")

    /**
     * The most containers [loads] reads, and the dumps write, one inside another: past it, [RecursionError].
     * Canonical's own bound (caracole.canonical.MAX_DEPTH), so that whatever loads gives can be digested too.
     *
     * Python's json raises its RecursionError past what its C stack holds (about 50,000 deep on the computer, the
     * site parsers reading it as a page that won't parse), a limit of the machine's; the phone's is this, the one
     * place it answers otherwise than Python: a text nested deeper is no page any site sends, and the dumps (as
     * every walk of a JsonElement, its toString among them) recurse, a frame or more a container, on a lookup's
     * thread, whose stack on ART is about 1 MiB.
     */
    const val MAX_DEPTH = Canonical.MAX_DEPTH

    /** Python's RecursionError where json nests deeper than [MAX_DEPTH]: an [IllegalArgumentException], as each
     * site parser catches it beside a [DecodeError]. */
    class RecursionError(message: String) : IllegalArgumentException(message)

    internal fun tooDeep(doing: String) = RecursionError("maximum nesting depth ($MAX_DEPTH) exceeded while $doing")

    /**
     * json.loads(text), Python 3.14's with its defaults (PyJsonDecoder): order kept, a duplicate key at its first
     * place with its last value, NaN and Infinity, big integers (to 4,300 digits), lone-surrogate escapes as UTF-16
     * units; numbers as literals in Python's int or float form ([float]: `1E2` is `100.0`, `-0` is `0`, `1e400`
     * `Infinity`). [DecodeError] where Python raises it, with its message; [RecursionError] past [MAX_DEPTH].
     */
    fun loads(text: String): JsonElement = PyJsonDecoder(text).decode()

    /** json.loads(bytes), as http.py's Response.json reads an answer: the bytes decoded as json.detect_encoding says
     * (UTF-8 by default, its BOM dropped), lone surrogates passed, then read as [loads] reads a text. */
    fun loads(bytes: ByteArray): JsonElement = PyJsonDecoder(PyJsonBytes.decode(bytes), bomCheck = false).decode()

    /**
     * json.dumps(v, indent=, ensure_ascii=, sort_keys=), byte for byte: with an [indent], each member and item on a
     * line of its own, [indent] spaces deeper than its container (0 still breaks lines), `,` after each but the last
     * and `": "` after a key, an empty container as `[]` or `{}`; without one, [dumps]'s `", "` and `": "`.
     * [ensureAscii] writes every character outside ' '–'~' as `\uXXXX` (lowercase hex, an astral one as its two
     * surrogates). Numbers as their literals, as [dumps] writes them. A value nested deeper than [MAX_DEPTH] is a
     * [RecursionError], as it is for [dumps].
     */
    fun dumps(value: JsonElement, indent: Int?, ensureAscii: Boolean = false, sortKeys: Boolean = false): String {
        if (indent == null && !ensureAscii) return dumps(value, sortKeys = sortKeys)
        val out = StringBuilder()
        writeIndented(out, value, indent?.let { " ".repeat(maxOf(it, 0)) }, 0, ensureAscii, sortKeys)
        return out.toString()
    }

    private fun writeIndented(out: StringBuilder, value: JsonElement, step: String?, level: Int, ascii: Boolean,
                              sortKeys: Boolean) {
        fun string(s: String) = if (ascii) quoteAscii(out, s) else JsonText.quote(out, s)
        fun newline(depth: Int) {
            if (step == null) return
            out.append('\n')
            repeat(depth) { out.append(step) }
        }
        val item = if (step == null) ", " else ","
        if ((value is JsonArray || value is JsonObject) && level >= MAX_DEPTH) throw tooDeep("encoding a JSON object")
        when (value) {
            is JsonNull -> out.append("null")
            is JsonPrimitive -> if (value.isString) string(value.content) else out.append(value.content)
            is JsonArray -> {
                if (value.isEmpty()) { out.append("[]"); return }
                out.append('[')
                value.forEachIndexed { k, element ->
                    if (k > 0) out.append(item)
                    newline(level + 1)
                    writeIndented(out, element, step, level + 1, ascii, sortKeys)
                }
                newline(level)
                out.append(']')
            }
            is JsonObject -> {
                if (value.isEmpty()) { out.append("{}"); return }
                out.append('{')
                val names = if (sortKeys) value.keys.sortedWith(Canonical.KEY_ORDER) else value.keys
                names.forEachIndexed { k, name ->
                    if (k > 0) out.append(item)
                    newline(level + 1)
                    string(name)
                    out.append(": ")
                    writeIndented(out, value.getValue(name), step, level + 1, ascii, sortKeys)
                }
                newline(level)
                out.append('}')
            }
        }
    }

    private const val HEX = "0123456789abcdef"

    /** json.encoder's encode_basestring_ascii: `"` `\\` and the five short escapes, every other UTF-16 unit outside
     * ' '–'~' as `\\uXXXX`. */
    private fun quoteAscii(out: StringBuilder, s: String) {
        out.append('"')
        for (c in s) {
            when (c) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\b' -> out.append("\\b")
                '\u000C' -> out.append("\\f")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                else -> if (c < ' ' || c > '~') {
                    val v = c.code
                    out.append("\\u").append(HEX[v shr 12]).append(HEX[(v shr 8) and 15]).append(HEX[(v shr 4) and 15])
                        .append(HEX[v and 15])
                } else {
                    out.append(c)
                }
            }
        }
        out.append('"')
    }
}
