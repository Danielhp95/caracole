package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest

/**
 * Canonical JSON, its digest and the stored-JSON hash (docs/superpowers/specs/2026-11-03-canonical-json.md; Python's
 * is caracole.canonical, and tests/conformance/vectors/canonical/ holds the two to the byte).
 *
 * - [write], C(v): members sorted by key in code-point order ([KEY_ORDER]), `{"k":v,…}` and `[v,…]` with no spaces,
 *   strings escaped as Python's json writes them with ensure_ascii=False, `true`, `false`, `null`, `NaN`,
 *   `Infinity` and `-Infinity` as they are, an integer literal as its decimal (`-0` as `0`), and any other number
 *   literal (a JsonPrimitive's content) as its exact decimal value in plain notation, computed on its digits. A lone
 *   surrogate, an exponent written beyond ±[MAX_EXPONENT], an integer of more than [MAX_INT_DIGITS] digits or
 *   nesting deeper than [MAX_DEPTH] is a CanonicalError.
 *
 *   A number's literal must be the one Python digests: a stored text's own literal, or a float's repr, which
 *   PyJson.float makes from a Double. Never `JsonPrimitive(Double)`, whose literal is `Double.toString`'s: 5e-324 is
 *   `4.9E-324` there (and 2e23 `1.9999999999999998E23` before JDK 19), another number's exact value, so another
 *   digest than Python's, and a unit that differs after every sync.
 *
 *   C is the text a digest is taken of, not a way to store a value: it writes the float 238.0 as `238` and 1e16 as
 *   `10000000000000000`, which read back as integers. Store a value as PyJson.dumps writes it, which keeps each
 *   literal.
 * - [digest], D(v): the lowercase hex SHA-256 of C(v)'s UTF-8.
 * - [parse]: the strict reading, what Python's `json.loads` reads and nothing it refuses (StrictReader).
 * - [hashStoredJson], H(text), for versions.raw and songs.lyrics_json: null for null, D of what the text holds when
 *   it is JSON and canonicalizable (with the members `without` names taken out of an object it holds: UG's ratings
 *   and votes of a version's raw record, Units.VOLATILE_RAW), else the SHA-256 of the text's own bytes as Python's
 *   `text.encode("utf-8", "surrogatepass")` gives them.
 */
object Canonical {
    /** A literal's written exponent beyond ±this: not canonicalizable. */
    const val MAX_EXPONENT = 1000

    /** Python's int limit (sys.get_int_max_str_digits()): an integer literal of more digits is no JSON. */
    const val MAX_INT_DIGITS = 4300

    /** Arrays and objects nested deeper: not canonicalizable (caracole.canonical.MAX_DEPTH). */
    const val MAX_DEPTH = 512

    /** Object keys by code point, as Python orders its strings (not UTF-16's order: U+FF61 before U+1F3B8). */
    val KEY_ORDER: Comparator<String> = Comparator { a, b ->
        var i = 0
        while (i < a.length && i < b.length) {
            val x = a.codePointAt(i)
            val y = b.codePointAt(i)
            if (x != y) return@Comparator x.compareTo(y)
            i += Character.charCount(x)
        }
        (a.length - i).compareTo(b.length - i)
    }

    /** C(v). */
    fun write(value: JsonElement): String = StringBuilder().also { write(it, value, 0) }.toString()

    private fun write(out: StringBuilder, value: JsonElement, depth: Int) {
        when (value) {
            is JsonNull -> out.append("null")
            is JsonPrimitive -> if (value.isString) string(out, value.content) else out.append(literal(value.content))
            is JsonArray -> {
                if (depth >= MAX_DEPTH) throw CanonicalError("nested deeper than $MAX_DEPTH")
                out.append('[')
                value.forEachIndexed { k, item ->
                    if (k > 0) out.append(',')
                    write(out, item, depth + 1)
                }
                out.append(']')
            }
            is JsonObject -> {
                if (depth >= MAX_DEPTH) throw CanonicalError("nested deeper than $MAX_DEPTH")
                out.append('{')
                value.keys.sortedWith(KEY_ORDER).forEachIndexed { k, key ->
                    if (k > 0) out.append(',')
                    string(out, key)
                    out.append(':')
                    write(out, value.getValue(key), depth + 1)
                }
                out.append('}')
            }
        }
    }

    private fun string(out: StringBuilder, s: String) {
        if (JsonText.hasLoneSurrogate(s)) throw CanonicalError("a lone surrogate")
        JsonText.quote(out, s)
    }

    private fun literal(content: String): String = when (content) {
        "true", "false", "NaN", "Infinity", "-Infinity" -> content
        else -> JsonText.decimal(content)
    }

    /** D(v): the lowercase hex SHA-256 of C(v)'s UTF-8. */
    fun digest(value: JsonElement): String = sha256Hex(JsonText.utf8(write(value)))

    /** H(text), for versions.raw and songs.lyrics_json; [without], members of an object the text holds that are no
     * part of its hash, taken out of it first (its own members alone; a text that holds no object is hashed whole). */
    fun hashStoredJson(text: String?, without: Set<String> = emptySet()): String? {
        if (text == null) return null
        val reader = StrictReader(text)
        val read = try {
            reader.read()
        } catch (e: CanonicalError) {
            return ownBytes(text) // not JSON
        }
        val taken = without.isNotEmpty() && read is JsonObject
        // A lone surrogate is no canonical text, unless it was read in a member taken out.
        if (reader.lone && !(taken && reader.loneKeys.all { it in without })) return ownBytes(text)
        val value = if (taken) JsonObject((read as JsonObject).filterKeys { it !in without }) else read
        val canonical = try {
            write(value)
        } catch (e: CanonicalError) {
            return ownBytes(text) // not canonicalizable
        }
        return sha256Hex(JsonText.utf8(canonical))
    }

    private fun ownBytes(text: String) = sha256Hex(JsonText.utf8(text))

    /**
     * The strict reading: literals kept, the last duplicate wins; CanonicalError when not JSON. A lone surrogate,
     * escaped or raw, reads into a String as it is (and [write] of it is a CanonicalError), but an escaped high
     * surrogate beside a raw low one (or the other way round), two lone surrogates to Python, reads as the pair its
     * UTF-16 units make: [hashStoredJson] tells them apart, and SQLite text never holds a raw one.
     */
    fun parse(text: String): JsonElement = StrictReader(text).read()

    fun sha256Hex(bytes: ByteArray): String = JsonText.hex(MessageDigest.getInstance("SHA-256").digest(bytes))
}

class CanonicalError(message: String) : Exception(message)
