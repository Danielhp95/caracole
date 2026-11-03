package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral

/**
 * The strict reading of the canonical-JSON spec: what Python's `json.loads(text)` reads with its defaults, and
 * nothing it refuses (CanonicalError).
 *
 * - Whitespace is space, `\t`, `\n` and `\r` alone; a BOM, U+00A0 or any other space is no JSON.
 * - A string holds no raw character below U+0020; its escapes are `\" \\ \/ \b \f \n \r \t \uXXXX`, an escaped
 *   high surrogate and the escaped low one right after it one code point.
 * - A number is `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?` in ASCII digits, kept as its literal (the content
 *   of a JsonPrimitive that isn't a string); an integer of more than 4300 digits is refused, as Python's int limit
 *   refuses it. `NaN`, `Infinity` and `-Infinity` are read, kept so too.
 * - When an object repeats a key, the last value wins, in the first one's place, as in a Python dict.
 *
 * It reads by a loop and a stack of the containers open, never recursion, so no depth overflows it (Python's own
 * limit is its C stack). [lone] says whether a string read holds a lone surrogate as Python reads the text: a raw
 * one, an escaped one, or an escaped high surrogate beside a raw low one (or the other way round), which are two
 * lone surrogates in Python even though their UTF-16 units look like a pair.
 */
@OptIn(ExperimentalSerializationApi::class)
internal class StrictReader(private val text: String) {
    private var i = 0
    private val n = text.length

    /** Whether a string read holds a lone surrogate, as Python reads it: such a text is not canonicalizable. */
    var lone = false
        private set

    private class Open(val members: LinkedHashMap<String, JsonElement>?) {
        val items = ArrayList<JsonElement>()
        var key = ""
    }

    fun read(): JsonElement {
        val stack = ArrayList<Open>()
        var value: JsonElement = JsonNull
        skipSpace()
        values@ while (true) {
            when (peek()) {
                '[' -> {
                    i++
                    skipSpace()
                    if (peek() == ']') {
                        i++
                        value = JsonArray(emptyList())
                    } else {
                        stack.add(Open(null))
                        continue@values
                    }
                }
                '{' -> {
                    i++
                    skipSpace()
                    if (peek() == '}') {
                        i++
                        value = JsonObject(emptyMap())
                    } else {
                        val open = Open(LinkedHashMap())
                        open.key = key()
                        stack.add(open)
                        continue@values
                    }
                }
                else -> value = scalar()
            }
            // The value is whole: it goes in the container open around it, which may then close too.
            while (true) {
                val open = stack.lastOrNull() ?: break@values
                skipSpace()
                val members = open.members
                if (members == null) {
                    open.items.add(value)
                    when (next()) {
                        ',' -> { skipSpace(); continue@values }
                        ']' -> { value = JsonArray(open.items); stack.removeAt(stack.size - 1) }
                        else -> fail("Expecting ',' delimiter")
                    }
                } else {
                    members[open.key] = value
                    when (next()) {
                        ',' -> { skipSpace(); open.key = key(); continue@values }
                        '}' -> { value = JsonObject(members); stack.removeAt(stack.size - 1) }
                        else -> fail("Expecting ',' delimiter")
                    }
                }
            }
        }
        skipSpace()
        if (i != n) fail("Extra data")
        return value
    }

    private fun fail(why: String): Nothing = throw CanonicalError("$why at char $i: not JSON")

    private fun peek(): Char? = if (i < n) text[i] else null

    private fun next(): Char? = if (i < n) text[i++] else null

    private fun skipSpace() {
        while (i < n) {
            val c = text[i]
            if (c != ' ' && c != '\t' && c != '\n' && c != '\r') return
            i++
        }
    }

    /** An object's key, its `:` and the space after: [i] is at the key's opening quote. */
    private fun key(): String {
        if (peek() != '"') fail("Expecting property name enclosed in double quotes")
        val key = string()
        skipSpace()
        if (next() != ':') fail("Expecting ':' delimiter")
        skipSpace()
        return key
    }

    private fun word(word: String): Boolean {
        if (i + word.length > n) return false
        for (k in word.indices) if (text[i + k] != word[k]) return false
        i += word.length
        return true
    }

