package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.http.AzLyricsParseError
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyHtml
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Duration
import java.time.Instant

/** azlyrics_fetch.AzLyricsStats: `tried`, `errors`, `budgetExhausted` and `failures` as every pass counts them;
 * [found], songs that had no lyrics and now have AZLyrics'; [missing], songs it has nothing for. */
class AzLyricsStats(var found: Int = 0, var missing: Int = 0) : PassStats()

/**
 * azlyrics.py and azlyrics_fetch.py on the phone: AZLyrics' pages, plain lyrics for a song LRCLIB and Megalobiz have
 * none of, and its pass for a lookup's song.
 *
 * - `/<letter>/<slug>.html` is an artist's page ([artistUrl], [parseArtist]: its `<h1>` and each `listalbum-item`
 *   link to `/lyrics/<artist>/<song>.html`), `/lyrics/<artist>/<song>.html` a song's ([parseLyrics]: the `<div>` after
 *   the site's notice, a line a `<br>`), each read with Python's regexes over `Response.text`, its tags stripped and
 *   its entities unescaped (PyHtml.unescape), each line `str.strip()`ped. A page that doesn't read is an
 *   [AzLyricsParseError]: an error, never a miss. Its block page is a 200, which PoliteClient knows by its words.
 * - A song takes two requests, its artist's page then the lyrics page of its line ([pickSong]), or `[azlyrics]`'s
 *   page alone (Overrides.azlyrics), whoever it credits.
 * - The songs asked ([songsToAsk]): those with no lyrics, missing or failed on by LRCLIB (kv `lyrics:failed:`), none
 *   it answered a miss about in the last 30 days (kv `azlyrics:checked:`, [CHECKED]); a song `[azlyrics]` names a
 *   page for whatever its last miss or LRCLIB's failure.
 *
 * tests/conformance/vectors/sites/azlyrics.jsonl and lookup/azlyrics.jsonl hold Python's answers.
 */
object AzLyrics {
    const val PROVIDER = "azlyrics"

    /** Where every page is, which caracole links back to. */
    const val SITE = "https://www.azlyrics.com/"

    /** + song id: when AZLyrics last answered a miss about the song. */
    const val CHECKED = "azlyrics:checked:"
    val RECHECK_AFTER: Duration = Duration.ofDays(30)
    private val ACCEPT = setOf(200, 404) // no such page: a miss

    private val HEADING by lazy { PyRegex.compile("(?s)<h1>\\s*<strong>(.+?) Lyrics</strong>\\s*</h1>") }
    private val ROW by lazy {
        PyRegex.compile("(?s)<div class=\"listalbum-item\"><a href=\"(?:https://www\\.azlyrics\\.com)?" +
                            "(/lyrics/[a-z0-9-]+/[a-z0-9-]+\\.html)\"[^>]*>(.*?)</a>")
    }
    private val LYRICS by lazy { PyRegex.compile("(?s)<!-- Usage of azlyrics\\.com content.*?-->(.*?)</div>") }
    private val TAG by lazy { PyRegex.compile("<[^>]+>") }
    private val THE by lazy { PyRegex.compile("^the\\s+") }
    private val NOT_SLUG by lazy { PyRegex.compile("[^a-z0-9]") }
    private val BR by lazy { PyRegex.compile("<br\\s*/?>") }
    private val LINE_ENDS by lazy { PyRegex.compile("[\\r\\n]+") }

    /** azlyrics.SongLink: a song an artist's page links to, its title as written and its lyrics page. */
    data class SongLink(val title: String, val url: String)

    /** azlyrics.ArtistPage: an artist's page, their name as the site writes it and the songs it links to. */
    data class ArtistPage(val name: String, val songs: List<SongLink>)

    /** azlyrics.artist_url: the address of an artist's page (the name folded, lower-cased, without a leading "The",
     * in letters and digits, under its first letter or `19/` for a digit), or null for a name with none to write. */
    fun artistUrl(name: String): String? {
        val slug = PyRe.sub(NOT_SLUG, PyRe.sub(THE, PyUnicode.lower(Normalize.fold(name))) { "" }) { "" }
        if (slug.isEmpty()) return null
        return "$SITE${if (slug[0] in 'a'..'z') slug[0].toString() else "19"}/$slug.html"
    }

    /** azlyrics._text: a fragment's tags gone, its entities unescaped, stripped. */
    private fun text(fragment: String): String = Py.strip(PyHtml.unescape(PyRe.sub(TAG, fragment) { "" }))

    private fun error(resp: Response, words: String) = AzLyricsParseError(PROVIDER, resp.url, resp.status, words)

    /** azlyrics.parse_artist: an artist's name and the songs their page links to, the page's script read for none. */
    fun parseArtist(resp: Response): ArtistPage {
        val page = resp.text
        val heading = PyRe.search(HEADING, page)
        if (heading == null || "id=\"listAlbum\"" !in page) throw error(resp, "not an artist's page")
        val songs = PyRe.finditer(ROW, page).map { m ->
            SongLink(text(m.groups[2]?.value ?: ""), SITE + (m.groups[1]?.value ?: "").removePrefix("/"))
        }.toList()
        return ArtistPage(text(heading.groups[1]?.value ?: ""), songs)
    }

    /** azlyrics.parse_lyrics: a lyrics page's text, a line a `<br>`, its tags (an italic section's name) gone and their
     * words kept. */
    fun parseLyrics(resp: Response): String {
        val found = PyRe.search(LYRICS, resp.text) ?: throw error(resp, "not a lyrics page")
        val joined = PyRe.sub(BR, PyRe.sub(LINE_ENDS, found.groups[1]?.value ?: "") { "" }) { "\n" }
        val lines = PyHtml.unescape(PyRe.sub(TAG, joined) { "" }).split("\n")
        val text = Py.strip(lines.joinToString("\n") { Py.strip(it) })
        if (text.isEmpty()) throw error(resp, "a lyrics page with no lyrics")
        return text
    }

