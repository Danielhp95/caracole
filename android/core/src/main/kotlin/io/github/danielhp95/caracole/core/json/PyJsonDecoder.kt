package io.github.danielhp95.caracole.core.json

import io.github.danielhp95.caracole.core.py.PyFloat
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral

/**
 * json.loads(str) with its defaults, as CPython 3.14's _json.c scans (scan_once_unicode, _parse_object_unicode,
 * _parse_array_unicode, scanstring_unicode, _match_number_unicode) and json.decoder's JSONDecoder.decode: the same
 * values and the same [PyJson.DecodeError]s, each at the place Python names (in code points).
 *
 * By a loop and a stack of the containers open, never recursion, so no depth overflows it (Python's limit is its C
 * stack, a RecursionError the site parsers read as a page that won't parse; this reads such a text whole).
 */
@OptIn(ExperimentalSerializationApi::class)
internal class PyJsonDecoder(private val s: String, private val bomCheck: Boolean = true) {
    private val n = s.length
    private val last = n - 1 // _json.c's end_idx

    fun decode(): JsonElement {
        // json.loads(str)'s own check: bytes are decoded first, and their text isn't checked
        if (bomCheck && s.startsWith("\uFEFF")) throw error("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0)
        val (value, end) = scan(space(0))
        val after = space(end)
        if (after != n) throw error("Extra data", after)
        return value
    }

    private fun error(msg: String, at: Int): PyJson.DecodeError {
        // Python's positions count code points: an astral one is one there, two UTF-16 units here.
        val pos = s.codePointCount(0, at)
        val newline = s.lastIndexOf('\n', at - 1)
        val lineno = 1 + (0 until at).count { s[it] == '\n' }
        val colno = if (newline < 0) pos + 1 else pos - s.codePointCount(0, newline)
        return PyJson.DecodeError(msg, pos, lineno, colno)
    }

    private fun isSpace(c: Char) = c == ' ' || c == '\t' || c == '\n' || c == '\r'

    private fun space(from: Int): Int {
        var i = from
        while (i < n && isSpace(s[i])) i++
        return i
    }

    private class Open(val members: LinkedHashMap<String, JsonElement>?) {
        val items = ArrayList<JsonElement>()
        var key = ""
    }

    /** scan_once at [start] with the containers it opens: the value and the index after it. */
    private fun scan(start: Int): Pair<JsonElement, Int> {
        val stack = ArrayList<Open>()
        var idx = start
        values@ while (true) {
            var value: JsonElement
            if (idx >= n) throw error("Expecting value", idx)
            when (s[idx]) {
                '"' -> {
                    val (text, end) = string(idx + 1)
                    value = JsonPrimitive(text)
                    idx = end
                }
                '{' -> {
                    idx = space(idx + 1)
                    if (idx > last || s[idx] != '}') {
                        val open = Open(LinkedHashMap())
                        idx = key(idx, open)
                        stack.add(open)
                        continue@values
                    }
                    value = JsonObject(emptyMap())
                    idx++
                }
                '[' -> {
                    idx = space(idx + 1)
                    if (idx > last || s[idx] != ']') {
                        stack.add(Open(null))
                        continue@values
                    }
                    value = JsonArray(emptyList())
                    idx++
                }
                else -> {
                    val (scalar, end) = word(idx) ?: number(idx)
                    value = scalar
                    idx = end
                }
            }
            // The value is whole: it goes in the container open around it, which may then close too.
            while (true) {
                val open = stack.lastOrNull() ?: return value to idx
                val members = open.members
                if (members == null) open.items.add(value) else members[open.key] = value
                val close = if (members == null) ']' else '}'
                idx = space(idx)
                if (idx <= last && s[idx] == close) {
                    value = if (members == null) JsonArray(open.items) else JsonObject(members)
                    idx++
                    stack.removeAt(stack.size - 1)
                    continue
                }
                if (idx > last || s[idx] != ',') throw error("Expecting ',' delimiter", idx)
                val comma = idx
                idx = space(idx + 1)
                if (idx <= last && s[idx] == close) {
                    throw error("Illegal trailing comma before end of ${if (members == null) "array" else "object"}",
                                comma)
                }
                if (members != null) idx = key(idx, open)
                continue@values
            }
        }
    }

    /** An object's key at [at], its `:` and the space after it: the index of its value. */
    private fun key(at: Int, open: Open): Int {
        if (at > last || s[at] != '"') throw error("Expecting property name enclosed in double quotes", at)
        val (key, end) = string(at + 1)
        open.key = key
        var idx = space(end)
        if (idx > last || s[idx] != ':') throw error("Expecting ':' delimiter", idx)
        idx = space(idx + 1)
        return idx
    }

    private fun matches(at: Int, word: String): Boolean = s.startsWith(word, at)

    /** null, true, false, NaN, Infinity and -Infinity, each checked as scan_once checks it (a character after it in
     * the text, or the end, for each); null when none is there. */
    private fun word(at: Int): Pair<JsonElement, Int>? = when (s[at]) {
        'n' -> if (at + 3 < n && matches(at, "null")) JsonNull to at + 4 else null
        't' -> if (at + 3 < n && matches(at, "true")) JsonPrimitive(true) to at + 4 else null
        'f' -> if (at + 4 < n && matches(at, "false")) JsonPrimitive(false) to at + 5 else null
        'N' -> if (at + 2 < n && matches(at, "NaN")) JsonUnquotedLiteral("NaN") to at + 3 else null
        'I' -> if (at + 7 < n && matches(at, "Infinity")) JsonUnquotedLiteral("Infinity") to at + 8 else null
        '-' -> if (at + 8 < n && matches(at, "-Infinity")) JsonUnquotedLiteral("-Infinity") to at + 9 else null
        else -> null
    }

    private fun digit(at: Int) = s[at] in '0'..'9'

    /** _match_number_unicode: an int as Python's int writes it (its digits, `-0` as `0`), a float as its repr. */
    private fun number(start: Int): Pair<JsonElement, Int> {
        var idx = start
        if (s[idx] == '-') {
            idx++
            if (idx > last) throw error("Expecting value", start)
        }
        when {
            s[idx] == '0' -> idx++
            digit(idx) -> { idx++; while (idx <= last && digit(idx)) idx++ }
            else -> throw error("Expecting value", start)
        }
        var float = false
        if (idx < last && s[idx] == '.' && digit(idx + 1)) {
            float = true
            idx += 2
            while (idx <= last && digit(idx)) idx++
        }
        if (idx < last && (s[idx] == 'e' || s[idx] == 'E')) {
            val e = idx
            idx++
            if (idx < last && (s[idx] == '-' || s[idx] == '+')) idx++
            while (idx <= last && digit(idx)) idx++
            if (digit(idx - 1)) float = true else idx = e
        }
        val literal = s.substring(start, idx)
        if (float) return PyJson.float(PyFloat.parse(literal)!!) to idx
        val digits = literal.length - (if (literal[0] == '-') 1 else 0)
        if (digits > Canonical.MAX_INT_DIGITS) {
            throw IllegalArgumentException("Exceeds the limit (${Canonical.MAX_INT_DIGITS} digits) for integer " +
                "string conversion: value has $digits digits; use sys.set_int_max_str_digits() to increase the limit")
        }
        return JsonUnquotedLiteral(if (literal == "-0") "0" else literal) to idx
    }

    private fun hex(at: Int): Int = when (val c = s[at]) {
        in '0'..'9' -> c - '0'
        in 'a'..'f' -> c - 'a' + 10
        in 'A'..'F' -> c - 'A' + 10
        else -> -1
    }

    /** Four hex digits at [at]..[at]+3, or -1 at the first that isn't one. */
    private fun hex4(at: Int): Int {
        var v = 0
        for (k in at until at + 4) {
            val d = hex(k)
            if (d < 0) return -1
            v = v shl 4 or d
        }
        return v
    }

    /** scanstring_unicode: [from] is the index after the opening quote; the string and the index after its closing
     * one. An escaped surrogate pair is one code point; an escaped lone surrogate is kept, one UTF-16 unit. */
    private fun string(from: Int): Pair<String, Int> {
        val begin = from - 1
        val out = StringBuilder()
        var end = from
        while (true) {
            var next = end
            var c = '\u0000'
            while (next < n) {
                c = s[next]
                if (c == '"' || c == '\\') break
                if (c <= '\u001f') throw error("Invalid control character at", next)
                next++
            }
            if (next >= n || (c != '"' && c != '\\')) throw error("Unterminated string starting at", begin)
            out.append(s, end, next)
            next++
            if (c == '"') return out.toString() to next
            if (next == n) throw error("Unterminated string starting at", begin)
            val e = s[next]
            if (e != 'u') {
                end = next + 1
                out.append(when (e) {
                    '"' -> '"'
                    '\\' -> '\\'
                    '/' -> '/'
                    'b' -> '\b'
                    'f' -> '\u000C'
                    'n' -> '\n'
                    'r' -> '\r'
                    't' -> '\t'
                    else -> throw error("Invalid \\escape", end - 2)
                })
                continue
            }
            next++
            end = next + 4
            if (end > n) throw error("Invalid \\uXXXX escape", next - 1)
            var unit = hex4(next)
            if (unit < 0) throw error("Invalid \\uXXXX escape", end - 5)
            if (unit in 0xD800..0xDBFF && end + 6 < n && s[end] == '\\' && s[end + 1] == 'u') {
                val low = hex4(end + 2)
                if (low < 0) throw error("Invalid \\uXXXX escape", end + 1)
                if (low in 0xDC00..0xDFFF) {
                    out.append(unit.toChar()).append(low.toChar())
                    end += 6
                    unit = -1
                }
            }
            if (unit >= 0) out.append(unit.toChar())
        }
    }
}

/**
 * bytes.decode(json.detect_encoding(b), "surrogatepass"), as json.loads reads bytes: UTF-32 or UTF-16 by a BOM,
 * UTF-8 with its BOM dropped, else by where the first bytes' zeros are, UTF-8 by default. A lone surrogate encoded
 * passes (surrogatepass); any other ill-formed sequence is Python's UnicodeDecodeError ([IllegalArgumentException],
 * with Python's message for UTF-8).
 */
internal object PyJsonBytes {
    fun decode(b: ByteArray): String {
        fun at(i: Int) = b[i].toInt() and 0xFF
        fun starts(vararg prefix: Int) = b.size >= prefix.size && prefix.indices.all { at(it) == prefix[it] }
        return when {
            starts(0, 0, 0xFE, 0xFF) -> utf32(b, 4, big = true)
            starts(0xFF, 0xFE, 0, 0) -> utf32(b, 4, big = false)
            starts(0xFE, 0xFF) -> utf16(b, 2, big = true)
            starts(0xFF, 0xFE) -> utf16(b, 2, big = false)
            starts(0xEF, 0xBB, 0xBF) -> utf8(b, 3)
            b.size >= 4 && at(0) == 0 -> if (at(1) != 0) utf16(b, 0, big = true) else utf32(b, 0, big = true)
            b.size >= 4 && at(1) == 0 -> if (at(2) != 0 || at(3) != 0) utf16(b, 0, big = false) else utf32(b, 0, big = false)
            b.size == 2 && at(0) == 0 -> utf16(b, 0, big = true)
            b.size == 2 && at(1) == 0 -> utf16(b, 0, big = false)
            else -> utf8(b, 0)
        }
    }

