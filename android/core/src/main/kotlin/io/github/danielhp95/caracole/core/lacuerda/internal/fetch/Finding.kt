package io.github.danielhp95.caracole.core.lacuerda.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSong
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.SongRow
import java.time.Instant

/** lacuerda_fetch._Sheet: LaCuerda's best "acordes" version of a song, as fetched: the artist slug that answered,
 * the song, its version's number and page, and its sheet in UG markup (chords in `[ch]…[/ch]`). */
internal data class Sheet(val artist: String, val song: LaCuerdaSong, val version: Int, val url: String,
                          val markup: String) {
    val tabId: String get() = "$artist/${song.slug}-$version"
}

/** lacuerda_fetch.py's asking: `_find_sheet`, `_artist_songs`, `_artist_page`, `_picked_sheet` and the two readers of
 * a page, each page through [HttpRules.readOnceMore], [fetched] the URLs this pass asked LaCuerda for. */
internal object Finding {
    /** _ACCEPT: a 404 is an answer, no such artist or no such version. */
    private val ACCEPT: Set<Int> = setOf(200, 404)

    private val unreadable: (Throwable) -> Boolean = { it is LaCuerdaParseError }

    /** _find_sheet: the best "acordes" version LaCuerda has of the song, or null when it has none. */
    fun findSheet(db: Db, client: Client, artist: String, title: String, now: Instant, stamp: String,
                  fetched: MutableSet<String>): Sheet? {
        val (slug, songs) = artistSongs(db, client, artist, now, stamp, fetched) ?: return null
        val lcSong = LaCuerdaPages.matchTitle(songs, title) ?: return null
        val n = LaCuerdaPages.bestAcordesVersion(lcSong) ?: return null
        val url = LaCuerdaPages.versionUrl(slug, lcSong.slug, n)
        val markup = versionPage(client, url, fetched) ?: return null
        return Sheet(slug, lcSong, n, url, markup)
    }

    /**
     * _artist_songs: the first artist page LaCuerda has among the artist's slugs, with its songs (stored in the
     * index). The slugs are [first]'s, then those LaCuerda's listings give the name, then those built from it, each
     * once in that order; a 404, or the "aqui llega:" body, moves on to the next. Null when no slug has a page.
     */
    fun artistSongs(db: Db, client: Client, artist: String, now: Instant, stamp: String, fetched: MutableSet<String>,
                    first: List<String> = emptyList()): Pair<String, List<LaCuerdaSong>>? {
        val slugs = LinkedHashSet<String>().apply {
            addAll(first)
            addAll(LaCuerda.artistSlugs(db, artist))
            addAll(LaCuerdaPages.artistSlugCandidates(artist))
        }
        for (slug in slugs) {
            val songs = artistPage(db, client, slug, now, stamp, fetched) ?: continue
            return slug to songs
        }
        return null
    }

    /** _artist_page: the songs of [slug]'s artist page, stored in the index at [stamp] (and noted for the next push);
     * null when LaCuerda has no artist by it. A copy older than 30 days, served once the budget is spent, is no
     * answer for today: [BudgetExhausted], as the next request would have been. */
    fun artistPage(db: Db, client: Client, slug: String, now: Instant, stamp: String,
                   fetched: MutableSet<String>): List<LaCuerdaSong>? {
        val url = LaCuerdaPages.artistUrl(slug)
        val resp = client.get(url, accept = ACCEPT, maxAge = LaCuerdaSheets.ARTIST_PAGE_MAX_AGE)
        if (HttpRules.stale(resp, now, LaCuerdaSheets.ARTIST_PAGE_MAX_AGE)) throw BudgetExhausted(LaCuerdaSheets.PROVIDER)
        val (songs, html) = HttpRules.readOnceMore(client, resp, url, unreadable, fetched, ACCEPT) { artistPageSongs(it) }
            ?: return null
        LaCuerda.storeSongs(db, slug, LaCuerdaPages.parseArtistName(html), songs, LaCuerdaPages.parsePopularity(html),
                            stamp)
        return songs
    }

    /**
     * _picked_sheet: the sheet of the LaCuerda song or version you picked, or null when LaCuerda has no such page, or
     * the song no "acordes" version. A version costs its own page; a song, its best "acordes" version's, which the
     * index names when it holds the artist's page (its row's `acordes`, 0 for none), else the artist's page does.
     */
    fun pickedSheet(db: Db, client: Client, pick: LaCuerdaPick, song: SongRow, now: Instant, stamp: String,
                    fetched: MutableSet<String>): Sheet? {
        val row = db.one("SELECT title, versions, acordes FROM lacuerda_index WHERE path = ?",
                         "${pick.artist}/${pick.song}") { Triple(it.text(0)!!, it.text(1)!!, it.long(2)!!) }
        var lcSong: LaCuerdaSong? = LaCuerdaSong(pick.song, row?.first ?: song.title, row?.second ?: "", emptyList())
        var n: Int? = pick.version
        if (n == null && row != null) {
            n = row.third.toInt().takeIf { it != 0 }  // `row[2] or None`
        } else if (n == null) {
            val songs = artistPage(db, client, pick.artist, now, stamp, fetched)
            lcSong = songs.orEmpty().firstOrNull { it.slug == pick.song }
            n = lcSong?.let { LaCuerdaPages.bestAcordesVersion(it) }
        }
        if (lcSong == null || n == null) return null
        val url = LaCuerdaPages.versionUrl(pick.artist, pick.song, n)
        val markup = versionPage(client, url, fetched) ?: return null
        return Sheet(pick.artist, lcSong, n, url, markup)
    }

    /** A version's page asked for (cached forever) and its sheet read: null when the page is gone. */
    private fun versionPage(client: Client, url: String, fetched: MutableSet<String>): String? =
        HttpRules.readOnceMore(client, client.get(url, accept = ACCEPT), url, unreadable, fetched, ACCEPT) {
            versionSheet(it)
        }

    /** _artist_page_songs: the songs on an artist page, and the page; null when LaCuerda has no artist by that slug. */
    private fun artistPageSongs(resp: Response): Pair<List<LaCuerdaSong>, String>? {
        val text = resp.text
        if (resp.status == 404 || LaCuerdaPages.isMissingArtistPage(text)) return null
        return LaCuerdaPages.parseArtistPage(text, url = resp.url) to text
    }

    /** _version_sheet: the sheet on a version page; null when the page is gone (listed by a cached artist page). */
    private fun versionSheet(resp: Response): String? =
        if (resp.status == 404) null else LaCuerdaPages.parseVersionPage(resp.text, url = resp.url)
}
