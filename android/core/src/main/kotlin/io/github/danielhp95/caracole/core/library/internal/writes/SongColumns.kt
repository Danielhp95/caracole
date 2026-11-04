package io.github.danielhp95.caracole.core.library.internal.writes

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/** songs.update_song's columns and how it stores a value in each. */
internal object SongColumns {
    /** songs._COLUMNS: songs.Song's fields, the `songs` table's columns (vectors/library/writes.jsonl's
     * update_song records name every one Python refuses besides). */
    val ALL: List<String> = listOf(
        "id", "key", "artist", "title", "artists", "album", "duration_ms", "isrc", "source_ids", "added_at", "variant",
        "status", "review", "match_decision", "match_step", "match_score", "match_artist_key", "match_song_key",
        "match_candidates", "matched_at", "ug_dirty", "ug_checked_at", "lyrics_status", "lyrics_json", "lyrics_at",
        "lacuerda_checked_at", "audio_path", "audio_mtime", "autochords_mtime", "created_at", "updated_at",
    )
    private val known = ALL.toSet()

    /** songs._JSON_COLUMNS: stored as JSON (json.dumps, ensure_ascii=False). */
    val JSON = setOf("artists", "source_ids", "match_candidates")

    /** songs._BOOL_COLUMNS: stored as 0 or 1. */
    val BOOL = setOf("review", "ug_dirty")

    /** update_song's refusal: ValueError's words, Python's. */
    fun check(names: Collection<String>) {
        val unknown = names.filter { it !in known && it != "id" }.distinct().sortedWith(Canonical.KEY_ORDER)
        if (unknown.isNotEmpty() || "id" in names) {
            throw IllegalArgumentException("unknown or read-only song field(s): " +
                                               (unknown.ifEmpty { listOf("id") }).joinToString(", "))
        }
    }

    /** The value as update_song stores it in [column]: a JSON column's JSON text (null stays null), a boolean
     * column's 0 or 1 (`int(bool(value))`), any other as given. */
    fun stored(column: String, value: Any?): Any? = when {
        column in JSON && value != null -> PyJson.dumps(json(value))
        column in BOOL -> if (truthy(value)) 1L else 0L
        else -> value
    }

    /** Python's bool(value) of what a caller passes: None, False, 0, 0.0, "" and an empty list or dict are false. */
    fun truthy(value: Any?): Boolean = when (value) {
        null -> false
        is Boolean -> value
        is Int -> value != 0
        is Long -> value != 0L
        is Double -> value != 0.0
        is String -> value.isNotEmpty()
        is Collection<*> -> value.isNotEmpty()
        is Map<*, *> -> value.isNotEmpty()
        is JsonNull -> false
        is JsonArray -> value.isNotEmpty()
        is JsonObject -> value.isNotEmpty()
        is JsonPrimitive -> when {
            value.isString -> value.content.isNotEmpty()
            value.booleanOrNull != null -> value.booleanOrNull!!
            else -> value.doubleOrNull?.let { it != 0.0 } ?: true
        }
        else -> true
    }

    /** A value a caller gives a JSON column, as the JSON json.dumps writes of it. */
    private fun json(value: Any?): JsonElement = when (value) {
        null -> JsonNull
        is JsonElement -> value
        is String -> JsonPrimitive(value)
        is Boolean -> JsonPrimitive(value)
        is Int -> JsonPrimitive(value)
        is Long -> JsonPrimitive(value)
        is Double -> PyJson.float(value)
        is List<*> -> JsonArray(value.map { json(it) })
        is Map<*, *> -> JsonObject(value.entries.associate { (k, v) ->
            (k as? String ?: throw IllegalArgumentException("a JSON object's keys are strings, not $k")) to json(v)
        })
        else -> throw IllegalArgumentException("no JSON for a ${value::class.simpleName}")
    }
}
