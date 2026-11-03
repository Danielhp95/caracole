package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral
import java.math.BigInteger

/** search_routes.ARTIST_PAGE: an artist's songs of UG's index /api/artist gives at a time. */
internal const val ARTIST_PAGE = 50

/** search_routes.LACUERDA_SONGS: a LaCuerda artist's songs /api/artist gives, all the index holds. */
internal const val LACUERDA_SONGS = 1000

/** An answer of /api/artist: its status and its JSON. */
internal class Answered(val status: Int, val json: JsonObject)

/**
 * /api/artist's three forms (search_routes.api_artist, api_lacuerda_artist, api_harptabs_artist), each over [db], with
 * your songs by the artist as your songs' rows are: an artist of UG's index by their key, [ARTIST_PAGE] songs from an
 * offset, most tabbed first; a LaCuerda artist by their page's slug or by their name, the songs its index holds of
 * theirs and whether caracole read their page; a harptabs.com artist by their page's path.
 */
internal class Artists(private val db: Db, private val enabled: Set<String>, private val cards: SongCards,
                       private val forms: SongForms) {
    /** search_routes._artist_songs, for a [key] and an [offset] api_artist has checked. */
    fun ug(key: String, offset: String): Answered {
        val named = Search.indexArtist(db, key)
            ?: return Answered(404, obj("error" to "The offline Ultimate Guitar index has no such artist."))
        val from = BigInteger(offset)
        val (hits, total) = Search.artistSongs(db, key, limit = ARTIST_PAGE, offset = from.min(INT_MAX).toInt())
        val songs = Songs.list(db)
        val rows = Rows(db, songs, cards, forms, enabled)
        val theirs = Search.libraryByArtist(songs, named.artist, key).map { LibraryHit(it, 100.0, "artist") }
        val (library, index) = rows.rows(theirs, hits.map { hitJson(db, it) })
        return Answered(200, obj(
            "artist_key" to key, "artist" to named.artist, "songs" to index, "total" to total,
            "offset" to integer(from), "tabs" to named.tabs, "library" to library,
        ))
    }

    /** search_routes.api_lacuerda_artist: by the [slug] of their page, else by their [name]. */
    fun lacuerda(slug: String, name: String): Answered {
        val named = (if (slug.isNotEmpty()) LaCuerda.lacuerdaArtist(db, slug) else LaCuerda.lacuerdaArtistNamed(db, name))
            ?: return Answered(404, obj("error" to "LaCuerda's index has no such artist."))
        val songs = Songs.list(db)
        val rows = Rows(db, songs, cards, forms, enabled)
        val theirs = Search.libraryByArtist(songs, named.artist).map { LibraryHit(it, 100.0, "artist") }
        val (library, _) = rows.rows(theirs, emptyList())
        val hits = rows.lacuerda(LaCuerda.lacuerdaSongs(db, named.slug).take(LACUERDA_SONGS))
        val gtptabs = rows.gtptabsSongs(named.artist)
        return Answered(200, obj(
            "source" to "lacuerda", "slug" to named.slug, "artist" to named.artist, "url" to named.url,
            "group_key" to groupKey(named.artist), "listed" to named.songs, "total" to named.known,
            "read" to (named.known > 0), "gtptabs" to gtptabs, "songs" to hits, "library" to library,
        ))
    }

    /** search_routes.api_harptabs_artist: by their page's [path] (`artist/<number>/<slug>`). */
    fun harptabs(path: String): Answered {
        val named = (if (isArtistPath(path)) SiteSearch.harptabsArtist(db, path) else null)
            ?: return Answered(404, obj("error" to "harptabs.com's index has no such artist."))
        val read = db.one("SELECT 1 FROM harptabs_artists WHERE path = ?", path) { true } ?: false
        val songs = Songs.list(db)
        val rows = Rows(db, songs, cards, forms, enabled)
        val theirs = Search.libraryByArtist(songs, named.artist).map { LibraryHit(it, 100.0, "artist") }
        val (library, _) = rows.rows(theirs, emptyList())
        val hits = rows.harptabs(SiteSearch.harptabsSongs(db, path))
        return Answered(200, obj(
            "source" to "harptabs", "path" to path, "artist" to named.artist, "url" to named.url,
            "group_key" to groupKey(named.artist), "listed" to named.songs, "total" to named.known, "read" to read,
            "songs" to hits, "library" to library,
        ))
    }

    companion object {
        private val INT_MAX = BigInteger.valueOf(Int.MAX_VALUE.toLong())

        /** A Python int as JSON, however long: `int(offset)` echoed. */
        @OptIn(ExperimentalSerializationApi::class)
        private fun integer(n: BigInteger): JsonElement =
            if (n.bitLength() < 64) JsonPrimitive(n.toLong()) else JsonUnquotedLiteral(n.toString())

        /** search_routes._HARP_ARTIST, `artist/\d{1,9}/[a-z0-9-]{1,200}` in full: \d as Python's re reads it in a str
         * pattern, any decimal digit (str.isdecimal). */
        fun isArtistPath(path: String): Boolean {
            if (!path.startsWith("artist/")) return false
            val rest = path.substring("artist/".length)
            val slash = rest.indexOf('/')
            if (slash < 0) return false
            val number = rest.substring(0, slash)
            val slug = rest.substring(slash + 1)
            val digits = number.codePoints().toArray()
            return digits.size in 1..9 && digits.all { it in '0'.code..'9'.code || PyUnicode.isDecimal(it) } &&
                slug.length in 1..200 && slug.all { it in 'a'..'z' || it in '0'..'9' || it == '-' }
        }
    }
}
