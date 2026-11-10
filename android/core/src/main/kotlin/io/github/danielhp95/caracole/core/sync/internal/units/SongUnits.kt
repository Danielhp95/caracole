package io.github.danielhp95.caracole.core.sync.internal.units

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.sync.internal.units.Python.iterate
import io.github.danielhp95.caracole.core.sync.internal.units.Python.member
import io.github.danielhp95.caracole.core.sync.internal.units.Python.truthy
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A song unit (peer_sync.song_value, song_document, _song_value_of): what a song is, as JSON, its document whole,
 * and its value read back from a document. Its versions come in SQL's `ORDER BY provider, tab_id` (SQLite's BINARY
 * order: tab "101" before "99"), its files by name, and never re-sorted here.
 */
internal object SongUnits {
    /** A song record's columns a song document carries (peer_sync.SONG_COLUMNS). */
    val SONG_COLUMNS = listOf(
        "status", "review", "match_decision", "match_step", "match_score", "match_artist_key", "match_song_key",
        "match_candidates", "matched_at", "ug_dirty", "ug_checked_at", "lyrics_status", "lyrics_json", "lyrics_at",
        "lacuerda_checked_at",
    )

    /** A version's columns a song document carries (peer_sync.VERSION_COLUMNS). */
    val VERSION_COLUMNS = listOf(
        "provider", "tab_id", "slot", "kind", "rating", "votes", "version", "label", "coverage", "url", "raw",
        "fetched_at", "pick_rank", "gone",
    )

    /** The per-song kv a song unit carries (peer_sync.CARRIED_KV). */
    val CARRIED_KV = listOf("sheet_versions:yours:", "sheet_versions:unkeepable:", "sheet_versions:same:")

    /** song_value. */
    fun value(db: Db, song: SongRow): JsonObject {
        val row = Cells.row(
            db, "SELECT status, review, match_decision, match_artist_key, match_song_key, lyrics_status, lyrics_json " +
                "FROM songs WHERE id = ?", song.id,
        ) ?: throw IllegalStateException("no song of id ${song.id}")
        val versions = Cells.rows(
            db, "SELECT provider, tab_id, slot, kind, label, pick_rank, gone, url, raw FROM versions WHERE song_id = ? " +
                "ORDER BY provider, tab_id", song.id,
        ).map { v ->
            obj(
                "provider" to v.getValue("provider"), "tab" to v.getValue("tab_id"), "slot" to v.getValue("slot"),
                "kind" to v.getValue("kind"), "label" to v.getValue("label"), "pick" to v.getValue("pick_rank"),
                "gone" to JsonPrimitive(truthy(v.getValue("gone"))), "url" to v.getValue("url"),
                "raw" to raw(v.getValue("provider"), Cells.text(v.getValue("raw"))),
            )
        }
        val files = LinkedHashMap<String, JsonElement>()
        for (f in Cells.rows(db, "SELECT name, sha256 FROM files WHERE song_id = ? ORDER BY name", song.id)) {
            files[Cells.text(f.getValue("name")) ?: f.getValue("name").toString()] = f.getValue("sha256")
        }
        return obj(
            "names" to names(song),
            "status" to row.getValue("status"),
            "review" to JsonPrimitive(truthy(row.getValue("review"))),
            "match" to JsonArray(listOf(row.getValue("match_decision"), row.getValue("match_artist_key"),
                                        row.getValue("match_song_key"))),
            "lyrics" to JsonArray(listOf(row.getValue("lyrics_status"), stored(Cells.text(row.getValue("lyrics_json"))))),
            "versions" to JsonArray(versions),
            "files" to JsonObject(files),
            "overrides" to OverridesStore.songEntries(db, song.key),
        )
    }

    /** peer_sync._names: the song's names as its wanted.txt line gives them. */
    private fun names(song: SongRow): JsonObject = obj(
        "artist" to JsonPrimitive(song.artist),
        "artists" to JsonArray(song.artists.map(::JsonPrimitive)),
        "title" to JsonPrimitive(song.title),
        "album" to JsonPrimitive(song.album),
        "duration_ms" to JsonPrimitive(song.durationMs),
        "variant" to JsonPrimitive(song.variant),
    )

