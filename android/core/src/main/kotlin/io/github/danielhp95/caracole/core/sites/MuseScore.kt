package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex

/** musescore.SongPage: a possible match, by its title alone: MuseScore's id, its path, its title's key. */
data class MuseScorePage(val pageId: Long, val path: String, val titleKey: String) {
    val url: String get() = "${MuseScorePages.BASE_URL}/$path"
}

/**
 * musescore.py on the phone: links from the index alone. MuseScore gets no request from the phone (nor from the
 * computer, but for its sitemaps): its song pages are the ones the computer's sitemap read left in `musescore_index`,
 * matched by title alone, possible matches you open yourself.
 */
object MuseScorePages {
    const val PROVIDER = "musescore"
    const val BASE_URL = "https://musescore.com"

    /** musescore.MAX_PAGES: a song's pages on the pages, oldest first. */
    const val MAX_PAGES = 3

    private val CHILD by lazy { PyRegex.compile("""https://musescore\.com/sitemaps/song-index/sitemap_songs(\d{1,4})\.xml""") }
    // The sitemaps' slugs are lowercase ASCII letters, digits and underscores (a hyphen let through too); \d Python's.
    private val SONG by lazy { PyRegex.compile("""https://musescore\.com/(song/([a-z0-9_-]{1,300})-(\d{1,12}))""") }

    /** `"18"` for the song sitemap `sitemap_songs18.xml`; null for any other URL. */
    fun sitemapName(url: String): String? = PyRe.fullmatch(CHILD, url)?.groupValues?.get(1)

    /** The song page a sitemap URL is, or null for any other URL, or a title without a key. */
    fun parseSongUrl(url: String): MuseScorePage? {
        val m = PyRe.fullmatch(SONG, url) ?: return null
        val key = Normalize.slugKey(m.groupValues[2])
        return if (key.isEmpty()) null else MuseScorePage(PyInt.parse(m.groupValues[3])!!.toLong(), m.groupValues[1], key)
    }

    /** The key a song's title meets the pages' titles with: its version suffixes go first (clean_title). */
    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))

    /** musescore.song_pages: the index's pages with the song's title, oldest first, at most [limit] (SQLite's LIMIT:
     * a negative one is none); possible matches, on the title alone. It sends no request. */
    fun songPages(db: Db, song: SongRow, limit: Int = MAX_PAGES): List<MuseScorePage> {
        val key = titleKey(song.title)
        if (key.isEmpty()) return emptyList()
        return db.query("SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? ORDER BY page_id " +
                            "LIMIT ?", key, limit.toLong()) {
            MuseScorePage(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }
    }
}
