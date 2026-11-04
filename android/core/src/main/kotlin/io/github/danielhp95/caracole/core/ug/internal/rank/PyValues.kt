package io.github.danielhp95.caracole.core.ug.internal.rank

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What sheet_versions.py does with the values json.loads makes of a kv record: db.kv_get_json's reading, and
 * Python's `str()` of each. */
internal object PyValues {
    /** db.kv_get_json: the record's JSON as json.loads reads it (PyJson's), null for no record. */
    fun kvJson(db: Db, key: String): JsonElement? = db.kvGet(key)?.let { PyJson.loads(it) }

    /** `str(value)` of the value json.loads makes of [e]: a text itself, anything else its repr. */
    fun str(e: JsonElement): String = if (e is JsonPrimitive && e.isString) e.content else repr(e)

    private fun repr(e: JsonElement): String = when {
        e is JsonNull -> "None"
        e is JsonArray -> e.joinToString(", ", "[", "]") { repr(it) }
        e is JsonObject -> e.entries.joinToString(", ", "{", "}") { "${PyStr.repr(it.key)}: ${repr(it.value)}" }
        e is JsonPrimitive && e.isString -> PyStr.repr(e.content)
        e is JsonPrimitive && e.content == "true" -> "True"
        e is JsonPrimitive && e.content == "false" -> "False"
        e is JsonPrimitive && integer(e.content) -> e.content.toBigInteger().toString()
        e is JsonPrimitive -> float(e.content)
        else -> e.toString()
    }

    /** A literal json.loads reads as an int: digits, a minus maybe, no fraction or exponent. */
    private fun integer(literal: String): Boolean =
        literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }

    /** repr of the float json.loads reads a literal as (NaN and the infinities as Python names them). */
    private fun float(literal: String): String = when (literal) {
        "NaN" -> "nan"
        "Infinity" -> "inf"
        "-Infinity" -> "-inf"
        else -> literal.toDouble().let { if (it.isInfinite()) (if (it > 0) "inf" else "-inf") else PyJson.floatText(it) }
    }
}
