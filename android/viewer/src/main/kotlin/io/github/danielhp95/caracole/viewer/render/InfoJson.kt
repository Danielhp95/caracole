package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import io.github.danielhp95.caracole.core.library.Versions as Rows

/**
 * library.write_info on the phone: a song's info.json, the song, where it came from, and what was kept or picked,
 * byte for byte as the computer writes it of the same library (`json.dumps(info, ensure_ascii=False, indent=2)` and a
 * line end). Its `render` is the PDF's (kv `render:<song id>`), which the phone never makes nor reads: null on the
 * phone, whatever record a library it was made of holds (helpers/phone_render.py writes it so).
 */
object InfoJson {
    /** The file's bytes for the song as the library holds it now. */
    fun bytes(db: Db, libraryDir: File, song: SongRow): ByteArray {
        val musical = MusicKeys.songKey(db, libraryDir, song.id)
        val files = Kept.keptFiles(db, song.id).map { f ->
            val v = Rows.get(db, f.versionId) ?: throw NoSuchElementException("no version with id ${f.versionId}")
            obj("name" to JsonPrimitive(f.name), "rank" to JsonPrimitive(f.keptRank), "sha256" to JsonPrimitive(f.sha256),
                "provider" to JsonPrimitive(v.provider), "tab_id" to JsonPrimitive(v.tabId),
                "kind" to JsonPrimitive(v.kind), "url" to JsonPrimitive(v.url), "rating" to PyJson.float(v.rating),
                "votes" to JsonPrimitive(v.votes), "version" to JsonPrimitive(v.version), "label" to text(v.label),
                "coverage" to (v.coverage?.let(PyJson::float) ?: JsonNull))
        }
        val picked = Rows.songVersions(db, song.id).filter { it.pickRank != null }
            .sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(a.kind, b.kind).takeIf { it != 0 } ?: a.pickRank!!.compareTo(b.pickRank!!) }
            .map { v ->
                obj("kind" to JsonPrimitive(v.kind), "rank" to JsonPrimitive(v.pickRank), "url" to JsonPrimitive(v.url),
                    "rating" to PyJson.float(v.rating), "votes" to JsonPrimitive(v.votes),
                    "version" to JsonPrimitive(v.version), "label" to text(v.label))
            }
        val info = obj(
            "artist" to JsonPrimitive(song.artist),
            "title" to JsonPrimitive(song.title),
            "artists" to JsonArray(song.artists.map(::JsonPrimitive)),
            "album" to text(song.album),
            "duration_ms" to (song.durationMs?.let(::JsonPrimitive) ?: JsonNull),
            "isrc" to text(song.isrc),
            "identity_key" to JsonPrimitive(song.key),
            "key" to text(musical?.key),
            "key_source" to text(musical?.source),
            "status" to JsonPrimitive(song.status),
            "sources" to PyJson.loads(song.sourceIds),
            "lyrics" to JsonPrimitive(song.lyricsStatus),
            "lyrics_from" to (lyricsFrom(song) ?: JsonNull),
            "match" to obj("decision" to text(song.matchDecision), "step" to text(song.matchStep),
                           "score" to (song.matchScore?.let(PyJson::float) ?: JsonNull),
                           "artist_key" to text(song.matchArtistKey), "song_key" to text(song.matchSongKey)),
            "files" to JsonArray(files),
            "picks" to JsonArray(picked),
            "render" to JsonNull,
        )
        return (PyJson.dumps(info, indent = 2) + "\n").toByteArray(Charsets.UTF_8)
    }

    /** write_info: info.json in the song's folder, left alone when it holds these bytes already (each rewrite is one
     * more sync on every device); the file. */
    fun write(db: Db, libraryDir: File, song: SongRow): File {
        val data = bytes(db, libraryDir, song)
        val file = File(LibraryStore(libraryDir).folderOf(song), "info.json")
        if (!Kept.holds(file.toPath(), Canonical.sha256Hex(data), data.size.toLong())) Kept.writeAtomic(file.toPath(), data)
        return file
    }

    /** library.lyrics_from: where a song's lyrics link back to, `{"source", "href"}`, for a site of
     * [RenderNames.LYRICS_PAGES] and a page on it alone; null for any other, or lyrics that can't be read. */
    fun lyricsFrom(song: SongRow): JsonObject? {
        val stored = song.lyricsJson?.let {
            try {
                PyJson.loads(it)
            } catch (_: IllegalArgumentException) {
                return null
            }
        }
        if (stored !is JsonObject || song.lyricsStatus != "found") return null
        val provider = (stored["provider"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val url = (stored["url"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val site = provider?.let { RenderNames.LYRICS_PAGES[it] }
        if (site == null || url == null || !url.startsWith(site)) return null
        return obj("source" to JsonPrimitive(provider), "href" to JsonPrimitive(url))
    }

    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull

    private fun obj(vararg members: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*members))
}