    private fun fail(message: String): Nothing = throw IllegalArgumentException(message)

    /** UTF-8 from [from] (positions in messages count from there, as utf-8-sig's do), CPython's error ranges. */
    private fun utf8(b: ByteArray, from: Int): String {
        val out = StringBuilder(b.size - from)
        var i = from
        val end = b.size
        fun at(k: Int) = b[k].toInt() and 0xFF
        fun cont(k: Int) = k < end && at(k) and 0xC0 == 0x80
        fun raise(start: Int, stop: Int, why: String): Nothing {
            val p = start - from
            val hex = "0123456789abcdef"
            fail(if (stop - start == 1) "'utf-8' codec can't decode byte 0x${hex[at(start) shr 4]}${hex[at(start) and 15]} " +
                     "in position $p: $why"
                 else "'utf-8' codec can't decode bytes in position $p-${stop - from - 1}: $why")
        }
        while (i < end) {
            val c = at(i)
            if (c < 0x80) { out.append(c.toChar()); i++; continue }
            // The decoder's verdict on the sequence at i: its length when it is whole, else where it went wrong.
            when {
                c < 0xC2 -> raise(i, i + 1, "invalid start byte")
                c < 0xE0 -> {
                    if (end - i < 2) raise(i, end, "unexpected end of data")
                    if (!cont(i + 1)) raise(i, i + 1, "invalid continuation byte")
                    out.append((((c and 0x1F) shl 6) or (at(i + 1) and 0x3F)).toChar())
                    i += 2
                }
                c < 0xF0 -> {
                    val second = if (i + 1 < end) at(i + 1) else -1
                    val badSecond = second < 0 || !cont(i + 1) ||
                        (c == 0xE0 && second < 0xA0) || (c == 0xED && second >= 0xA0)
                    val whole = end - i >= 3
                    if (badSecond && i + 1 < end) {
                        // surrogatepass: ED A0–BF 80–BF is a lone surrogate, passed
                        if (c == 0xED && second >= 0xA0 && cont(i + 1) && whole && cont(i + 2)) {
                            out.append((((c and 0x0F) shl 12) or ((second and 0x3F) shl 6) or (at(i + 2) and 0x3F)).toChar())
                            i += 3
                            continue
                        }
                        raise(i, i + 1, "invalid continuation byte")
                    }
                    if (!whole) raise(i, end, "unexpected end of data")
                    if (!cont(i + 2)) raise(i, i + 2, "invalid continuation byte")
                    out.append((((c and 0x0F) shl 12) or ((second and 0x3F) shl 6) or (at(i + 2) and 0x3F)).toChar())
                    i += 3
                }
                c < 0xF5 -> {
                    if (end - i < 2) raise(i, end, "unexpected end of data")
                    val second = at(i + 1)
                    if (!cont(i + 1) || (c == 0xF0 && second < 0x90) || (c == 0xF4 && second >= 0x90)) {
                        raise(i, i + 1, "invalid continuation byte")
                    }
                    if (end - i < 3) raise(i, end, "unexpected end of data")
                    if (!cont(i + 2)) raise(i, i + 2, "invalid continuation byte")
                    if (end - i < 4) raise(i, end, "unexpected end of data")
                    if (!cont(i + 3)) raise(i, i + 3, "invalid continuation byte")
                    out.appendCodePoint(((c and 0x07) shl 18) or ((second and 0x3F) shl 12) or
                                        ((at(i + 2) and 0x3F) shl 6) or (at(i + 3) and 0x3F))
                    i += 4
                }
                else -> raise(i, i + 1, "invalid start byte")
            }
        }
        return out.toString()
    }

