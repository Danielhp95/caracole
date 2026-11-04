package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.py.Py
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive

/** How the replays read a record's values and show an answer. */
internal fun text(e: JsonElement): String = e.jsonPrimitive.content

internal fun JsonElement.intOrNull(): Int? = if (this is JsonNull) null else jsonPrimitive.int

/** A float as the corpus writes one: a number, or "inf", "-inf", "nan". */
internal fun double(e: JsonElement): Double {
    val p = e as JsonPrimitive
    if (p.isString) return when (p.content) {
        "inf" -> Double.POSITIVE_INFINITY
        "-inf" -> Double.NEGATIVE_INFINITY
        "nan" -> Double.NaN
        else -> throw AssertionError("not a float: $p")
    }
    return p.content.toDouble()
}

internal fun hex(s: String): String = Py.codePoints(s).joinToString(" ", "[", "]") { "%04X".format(it) }

internal fun show(x: Any?): String = when (x) {
    is String -> hex(x)
    is List<*> -> x.joinToString(", ", "[", "]") { show(it) }
    else -> x.toString()
}

internal fun hexBytes(bytes: ByteArray): String {
    val digits = "0123456789abcdef"
    return bytes.joinToString("") { b -> "${digits[b.toInt() shr 4 and 15]}${digits[b.toInt() and 15]}" }
}
