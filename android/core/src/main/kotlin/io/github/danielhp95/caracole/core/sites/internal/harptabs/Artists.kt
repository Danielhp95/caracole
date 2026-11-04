package io.github.danielhp95.caracole.core.sites.internal.harptabs

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HarpTabsParseError
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.sites.HarpArtistPage
import io.github.danielhp95.caracole.core.sites.HarpTabs
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import io.github.danielhp95.caracole.core.sites.SiteKeys
import java.time.Instant

/** harptabs_index.py's artist pages on the phone: one read now ([read]), stored ([store]), and the pages a name
 * names ([paths]). Neither the sitemap nor a pass over every artist (artist_pass): those are the computer's. */
internal object Artists {
    private val ADDRESS by lazy {
        PyRegex.compile("""(?:https?://)?(?:www\.)?harptabs\.com/(artist/\d{1,9}/[a-z0-9-]{1,200})/?""")
    }
    private val PATH by lazy { PyRegex.compile("""(artist/\d{1,9}/[a-z0-9-]{1,200})""") }
    private val ARTIST_ID by lazy { PyRegex.compile("""artist/(\d+)""") }

    fun read(db: Db, client: Client, path: String, now: Instant): HarpArtistPage? {
        val url = HarpTabs.pageUrl(path)
        val resp = client.get(url, accept = HarpTabsFetch.ACCEPT, maxAge = HarpTabsFetch.ARTIST_MAX_AGE)
        // no answer for today: stop as the next request would have
        if (HttpRules.stale(resp, now, HarpTabsFetch.ARTIST_MAX_AGE)) throw BudgetExhausted(HarpTabsPages.PROVIDER)
        val page = HttpRules.readOnceMore(client, resp, url, { it is HarpTabsParseError }, fetched = HashSet(),
                                          accept = HarpTabsFetch.ACCEPT) { r ->
            if (r.status == 404) null else HarpTabsPages.parseArtistPage(r.content, r.url)
        }
        store(db, path, page ?: HarpArtistPage("", 0), now)
        return page
    }

    /** store_artist_page (store_gone's with no name and no tab): in place of what the page gave before, in one
     * savepoint, after harptabs_index.ensure_current_keys; and noted for the next push to the computer. */
    fun store(db: Db, path: String, page: HarpArtistPage, now: Instant) {
        SiteKeys.harptabsSongKeys(db)
        val (pageId, key) = rowOf(path)
        val stamp = Stamps.of(now)
        db.savepoint("harptabs_artist_page") {
            db.execute("DELETE FROM harptabs_artist_tabs WHERE artist = ?", path)
            db.execute("INSERT OR REPLACE INTO harptabs_artists (path, page_id, key, name, tabs, read_at) " +
                           "VALUES (?, ?, ?, ?, ?, ?)", path, pageId, key, page.name, page.tabs, stamp)
            page.listed.forEachIndexed { n, t ->
                db.execute("INSERT OR REPLACE INTO harptabs_artist_tabs (artist, tab_id, path, title, song_key, " +
                               "harp_key, difficulty, views, rating, place) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           path, t.tabId, t.path, t.title, HarpTabs.songKey(t.title), t.key, t.difficulty, t.views,
                           t.rating, n)
            }
            Reads.note(db, HarpTabsPages.PROVIDER, path, stamp)
        }
    }

    /** _row_of: an artist page's id and its slug's key, from its path; for a path of no slug (`artist/4`, the site's
     * catch-all), its id alone. */
    private fun rowOf(path: String): Pair<Long, String> {
        HarpTabsPages.parsePageUrl(HarpTabs.pageUrl(path))?.let { return it.pageId to it.key }
        val found = PyRe.match(ARTIST_ID, path) ?: return 0L to ""
        return PyInt.parse(found.groupValues[1])!!.longValueExact() to ""
    }

    fun paths(db: Db, name: String): List<String> {
        val text = Py.split(name).joinToString(" ")
        val found = PyRe.fullmatch(ADDRESS, text) ?: PyRe.fullmatch(PATH, text)
        if (found != null) {
            return listOfNotNull(db.one("SELECT path FROM harptabs_index WHERE path = ? AND kind = ?",
                                        found.groupValues[1], HarpTabs.ARTIST) { it.text(0) })
        }
        val forms = Normalize.nameForms(text).filter { it.isNotEmpty() }.map(Normalize::compact).toSet()
        if (forms.isEmpty()) return emptyList()
        return db.query("SELECT path, key FROM harptabs_index WHERE kind = ? ORDER BY page_id", HarpTabs.ARTIST) {
            it.text(0)!! to it.text(1)!!
        }.filter { (_, key) -> Normalize.compact(key) in forms }.map { it.first }
    }
}
