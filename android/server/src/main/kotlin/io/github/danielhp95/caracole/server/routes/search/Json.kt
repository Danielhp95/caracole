package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Response
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

// The search routes' JSON as search_routes.py writes its dicts: members in the order Python puts them, a float as
// Python's repr writes it (PyJson.float, never JsonPrimitive(Double)), an int as an int.

/** A dict literal: each value made JSON by [json]. */
internal fun obj(vararg members: Pair<String, Any?>): JsonObject {
    val map = LinkedHashMap<String, JsonElement>(members.size * 2)
    for ((name, value) in members) map[name] = json(value)
    return JsonObject(map)
}

/** `{**a, **b}`: [b]'s members after [a]'s, a name both have keeping [a]'s place with [b]'s value, as a dict does. */
internal infix fun JsonObject.with(b: Map<String, JsonElement>): JsonObject {
    val map = LinkedHashMap<String, JsonElement>(this)
    map.putAll(b)
    return JsonObject(map)
}

/** A Python value as JSON: None, a str, a bool, an int, a float (Python's literal), a list, a dict. */
internal fun json(value: Any?): JsonElement = when (value) {
    null -> JsonNull
    is JsonElement -> value
    is String -> JsonPrimitive(value)
    is Boolean -> JsonPrimitive(value)
    is Int -> JsonPrimitive(value)
    is Long -> JsonPrimitive(value)
    is Double -> PyJson.float(value)
    is List<*> -> JsonArray(value.map { json(it) })
    is Map<*, *> -> {
        val map = LinkedHashMap<String, JsonElement>(value.size * 2)
        for ((k, v) in value) map[k as String] = json(v)
        JsonObject(map)
    }
    else -> throw IllegalArgumentException("no JSON for ${value::class.simpleName}")
}

/** app.py's json_response: `json.dumps(data, ensure_ascii=False, separators=(",", ":"))`, in UTF-8. */
internal fun jsonResponse(status: Int, data: JsonElement): Response = Response(
    status, Body.Bytes(PyJson.dumps(data, compact = true).toByteArray(Charsets.UTF_8)),
    mutableListOf("Content-Type" to App.JSON),
)

/** A member's text, "" for none (a row's `artist`, `title`, `ug`). */
internal fun JsonObject.text(name: String): String = (this[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: ""