    /** azlyrics.pick_song: the song on an artist's page, or null: their name and its title fit ([Lrclib.fits]), no
     * other kind of version than the song, the title closest to the song's as written first (its own line before its
     * "(Live)" one), the first of equals. */
    fun pickSong(page: ArtistPage, artist: String, title: String): SongLink? = page.songs
        .filter { !Lrclib.anotherVersion(title, it.title) && Lrclib.fits(artist, title, null, page.name, it.title, null) != null }
        .maxByOrNull { Fuzz.ratio(Normalize.slugKey(title), Normalize.slugKey(it.title)) }

    // --- the pass ---------------------------------------------------------------------------------------------------

    /** azlyrics_fetch._wants: whether the sites before it left the song without lyrics: missing, or failed on and
     * pending. */
    private fun wants(db: Db, song: SongRow): Boolean = when (song.lyricsStatus) {
        "pending" -> db.kvGet("${Lrclib.FAILED}${song.id}") != null
        else -> song.lyricsStatus == "missing"
    }

    /** azlyrics_fetch.songs_to_ask: the songs with no lyrics that AZLyrics hasn't answered a miss about since
     * [recheckAfter], or that [picks] (Overrides.azlyrics) names a page for, newest first (of [only]'s ids). */
    fun songsToAsk(db: Db, now: Instant, picks: Map<String, String> = emptyMap(), recheckAfter: Duration = RECHECK_AFTER,
                   only: Set<Long>? = null): List<SongRow> {
        val asked = ArrayList<SongRow>()
        for (song in Lrclib.songs(db, now)) {
            if (song.status == "ignored" || (only != null && song.id !in only)) continue
            if (OverrideUrls.overrideKey(song.display) in picks) {
                if (song.lyricsStatus == "pending" || song.lyricsStatus == "missing") asked += song
                continue
            }
            val checked = db.kvGet("$CHECKED${song.id}")
            if (wants(db, song) && (checked == null || PyValues.before(checked, now, recheckAfter))) asked += song
        }
        return asked
    }

    /** azlyrics_fetch.fetch_azlyrics: a song's plain lyrics, or null when AZLyrics has none: its artist's page, then
     * the song's lyrics page, or [page] alone when given. Errors propagate (a page that won't read asked for once more
     * first, past the cache); [cache] goes to each first request. */
    fun fetchAzLyrics(client: Client, artist: String, title: String, page: String? = null, cache: Boolean = true): Lyrics? {
        var lyricsPage = page
        if (lyricsPage == null) {
            val url = artistUrl(artist) ?: return null
            val resp = client.get(url, accept = ACCEPT, cache = cache)
            if (resp.status == 404) return null
            val listed = HttpRules.readOnceMore(client, resp, url, { it is AzLyricsParseError }, accept = ACCEPT) {
                parseArtist(it)
            }
            lyricsPage = (pickSong(listed, artist, title) ?: return null).url
        }
        val resp = client.get(lyricsPage, accept = ACCEPT, cache = cache)
        if (resp.status == 404) return null
        val plain = HttpRules.readOnceMore(client, resp, lyricsPage, { it is AzLyricsParseError }, accept = ACCEPT) {
            parseLyrics(it)
        }
        return Lyrics(plain = plain, synced = null, instrumental = false, duration = null, lrclibId = null,
                      raw = JsonObject(mapOf("url" to JsonPrimitive(lyricsPage))), provider = PROVIDER, url = lyricsPage)
    }

    /**
     * azlyrics_fetch.azlyrics_lyrics for [only]'s songs (a lookup's one, [songsToAsk]), `[azlyrics]`'s pages from
     * [overrides]. Found lyrics written as LRCLIB's plain ones are and stored with their page (the link back,
     * `Lyrics.url`); a miss: [CHECKED] now; an error: never a miss, a song LRCLIB missed back to pending.
     */
    fun azlyricsLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides, only: Set<Long>,
                       recheckAfter: Duration = RECHECK_AFTER): AzLyricsStats {
        val stats = AzLyricsStats()
        val stamp = Stamps.of(now)
        val picks = overrides.azlyrics
        val backToPending = { song: SongRow, _: Exception ->
            if (song.lyricsStatus == "missing") { // a song is missing only once every site asked answered a miss
                Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to "pending", "lyrics_at" to null), stamp)
            }
        }
        val songs = songsToAsk(db, now, picks, recheckAfter, only).asSequence()
        val asked = Passes.eachSong(songs, stats, "AZLyrics", onError = backToPending) { song ->
            val page = picks[OverrideUrls.overrideKey(song.display)]
            val cache = page != null || db.kvGet("$CHECKED${song.id}") == null // a miss asked again goes past the cache
            fetchAzLyrics(client, song.artists[0], song.title, page, cache)
        }
        for ((song, lyrics) in asked) {
            if (lyrics == null) {
                db.kvSet("$CHECKED${song.id}", stamp)
                stats.missing++
                continue
            }
            Lrclib.writeLyrics(lib.folderOf(song), lyrics)
            Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to "found", "lyrics_json" to lyrics.toJson(),
                                                         "lyrics_at" to stamp), stamp)
            db.kvDelete("$CHECKED${song.id}")
            db.kvDelete("${Lrclib.FAILED}${song.id}")
            stats.found++
        }
        return stats
    }
}
