package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * `json.dumps(value, ensure_ascii=False)`, byte for byte: the kv text db.kv_set_json writes, which Db.kvSetJson
 * writes so (the canonical-JSON spec's "kv text"; tests/conformance/vectors/canonical/pydumps.jsonl).
 *
 * Members in the JsonObject's own order (insertion order), or by code point with [sortKeys] (`sort_keys=True`);
 * `", "` and `": "` between them, or `","` and `":"` when [compact] (`separators=(",", ":")`); strings escaped as
 * Python escapes them; a number written as its literal, the JsonPrimitive's content as given (so a Double made in
 * Kotlin is written as `Double.toString` writes it: build a number as Python's repr writes it when Python's bytes
 * matter). Not canonical: Canonical.write is.
 */
object PyJson {
    fun dumps(value: JsonElement, sortKeys: Boolean = false, compact: Boolean = false): String {
        val out = StringBuilder()
        write(out, value, sortKeys, if (compact) "," else ", ", if (compact) ":" else ": ")
        return out.toString()
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
}