    /** UTF-16 from [from]; a lone surrogate passes. */
    private fun utf16(b: ByteArray, from: Int, big: Boolean): String {
        if ((b.size - from) % 2 != 0) fail("'utf-16' codec can't decode byte: truncated data")
        val out = StringBuilder((b.size - from) / 2)
        var i = from
        while (i < b.size) {
            val hi = b[i].toInt() and 0xFF
            val lo = b[i + 1].toInt() and 0xFF
            out.append((if (big) (hi shl 8) or lo else (lo shl 8) or hi).toChar())
            i += 2
        }
        return out.toString()
    }

    /** UTF-32 from [from]; a lone surrogate passes, a code point past U+10FFFF doesn't. */
    private fun utf32(b: ByteArray, from: Int, big: Boolean): String {
        if ((b.size - from) % 4 != 0) fail("'utf-32' codec can't decode bytes: truncated data")
        val out = StringBuilder((b.size - from) / 4)
        var i = from
        while (i < b.size) {
            var cp = 0L
            for (k in 0 until 4) {
                val byte = (b[i + (if (big) k else 3 - k)].toLong() and 0xFF)
                cp = (cp shl 8) or byte
            }
            if (cp > 0x10FFFF) fail("'utf-32' codec can't decode bytes in position ${i - from}-${i - from + 3}: " +
                                    "code point not in range(0x110000)")
            out.appendCodePoint(cp.toInt())
            i += 4
        }
        return out.toString()
    }
}
