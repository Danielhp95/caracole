package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What songs.py keeps beside a song's row, and how it reads its JSON columns. */
internal object SongKv {
    /** songs._PER_SONG_KV: kv kept under a song's id, `<prefix><id>` or `<prefix><id>:<more>`, which goes with the
     * song (SQLite may give its id to the next song). */
    val PER_SONG = listOf(
        "render:", "render:files:", "render:export:", "render:progressions:", "ug:artist_page_checked:",
        "lyrics:failed:", "megalobiz:checked:", "azlyrics:checked:",
        "autochords:failed:", "gtptabs:checked:", "harptabs:checked:", "gametabs:checked:", "ug:blocked:", "youtube:",
        "sheet_versions:same:",
        "sheet_versions:yours:", "sheet_versions:unkeepable:",
    )

    /** songs.KEY_VERSION_KV: the normalize.KEY_VERSION the stored keys were made with. */
    const val KEY_VERSION = "songs:key_version"

    /** wanted.FIRST_SEEN_KEY: when a wanted.txt line's song was first seen, by its key (the computer's; a fixture
     * or a re-keying brings them to the phone). */
    const val FIRST_SEEN = "wanted:first_seen:"

    /** wanted.SOURCE: a song's source as songs.upsert_song gives it, its id the song's identity key. */
    const val WANTED = "wanted"

    /** The kv of `<prefix><id>` and `<prefix><id>:…`, gone. */
    fun deletePrefixed(db: Db, prefix: String, id: Long) {
        val own = "$prefix$id"
        db.execute("DELETE FROM kv WHERE key = ? OR substr(key, 1, ?) = ?", own, own.length + 1, "$own:")
    }

    /** songs.delete_song_kv. */
    fun deleteSongKv(db: Db, id: Long) = PER_SONG.forEach { deletePrefixed(db, it, id) }

    /** A JSON column's text read as json.loads reads it; null for text that isn't JSON. */
    fun json(text: String?): JsonElement? = text?.let { runCatching { Canonical.parse(it) }.getOrNull() }

    /** A `source_ids` column: each source's ids in order. */
    fun sourceIds(text: String): LinkedHashMap<String, MutableList<JsonElement>> {
        val out = LinkedHashMap<String, MutableList<JsonElement>>()
        (json(text) as? JsonObject)?.forEach { (source, ids) ->
            out[source] = ((ids as? JsonArray)?.toMutableList() ?: mutableListOf())
        }
        return out
    }

    /** songs._add_ids: each id of [more] that [ids] lacks, after its source's ids there. */
    fun addIds(ids: LinkedHashMap<String, MutableList<JsonElement>>, more: Map<String, List<JsonElement>>) =
        ids.also {
            for ((source, values) in more) {
                val bucket = ids.getOrPut(source) { mutableListOf() }
                for (v in values) if (v !in bucket) bucket.add(v)
            }
        }

    /** source ids as songs.py writes them, json.dumps(ids, ensure_ascii=False). */
    fun idsText(ids: Map<String, List<JsonElement>>): String =
        io.github.danielhp95.caracole.core.json.PyJson.dumps(JsonObject(ids.mapValues { JsonArray(it.value) }))

    /** A list of names as songs.py writes `artists`. */
    fun namesText(names: List<String>): String =
        io.github.danielhp95.caracole.core.json.PyJson.dumps(JsonArray(names.map { JsonPrimitive(it) }))
}