    /** song_document: the names, the record's cells as stored, the versions with their kept files, the carried kv
     * (keyed `prefix|rest`) and the overrides.toml entries. */
    fun document(db: Db, song: SongRow, value: JsonObject): JsonObject {
        val row = Cells.row(db, "SELECT ${SONG_COLUMNS.joinToString(", ")} FROM songs WHERE id = ?", song.id)
            ?: throw IllegalStateException("no song of id ${song.id}")
        val versions = Cells.rows(
            db, "SELECT id, ${VERSION_COLUMNS.joinToString(", ")} FROM versions WHERE song_id = ? ORDER BY provider, tab_id",
            song.id,
        ).map { v ->
            val id = v.getValue("id").let { (it as JsonPrimitive).content.toLong() }
            val files = Cells.rows(
                db, "SELECT name, sha256, kept_rank FROM files WHERE version_id = ? ORDER BY name", id,
            ).map { f -> obj("name" to f.getValue("name"), "sha256" to f.getValue("sha256"), "kept_rank" to f.getValue("kept_rank")) }
            JsonObject(LinkedHashMap<String, JsonElement>().apply {
                for (c in VERSION_COLUMNS) put(c, v.getValue(c))
                put("files", JsonArray(files))
            })
        }
        val carried = LinkedHashMap<String, JsonElement>()
        for (prefix in CARRIED_KV) {
            val own = "$prefix${song.id}" // ASCII, so its length is Python's len()
            for (kv in Cells.rows(db, "SELECT key, value FROM kv WHERE key = ? OR substr(key, 1, ?) = ?",
                                  own, own.length + 1, "$own:")) {
                carried[prefix + "|" + Cells.text(kv.getValue("key"))!!.substring(own.length)] = kv.getValue("value")
            }
        }
        return obj(
            "key" to JsonPrimitive(song.key),
            "names" to value.getValue("names"),
            "song" to JsonObject(LinkedHashMap<String, JsonElement>().apply { for (c in SONG_COLUMNS) put(c, row.getValue(c)) }),
            "versions" to JsonArray(versions),
            "kv" to JsonObject(carried),
            "overrides" to value.getValue("overrides"),
        )
    }

    /** _song_value_of: song_value from a song_document, its versions and files in the document's order. Every
     * KeyError and TypeError Python's raises is an [Python.Unread]. */
    fun valueOf(doc: JsonObject): JsonObject {
        val record = member(doc, "song")
        val names = member(doc, "names")
        val overrides = member(doc, "overrides")
        if (record !is JsonObject || names !is JsonObject || overrides !is JsonObject) {
            throw Python.Unread("TypeError", "a song, names or overrides that aren't objects")
        }
        val versions = ArrayList<JsonElement>()
        val files = LinkedHashMap<String, JsonElement>()
        for (version in iterate(member(doc, "versions"))) {
            val raw = member(version, "raw")
            if (raw !is JsonNull && !(raw is JsonPrimitive && raw.isString)) {
                throw Python.Unread("TypeError", "a raw record that isn't text")
            }
            versions.add(obj(
                "provider" to member(version, "provider"), "tab" to member(version, "tab_id"),
                "slot" to member(version, "slot"), "kind" to member(version, "kind"),
                "label" to member(version, "label"), "pick" to member(version, "pick_rank"),
                "gone" to JsonPrimitive(truthy(member(version, "gone"))), "url" to member(version, "url"),
                "raw" to raw(member(version, "provider"), Cells.text(raw)),
            ))
            for (f in iterate(member(version, "files"))) {
                files[Python.text(member(f, "name"))] = member(f, "sha256")
            }
        }
        val lyricsJson = member(record, "lyrics_json")
        if (lyricsJson !is JsonNull && !(lyricsJson is JsonPrimitive && lyricsJson.isString)) {
            throw Python.Unread("TypeError", "lyrics that aren't text")
        }
        return obj(
            "names" to names,
            "status" to member(record, "status"),
            "review" to JsonPrimitive(truthy(member(record, "review"))),
            "match" to JsonArray(listOf(member(record, "match_decision"), member(record, "match_artist_key"),
                                        member(record, "match_song_key"))),
            "lyrics" to JsonArray(listOf(member(record, "lyrics_status"), stored(Cells.text(lyricsJson)))),
            "versions" to JsonArray(versions),
            "files" to JsonObject(files.entries.sortedWith { a, b -> Canonical.KEY_ORDER.compare(a.key, b.key) }
                                      .associateTo(LinkedHashMap()) { it.key to it.value }),
            "overrides" to overrides,
        )
    }

    /** The stored-JSON hash a value holds for a raw record or a song's lyrics (canonical.stored_hash). */
    private fun stored(text: String?): JsonElement = JsonPrimitive(Canonical.hashStoredJson(text))

    /** peer_sync._raw_hash: a version's raw record, without what Units.VOLATILE_RAW names for its provider (UG's
     * ratings and votes); a provider that isn't text takes nothing out. */
    private fun raw(provider: JsonElement, text: String?): JsonElement {
        val name = (provider as? JsonPrimitive)?.takeIf { it.isString }?.content
        return JsonPrimitive(Canonical.hashStoredJson(text, name?.let { Units.VOLATILE_RAW[it] } ?: emptySet()))
    }

    private fun obj(vararg members: Pair<String, JsonElement>): JsonObject = JsonObject(linkedMapOf(*members))
}
