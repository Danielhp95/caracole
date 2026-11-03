package io.github.danielhp95.caracole.core.search.internal.suggest

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.HarpTabHit
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.internal.ug.UgHits

/**
 * What a suggestion reads of LaCuerda's, harptabs.com's and gtptabs.com's indexes, ported here as search.py and
 * lacuerda_index.py read them, privately (search-sites and search-lacuerda port the searches themselves): the same
 * SQL, the same rows in the same order, the same hits.
 */
internal object SiteRows {
    private const val LACUERDA = "https://acordes.lacuerda.net"
    private const val HARPTABS = "https://www.harptabs.com"
    private const val GTPTABS = "https://gtptabs.com"

    /** search.SITE_TITLES_READ: another site's songs a title suggestion reads at most. */
    const val SITE_TITLES_READ = 2000

    // --- LaCuerda --------------------------------------------------------------------------------------------------

    /** A song row of `lacuerda_index` as lacuerda_index._song_hit makes it a LaCuerdaHit, and search._lacuerda_song a
     * SiteHit: its page, its versions counted, the page of its best Letra y Acordes version. */
    class LaCuerdaSong(val artistSlug: String, val artistKey: String, val titleKey: String, val versions: String,
                       val hit: SiteHit)

    /** lacuerda_index.songs_like: the songs whose title's key or artist's key holds one of [patterns] (`LIKE`), at
     * most [limit], by path. */
    fun songsLike(db: Db, patterns: List<String>, limit: Int): List<LaCuerdaSong> {
        if (patterns.isEmpty()) return emptyList()
        val where = patterns.joinToString(" OR ") { "title_key LIKE ? OR artist_key LIKE ?" }
        val args = patterns.flatMap { listOf(it, it) } + limit
        return db.query(
            "SELECT path, artist_slug, artist, artist_key, title, title_key, songs, versions, acordes, popular, page " +
                "FROM lacuerda_index WHERE title != '' AND ($where) ORDER BY path LIMIT ?",
            *args.toTypedArray(),
        ) { lacuerdaSong(it) }
    }

    private fun lacuerdaSong(r: Row): LaCuerdaSong {
        val path = r.text(0)!!
        val slug = r.text(1)!!
        val song = path.substringAfter('/', "")
        val acordes = r.long(8)!!
        val versions = r.text(7)!!
        val sheet = if (song.isNotEmpty() && acordes != 0L) versionUrl(slug, song, acordes) else null
        val hit = SiteHit("lacuerda", r.text(4)!!, songUrl(slug, song), 0.0, r.text(2)!!, r.text(3)!!, r.text(5)!!,
                          uploads = Py.len(versions), via = "title", sheet = sheet)
        return LaCuerdaSong(slug, r.text(3)!!, r.text(5)!!, versions, hit)
    }

    /** The artist search.lacuerda_artist gives, as a suggestion names them: the name LaCuerda writes, their page's
     * slug and their songs (their listing's count, or the songs the index holds from their page, the more); null for
     * one the index doesn't know. */
    fun lacuerdaArtist(db: Db, slug: String): Triple<String, String, Int>? {
        val row = db.one(
            "SELECT artist, artist_key, songs FROM lacuerda_index WHERE artist_slug = ? ORDER BY title != '', path LIMIT 1",
            slug,
        ) { it.text(0)!! to it.long(2)!!.toInt() } ?: return null
        require(slug.isNotEmpty()) { "empty LaCuerda artist slug" } // lacuerda.artist_url
        val known = db.one(
            "SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != '' AND page = ?", slug, "$slug/",
        ) { it.long(0)!!.toInt() }!!
        return Triple(row.first, slug, maxOf(row.second, known))
    }

    private fun songUrl(artist: String, song: String): String {
        require(artist.isNotEmpty() && song.isNotEmpty()) { "empty LaCuerda artist or song slug" }
        return "$LACUERDA/$artist/$song"
    }

    private fun versionUrl(artist: String, song: String, n: Long): String {
        require(artist.isNotEmpty() && song.isNotEmpty()) { "empty LaCuerda artist or song slug" }
        require(n >= 1) { "LaCuerda version numbers start at 1, not $n" }
        return "$LACUERDA/$artist/$song${if (n == 1L) "" else "-$n"}.shtml"
    }

    // --- harptabs.com ----------------------------------------------------------------------------------------------

    /** search._HARP_ARTISTS: harptabs.com's artist rows, with what their page said once read; each query adds its
     * WHERE. */
    const val HARP_ARTISTS = "SELECT i.path, i.page_id, i.key, a.name, a.tabs, a.read_at FROM harptabs_index i " +
        "LEFT JOIN harptabs_artists a ON a.path = i.path"

