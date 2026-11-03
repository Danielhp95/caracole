package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.json.JsonElement

/** json.dumps(value, ensure_ascii=False), byte for byte: kv text (lane canonical). */
object PyJson {
    fun dumps(value: JsonElement, sortKeys: Boolean = false, compact: Boolean = false): String = TODO("lane canonical")
}
