package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderUnavailable
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sites.internal.harptabs.Artists
import io.github.danielhp95.caracole.core.sites.internal.harptabs.HarpPass
import java.time.Duration
import java.time.Instant

/** harptabs_fetch.HarpTabsStats: what one [HarpTabsFetch.harptabsTabs] pass did. [sitemaps] counts the sitemap reads
 * stored (none on the phone, which reads no sitemap); [tried] the songs looked up, errors included; [errors] the
 * songs' (and a sitemap's); [failures] the songs an error left, as every pass names them. */
class HarpTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats() {
    /** The errors no song's failure stands for: the sitemap's. */
    val sitemapErrors: Int get() = errors - failures.count { it.second !is ProviderUnavailable }
}

/** harptabs.ListedTab: a tab an artist page lists: the site's id, its page's path (`tab/25/piano-man`), its title as
 * the card writes it, and its chips (null, or 0 for the views, when the card shows none). */
data class HarpListedTab(val tabId: Long, val path: String, val title: String, val key: String? = null,
                         val difficulty: String? = null, val views: Long = 0, val rating: Double? = null)

/** harptabs.ArtistPage: an artist page read: the name as the page heads it, how many tabs it says the artist has
 * ([tabs]), and the tabs it lists ([listed]: the first 30, the most viewed first). */
data class HarpArtistPage(val name: String, val tabs: Long, val listed: List<HarpListedTab> = emptyList())

/**
 * harptabs.com for a lookup's song (harptabs_fetch.py's `harptabs_tabs` with `only` its song and
 * `refresh_index=False`: the phone reads no sitemap, its index is the computer's) and an artist's page read now
 * (harptabs_index.py's `read_artist`, `caracole harptabs --artist`). Every request is the lookup's client's, at the
 * lookup pace. Errors are never misses: a block propagates, a spent budget ends the pass, and any other provider error
 * (a page that won't parse, fetched again included) leaves the song for the next run, in `failures`.
 *
 * A song's candidates: the tabs of its title the read page of one of its artists lists, the most viewed first, then
 * the sitemap's, lowest id first, [CANDIDATES] at most; none unless the sitemap lists an artist by one of the song's
 * names' forms. Each is read for its artist, kept only when one of the song's ([sameArtist]); of those, the most viewed
 * (then the best rated, then the lowest id) is kept as the song's lowest free `harmonica-N.txt`, under a version of
 * provider `harptabs` and kind `harmonica`. A tab you picked (`[harptabs]`) is read alone and kept whoever its page
 * names. A miss is kv `harptabs:checked:<song id>`, asked again after 30 days, and a pick's `…:pick`. info.json is
 * the viewer's (milestone 5's): none is written here.
 *
 * Each artist page stored (read, or gone) is noted for the next push to the computer (core.index.Reads, site
 * `harptabs`, the page's path).
 */
object HarpTabsFetch {
    const val PROVIDER = "harptabs"

    /** harptabs_fetch.CANDIDATES: a title's tabs read for one song at most. */
    const val CANDIDATES = 8

    /** harptabs_fetch.RECHECK_AFTER: a song whose candidates were none of its artist's is asked again after this. */
    val RECHECK_AFTER: Duration = Duration.ofDays(30)

    /** harptabs_index.ARTIST_MAX_AGE: an artist page is read again after this. */
    val ARTIST_MAX_AGE: Duration = Duration.ofDays(30)

    /** harptabs_fetch.CHECKED_PREFIX, + song id: when its candidates last answered for it. */
    const val CHECKED_PREFIX = "harptabs:checked:"

    /** harptabs_fetch.PICKED: CHECKED_PREFIX + song id + this: the tab you picked that was asked for then. */
    const val PICKED = ":pick"

    /** The answers a page may give: a 404 is one (the tab, or the artist, is gone). */
    val ACCEPT: Set<Int> = setOf(200, 404)

    /** harptabs_tabs for a lookup's songs ([only]): keep a harmonica tab for each that wants one and has a candidate;
     * see the object's docs. With no song that wants a tab, nothing is sent. */
    fun harptabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): HarpTabsStats = HarpPass.harptabsTabs(db, client, lib, now, overrides, only)

    /** read_artist: one artist page into the index now, as an artist's Songs asks for it; null when the site no
     * longer has it (404, stored as gone). Read once in 30 days: a copy the cache holds from within them is read again,
     * with no request; an older one the budget can't replace is BudgetExhausted. A cached copy that won't parse is
     * asked for once more. Provider errors propagate. */
    fun readArtist(db: Db, client: Client, path: String, now: Instant): HarpArtistPage? =
        Artists.read(db, client, path, now)

    /** store_artist_page: an artist page's tabs into the index, in place of those it gave before, in one savepoint,
     * the songs' keys made current first; noted for the next push. */
    fun storeArtistPage(db: Db, path: String, page: HarpArtistPage, now: Instant) = Artists.store(db, path, page, now)

    /** store_gone: an artist page that answered 404: no tab, no name, and when it answered. */
    fun storeGone(db: Db, path: String, now: Instant) = Artists.store(db, path, HarpArtistPage("", 0), now)

    /** artist_paths: the artist pages the sitemap lists for [name]: its page's path or address as it is, else the
     * artists whose slug's key is one of the name's forms, hyphens aside, lowest id first. */
    fun artistPaths(db: Db, name: String): List<String> = Artists.paths(db, name)

    /** same_artist: whether the artist a tab page names is one of the song's (they share a form, hyphens aside); a
     * page of no known artist (null) is no one's. */
    fun sameArtist(song: SongRow, artist: String?): Boolean = HarpPass.sameArtist(song, artist)

    /** songs_with_a_harmonica_tab: the songs the files table holds a harmonica tab for. */
    fun songsWithAHarmonicaTab(db: Db): Set<Long> = HarpPass.withATab(db)
}
