package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

// search.py's dataclasses, field for field. Each toJson() is what helpers.corpus.plain writes for it: Python's
// snake_case names in declaration order, a song as its key, a tuple as an array, so a corpus record compares whole.

/** A song of yours a query matches. */
data class LibraryHit(val song: SongRow, val score: Double, val via: String = "both") {
    fun toJson(): JsonObject = obj("song" to song.key, "score" to score, "via" to via)
}

/** A song of UG's index a query matches: its tabs counted by kind. */
data class IndexHit(
    val artistKey: String, val songKey: String, val counts: LinkedHashMap<String, Int>, val score: Double,
    val url: String, val labels: List<String> = emptyList(), val artist: String = "", val title: String = "",
    val via: String = "both", val rating: Double? = null, val votes: Int = 0, val page: String = "",
) {
    /** Its tabs of every kind. */
    val tabs: Int get() = counts.values.sum()

    /** match.is_catch_all: a misc-… key (but misc-mashups) files many artists' songs. */
    val catchAll: Boolean get() = artistKey.startsWith(SearchLimits.CATCH_ALL_PREFIX) && artistKey != "misc-mashups"

    fun toJson(): JsonObject = obj(
        "artist_key" to artistKey, "song_key" to songKey, "counts" to counts, "score" to score, "url" to url,
        "labels" to labels, "artist" to artist, "title" to title, "via" to via, "rating" to rating, "votes" to votes,
        "page" to page,
    )
}

/** An artist of UG's index a query names. */
data class ArtistHit(
    val artistKey: String, val artist: String, val score: Double, val songs: Int, val tabs: Int,
    val top: List<IndexHit> = emptyList(), val page: String = "", val part: Boolean = false,
) {
    /** Their most tabbed song's tabs. */
    val topTabs: Int get() = top.firstOrNull()?.tabs ?: 0

    fun toJson(): JsonObject = obj(
        "artist_key" to artistKey, "artist" to artist, "score" to score, "songs" to songs, "tabs" to tabs,
        "top" to top, "page" to page, "part" to part,
    )
}

/** What find_index found. */
data class IndexFound(
    val artists: List<ArtistHit> = emptyList(), val songs: List<IndexHit> = emptyList(), val lead: String? = null,
    val best: IndexHit? = null,
) {
    fun toJson(): JsonObject = obj("artists" to artists, "songs" to songs, "lead" to lead, "best" to best)
}

/** Your songs and the index's, together. [best] is a [LibraryHit] or an [IndexHit]. */
data class Found(
    val library: List<LibraryHit>, val artists: List<ArtistHit>, val songs: List<IndexHit>, val lead: String?,
    val best: Any?,
) {
    fun toJson(): JsonObject =
        obj("library" to library, "artists" to artists, "songs" to songs, "lead" to lead, "best" to best)
}

/** One harmonica tab of a song on harptabs.com. */
data class HarpTabHit(
    val title: String, val url: String, val views: Int = 0, val rating: Double? = null, val key: String? = null,
    val difficulty: String? = null,
) {
    fun toJson(): JsonObject = obj(
        "title" to title, "url" to url, "views" to views, "rating" to rating, "key" to key,
        "difficulty" to difficulty,
    )
}

/** One tab of a game's track on gametabs.net. */
data class GameTabHit(
    val title: String, val url: String, val views: Int = 0, val rating: Double? = null,
    val instruments: List<String> = emptyList(), val composers: List<String> = emptyList(),
) {
    fun toJson(): JsonObject = obj(
        "title" to title, "url" to url, "views" to views, "rating" to rating, "instruments" to instruments,
        "composers" to composers,
    )
}

/** A song of another site's index (gtptabs.com, MuseScore, LaCuerda, harptabs.com, gametabs.net). [tabs] holds
 * [HarpTabHit]s or [GameTabHit]s. */
data class SiteHit(
    val source: String, val title: String, val url: String, val score: Double, val artist: String = "",
    val artistKey: String = "", val titleKey: String = "", val uploads: Int = 1, val via: String = "title",
    val sheet: String? = null, val tabs: List<Any> = emptyList(), val page: String = "",
) {
    fun toJson(): JsonObject = obj(
        "source" to source, "title" to title, "url" to url, "score" to score, "artist" to artist,
        "artist_key" to artistKey, "title_key" to titleKey, "uploads" to uploads, "via" to via, "sheet" to sheet,
        "tabs" to tabs, "page" to page,
    )
}

