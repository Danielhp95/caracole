package io.github.danielhp95.caracole.core.lacuerda

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * lacuerda_index.LaCuerdaHit: an artist or a song of LaCuerda's that the query matches, from the local index.
 *
 * [artist] is the name LaCuerda writes, [artistSlug] their page's slug; [url] is the artist's page, or the song's own
 * (which lists its versions). [score] is 0–100, and [via] the reading of the query that gave it ("title", "artist" or
 * "both"). An artist's hit counts its [songs] (as the listing does) and holds its [top] songs the index has: the most
 * popular with a Letra y Acordes version. A song's hit has its [title], its lcd letters ([versions], one per version)
 * and its best Letra y Acordes version ([acordes], 0 for none), whose page is [sheetUrl]. [part] is true for an artist
 * whose name holds the query's words as words of its own among others, never letters inside a word.
 */
data class LaCuerdaHit(
    val artist: String, val artistSlug: String, val artistKey: String, val url: String, val score: Double,
    val via: String = "artist", val title: String = "", val songSlug: String = "", val titleKey: String = "",
    val songs: Int = 0, val versions: String = "", val acordes: Int = 0, val top: List<LaCuerdaHit> = emptyList(),
    val source: String = "lacuerda", val part: Boolean = false,
) {
    /** "song" or "artist". */
    val kind: String get() = if (songSlug.isNotEmpty()) "song" else "artist"

    /** The page of the song's best Letra y Acordes version; null for an artist or a song with none. */
    val sheetUrl: String? get() =
        if (songSlug.isNotEmpty() && acordes != 0) LaCuerdaUrls.versionUrl(artistSlug, songSlug, acordes) else null

    /** As helpers.corpus.plain writes it: the dataclass's fields in their order, its properties left out. */
    fun toJson(): JsonObject = JsonObject(linkedMapOf(
        "artist" to s(artist), "artist_slug" to s(artistSlug), "artist_key" to s(artistKey), "url" to s(url),
        "score" to JsonPrimitive(score), "via" to s(via), "title" to s(title), "song_slug" to s(songSlug),
        "title_key" to s(titleKey), "songs" to JsonPrimitive(songs), "versions" to s(versions),
        "acordes" to JsonPrimitive(acordes), "top" to JsonArray(top.map { it.toJson() }), "source" to s(source),
        "part" to JsonPrimitive(part),
    ))
}

/** lacuerda_index.LaCuerdaFound: what [LaCuerda.find] answers, the artists best first, then the songs. */
data class LaCuerdaFound(val artists: List<LaCuerdaHit> = emptyList(), val songs: List<LaCuerdaHit> = emptyList()) {
    fun toJson(): JsonObject = JsonObject(linkedMapOf<String, JsonElement>(
        "artists" to JsonArray(artists.map { it.toJson() }), "songs" to JsonArray(songs.map { it.toJson() }),
    ))
}

private fun s(text: String?): JsonElement = if (text == null) JsonNull else JsonPrimitive(text)
