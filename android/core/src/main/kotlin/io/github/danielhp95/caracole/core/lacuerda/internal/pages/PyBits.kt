package io.github.danielhp95.caracole.core.lacuerda.internal.pages

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import java.math.BigInteger
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** The bits of Python's str and int lacuerda.py and lacuerda_search.py lean on, on code points. */
internal object PyBits {
    /** str.lstrip(): Python's whitespace off the start. */
    fun lstrip(s: String): String {
        var start = 0
        while (start < s.length && PyUnicode.isSpace(s.codePointAt(start))) start += Character.charCount(s.codePointAt(start))
        return s.substring(start)
    }

    /** str.rstrip(): Python's whitespace off the end. */
    fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }

    /** `" ".join(s.split())`: Python's whitespace runs as one space, none at either end. */
    fun collapsed(s: String): String = Py.split(s).joinToString(" ")

    /** `len(s.encode("utf-8"))` of a text that holds no lone surrogate (a page's text never does). */
    fun utf8Length(s: String): Int {
        var n = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            n += when {
                cp < 0x80 -> 1
                cp < 0x800 -> 2
                cp < 0x10000 -> 3
                else -> 4
            }
            i += Character.charCount(cp)
        }
        return n
    }

    /**
     * `int(c, 36)` of one code point: an ASCII digit or letter its value (a–z and A–Z 10 to 35), a decimal digit of
     * any script its digit (as int() reads one, _PyUnicode_TransformDecimalAndSpaceToASCII); null where Python raises
     * ValueError (a space, an underscore, a sign, any other character).
     */
    fun base36(cp: Int): Int? = when {
        cp in '0'.code..'9'.code -> cp - '0'.code
        cp in 'a'.code..'z'.code -> cp - 'a'.code + 10
        cp in 'A'.code..'Z'.code -> cp - 'A'.code + 10
        cp < 0x7F -> null
        PyUnicode.isSpace(cp) -> null
        PyUnicode.isDecimal(cp) -> decimal(cp)
        else -> null
    }

    /** A decimal digit's value: its place in its run of ten, as Unicode encodes each script's 0–9. */
    private fun decimal(cp: Int): Int {
        var start = cp
        while (PyUnicode.isDecimal(start - 1)) start--
        return (cp - start) % 10
    }

    /** urlsplit(href).path; ValueError's words as [PyUrl.Invalid]. */
    fun path(href: String): String = PyUrl.urlsplit(href).path

    /** `str(value)` of what json.loads made of [value]: a text itself, `True`, `None`, an int's digits, a float's
     * repr (`1e+100`, `inf`), a list's and an object's repr. */
    fun str(value: JsonElement): String = when {
        value is JsonPrimitive && value.isString -> value.content
        else -> repr(value)
    }

    private fun repr(value: JsonElement): String = when (value) {
        is JsonNull -> "None"
        is JsonArray -> value.joinToString(", ", "[", "]") { repr(it) }
        is JsonObject -> value.entries.joinToString(", ", "{", "}") { "${PyStr.repr(it.key)}: ${repr(it.value)}" }
        is JsonPrimitive -> when {
            value.isString -> PyStr.repr(value.content)
            value.content == "true" -> "True"
            value.content == "false" -> "False"
            isInt(value.content) -> BigInteger(value.content).toString()
            else -> floatRepr(value.content)
        }
    }

    private fun isInt(literal: String): Boolean =
        literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }

    /** A JSON float literal as Python's float repr writes it: `1e+100`, `2.5`, `inf`, `nan`. */
    private fun floatRepr(literal: String): String = when (literal) {
        "NaN" -> "nan"
        "Infinity" -> "inf"
        "-Infinity" -> "-inf"
        else -> {
            val x = literal.toDouble()
            when {
                x.isNaN() -> "nan"
                x.isInfinite() -> if (x > 0) "inf" else "-inf"
                else -> PyJson.floatText(x)
            }
        }
    }
}