    /** search._HarpArtist: an artist row of harptabs.com's index ([name] null before their page is read, "" for a
     * page gone). */
    class HarpArtist(val path: String, val pageId: Long, val key: String, val name: String?, val tabs: Int?,
                     val readAt: String?) {
        val shown: String get() = name?.takeIf { it.isNotEmpty() } ?: UgHits.titleWords(key)

        /** Whether caracole read their page and it was gone: a page gone names no one. */
        val gone: Boolean get() = readAt != null && name.isNullOrEmpty()
    }

    fun harpArtist(r: Row): HarpArtist =
        HarpArtist(r.text(0)!!, r.long(1)!!, r.text(2)!!, r.text(3), r.long(4)?.toInt(), r.text(5))

    /** The artist search.harptabs_artist gives, as a suggestion names them: their name, their page's path and the tabs
     * their page says they have; null for one the sitemap doesn't list, or whose page is gone. */
    fun harptabsArtist(db: Db, path: String): Triple<String, String, Int>? {
        val row = db.one("$HARP_ARTISTS WHERE i.path = ? AND i.kind = 'artist'", path) { harpArtist(it) } ?: return null
        return if (row.gone) null else Triple(row.shown, row.path, row.tabs ?: 0)
    }

    /** search._harp_grouped: the tabs of the artist pages read that [where] keeps (`t`, the tab; `a`, its artist), a
     * song a hit, the most viewed first. */
    fun harpGrouped(db: Db, where: String, args: List<Any?>, limit: Int? = null): List<SiteHit> {
        val rows = db.query(
            "SELECT t.artist, t.path, t.title, t.song_key, t.views, t.rating, t.harp_key, t.difficulty, a.name " +
                "FROM harptabs_artist_tabs t JOIN harptabs_artists a ON a.path = t.artist " +
                "WHERE $where ORDER BY t.views DESC, t.place, t.artist, t.tab_id" + (if (limit != null) " LIMIT ?" else ""),
            *(if (limit != null) args + limit else args).toTypedArray(),
        ) { HarpRow(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.long(4)!!.toInt(), it.double(5), it.text(6),
                    it.text(7), it.text(8)!!) }
        val songs = LinkedHashMap<Pair<String, String>, MutableList<HarpRow>>()
        for (row in rows) songs.getOrPut(row.artist to row.songKey) { ArrayList() }.add(row)
        return songs.map { (key, tabs) ->
            val best = tabs[0]
            SiteHit("harptabs", songTitle(best.title), harpUrl(best.path), 100.0, artist = best.name,
                    artistKey = Normalize.identityKey(best.name, "").substringBefore('/'), titleKey = key.second,
                    uploads = tabs.size, via = "title",
                    tabs = tabs.map { HarpTabHit(it.title, harpUrl(it.path), it.views, it.rating, it.harpKey, it.difficulty) },
                    page = key.first)
        }
    }

    private class HarpRow(val artist: String, val path: String, val title: String, val songKey: String, val views: Int,
                          val rating: Double?, val harpKey: String?, val difficulty: String?, val name: String)

    /** harptabs.page_url. */
    private fun harpUrl(path: String): String = "$HARPTABS/$path"

    private val BRACKETED: Regex by lazy { PyRegex.compile("\\([^()]*\\)|\\[[^\\[\\]]*\\]") }
    private val BRACKET: Regex by lazy { PyRegex.compile("[()\\[\\]]") }

    /** harptabs.song_title: the song a tab's title names: the title less what it says in brackets, innermost first, a
     * bracket left open gone too; the title as it is when nothing else is left. */
    fun songTitle(title: String): String {
        var text = title
        var before: String? = null
        while (text != before) {
            before = text
            text = BRACKETED.replace(text, " ")
        }
        text = Py.split(BRACKET.replace(text, " ")).joinToString(" ")
        return if (Py.codePoints(text).any { PyUnicode.isAlnum(it) }) text else Py.strip(title)
    }

    // --- gtptabs.com -----------------------------------------------------------------------------------------------

    /** search._gtptabs_keys: the artist keys gtptabs.com may file a name under: its forms' keys, each also last word
     * first ("Elton John" is `john-elton`); none of no one's, nor a placeholder's. */
    fun gtptabsKeys(artist: String): List<String> {
        val keys = ArrayList<String>()
        for (form in Normalize.nameForms(artist)) {
            if (form.isNotEmpty() && !UgHits.noOnes(form) && !Normalize.placeholderArtist(form)) {
                val words = form.split("-")
                keys += form
                keys += (listOf(words.last()) + words.dropLast(1)).joinToString("-")
            }
        }
        return LinkedHashSet(keys).toList()
    }

    /** gtptabs.page_url. */
    fun gtptabsUrl(path: String): String = "$GTPTABS/$path"
}