/** An artist of another site's index. */
data class SiteArtist(
    val source: String, val artist: String, val slug: String, val url: String, val score: Double,
    val songs: Int = 0, val known: Int = 0, val via: String = "artist", val top: List<SiteHit> = emptyList(),
    val part: Boolean = false, val read: Boolean = false,
) {
    fun toJson(): JsonObject = obj(
        "source" to source, "artist" to artist, "slug" to slug, "url" to url, "score" to score, "songs" to songs,
        "known" to known, "via" to via, "top" to top, "part" to part, "read" to read,
    )
}

/** A "Did you mean": an artist spelled close to the query, or a title ([hits]: [IndexHit]s or [SiteHit]s). */
data class Suggestion(
    val source: String, val artist: String, val key: String, val songs: Int, val score: Double,
    val title: String = "", val hits: List<Any> = emptyList(),
) {
    fun toJson(): JsonObject = obj(
        "source" to source, "artist" to artist, "key" to key, "songs" to songs, "score" to score, "title" to title,
        "hits" to hits,
    )
}

/** A removed song a query matches: never a library hit, never lead or best. */
data class RemovedHit(
    val artist: String, val title: String, val key: String, val removedAt: String, val score: Double,
    val via: String = "both",
) {
    fun toJson(): JsonObject = obj(
        "artist" to artist, "title" to title, "key" to key, "removed_at" to removedAt, "score" to score, "via" to via,
    )
}

/** search.py's constants (its lines 169–196), by the same names. */
object SearchLimits {
    const val MIN_SCORE = 70
    const val STRONG = 90
    const val PARTIAL_SCALE = 0.9
    val TYPE_ORDER: List<String> = listOf("chords", "tabs", "ukulele")
    const val MAX_PATTERNS = 2
    const val SHOWN_CANDIDATES = 3
    val READINGS: List<String> = listOf("title", "both", "artist")
    const val TOP_SONGS = 3
    const val ARTIST_ROWS = 3
    const val SONG_ROWS = 8
    const val SITE_ROWS = 5
    const val SITE_ROWS_READ = 2000
    const val PART = 90.0
    const val WORD_LETTERS = 3
    const val WORD_ARTISTS = 300
    const val WELL_KNOWN = 50
    const val MOST_SONGS = 5
    const val OUTWEIGHS = 4
    const val SUGGESTED = 3
    const val CLOSE = 80
    const val CLOSE_LETTERS = 4
    const val CLOSE_WORDS = 20
    const val CLOSE_ARTISTS = 1000
    const val CLOSE_MARGIN = 8
    const val SUGGEST_SHARE = 10
    const val CLOSE_TABS = 5000
    const val CLOSE_PATTERNS = 2
    const val TAB_SONGS = 5

    /** match.CATCH_ALL_PREFIX. */
    const val CATCH_ALL_PREFIX = "misc-"
}

private fun obj(vararg members: Pair<String, Any?>): JsonObject = JsonObject(linkedMapOf(*members).mapValues { json(it.value) })

private fun json(value: Any?): JsonElement = when (value) {
    null -> JsonNull
    is JsonElement -> value
    is String -> JsonPrimitive(value)
    is Boolean -> JsonPrimitive(value)
    is Number -> JsonPrimitive(value)
    is List<*> -> JsonArray(value.map { json(it) })
    is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k as String to json(v) })
    is LibraryHit -> value.toJson()
    is IndexHit -> value.toJson()
    is ArtistHit -> value.toJson()
    is IndexFound -> value.toJson()
    is Found -> value.toJson()
    is HarpTabHit -> value.toJson()
    is GameTabHit -> value.toJson()
    is SiteHit -> value.toJson()
    is SiteArtist -> value.toJson()
    is Suggestion -> value.toJson()
    is RemovedHit -> value.toJson()
    else -> throw IllegalArgumentException("no JSON form for ${value::class.simpleName}")
}
