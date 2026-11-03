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
 *   literal (a JsonPrimitive's content, as a text gave it or `Double.toString` made it) as its exact decimal value in
 *   plain notation, computed on its digits. A lone surrogate, an exponent written beyond ±[MAX_EXPONENT], an integer
 *   of more than [MAX_INT_DIGITS] digits or nesting deeper than [MAX_DEPTH] is a CanonicalError.
 * - [digest], D(v): the lowercase hex SHA-256 of C(v)'s UTF-8.
 * - [parse]: the strict reading, what Python's `json.loads` reads and nothing it refuses (StrictReader).
 * - [hashStoredJson], H(text), for versions.raw and songs.lyrics_json: null for null, D of what the text holds when
 *   it is JSON and canonicalizable, else the SHA-256 of the text's own bytes as Python's
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

    /** H(text), for versions.raw and songs.lyrics_json. */
    fun hashStoredJson(text: String?): String? {
        if (text == null) return null
        val reader = StrictReader(text)
        val value = try {
            reader.read()
        } catch (e: CanonicalError) {
            return ownBytes(text) // not JSON
        }
        if (reader.lone) return ownBytes(text)
        val canonical = try {
            write(value)
        } catch (e: CanonicalError) {
            return ownBytes(text) // not canonicalizable
        }
        return sha256Hex(JsonText.utf8(canonical))
    }

    private fun ownBytes(text: String) = sha256Hex(JsonText.utf8(text))

    /** The strict reading: literals kept, the last duplicate wins; CanonicalError when not JSON. */
    fun parse(text: String): JsonElement = StrictReader(text).read()

    fun sha256Hex(bytes: ByteArray): String = JsonText.hex(MessageDigest.getInstance("SHA-256").digest(bytes))
}

class CanonicalError(message: String) : Exception(message)