    private fun scalar(): JsonElement = when (peek()) {
        '"' -> JsonPrimitive(string())
        'n' -> if (word("null")) JsonNull else fail("Expecting value")
        't' -> if (word("true")) JsonPrimitive(true) else fail("Expecting value")
        'f' -> if (word("false")) JsonPrimitive(false) else fail("Expecting value")
        'N' -> if (word("NaN")) JsonUnquotedLiteral("NaN") else fail("Expecting value")
        'I' -> if (word("Infinity")) JsonUnquotedLiteral("Infinity") else fail("Expecting value")
        '-' -> if (word("-Infinity")) JsonUnquotedLiteral("-Infinity") else number()
        else -> number()
    }

    private fun digit(at: Int) = at < n && text[at] in '0'..'9'

    /** As Python's scanner matches one: the longest number at [i], an exponent or a fraction left for the text after
     * (which then is no JSON) when no digit follows it. */
    private fun number(): JsonElement {
        val start = i
        if (peek() == '-') i++
        when {
            i < n && text[i] == '0' -> i++
            i < n && text[i] in '1'..'9' -> while (digit(i)) i++
            else -> { i = start; fail("Expecting value") }
        }
        val digits = i - start - (if (text[start] == '-') 1 else 0)
        var integral = true
        if (i < n && text[i] == '.' && digit(i + 1)) {
            integral = false
            i += 2
            while (digit(i)) i++
        }
        if (i < n && (text[i] == 'e' || text[i] == 'E')) {
            val e = i++
            if (i < n && (text[i] == '-' || text[i] == '+')) i++
            if (digit(i)) {
                integral = false
                while (digit(i)) i++
            } else {
                i = e
            }
        }
        if (integral && digits > Canonical.MAX_INT_DIGITS) {
            fail("an integer of more than ${Canonical.MAX_INT_DIGITS} digits (Python's int limit)")
        }
        return JsonUnquotedLiteral(text.substring(start, i))
    }

    private fun hex4(at: Int): Int? {
        if (at + 4 > n) return null
        var v = 0
        for (k in at until at + 4) {
            val c = text[k]
            v = v * 16 + when (c) {
                in '0'..'9' -> c - '0'
                in 'a'..'f' -> c - 'a' + 10
                in 'A'..'F' -> c - 'A' + 10
                else -> return null
            }
        }
        return v
    }

    /** A string: [i] is at its opening quote, and ends past its closing one. */
    private fun string(): String {
        i++
        val out = StringBuilder()
        while (true) {
            if (i >= n) fail("Unterminated string")
            val c = text[i]
            when {
                c == '"' -> { i++; return out.toString() }
                c == '\\' -> escape(out)
                c < ' ' -> fail("Invalid control character")
                Character.isHighSurrogate(c) && i + 1 < n && Character.isLowSurrogate(text[i + 1]) -> {
                    out.append(c).append(text[i + 1]) // one supplementary code point, as Python's str holds it
                    i += 2
                }
                else -> {
                    if (Character.isSurrogate(c)) lone = true
                    out.append(c)
                    i++
                }
            }
        }
    }

    private fun escape(out: StringBuilder) {
        val c = if (i + 1 < n) text[i + 1] else fail("Unterminated string")
        i += 2
        when (c) {
            '"' -> out.append('"')
            '\\' -> out.append('\\')
            '/' -> out.append('/')
            'b' -> out.append('\b')
            'f' -> out.append('\u000C')
            'n' -> out.append('\n')
            'r' -> out.append('\r')
            't' -> out.append('\t')
            'u' -> {
                val unit = hex4(i) ?: fail("Invalid \\uXXXX escape")
                i += 4
                if (unit in 0xD800..0xDBFF && i + 1 < n && text[i] == '\\' && text[i + 1] == 'u') {
                    val low = hex4(i + 2) ?: fail("Invalid \\uXXXX escape")
                    if (low in 0xDC00..0xDFFF) {
                        out.append(unit.toChar()).append(low.toChar())
                        i += 6
                        return
                    }
                }
                if (unit in 0xD800..0xDFFF) lone = true
                out.append(unit.toChar())
            }
            else -> fail("Invalid \\escape")
        }
    }
}
