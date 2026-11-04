package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.keys.Normalize

/** ug/lookup.py's IndexTab: a tab of the sitemap index, a variant's [label] (`creep-acoustic` is creep's
 * `acoustic`), and the sitemap [path] its page lives at (`radiohead/creep-chords-4169`, "" for none). */
data class IndexTab(val tabId: Long, val type: String, val songKey: String, val label: String?, val path: String = "") {
    /** The tab page's URL: a slugged tab is served at its slugged path alone. */
    val url: String get() = UgPage.pageUrl(tabId, path.ifEmpty { null })
}

/** ug/lookup.py: the local UG index's tabs, and the artist pages learned (kv [ARTIST_URL_KV]`<artist key>`), shared
 * by matching and fetching. */
object UgLookup {
    /** ARTIST_URL_KV: the artist page learned for an artist key, under this prefix. */
    const val ARTIST_URL_KV = "ug:artist_url:"

    private const val SELECT = "SELECT tab_id, type, song_key, path FROM ug_index"

    private fun indexTab(r: Row): IndexTab {
        val songKey = r.text(2)!!
        return IndexTab(r.long(0)!!, r.text(1)!!, songKey, Normalize.splitVariant(songKey).second, r.text(3)!!)
    }

    /** song_tabs: every indexed tab of a song (chords, text tabs and ukulele chords: the index keeps no other type),
     * variant slugs such as `song-key-acoustic` among them, by id. */
    fun songTabs(db: Db, artistKey: String, songKey: String): List<IndexTab> {
        val rows = db.query("$SELECT WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) ORDER BY tab_id",
                            artistKey, songKey, "$songKey-%") { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!! to it.text(3)!!) }
        val out = ArrayList<IndexTab>()
        for ((tabId, type, keyAndPath) in rows) {
            val (key, path) = keyAndPath
            if (key == songKey) {
                out += IndexTab(tabId, type, key, null, path)
                continue
            }
            val (base, label) = Normalize.splitVariant(key)
            if (base == songKey) out += IndexTab(tabId, type, key, label, path)
        }
        return out
    }

    fun artistKnown(db: Db, artistKey: String): Boolean =
        db.one("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", artistKey) { true } != null

    fun learnedArtistUrl(db: Db, artistKey: String): String? = db.kvGet(ARTIST_URL_KV + artistKey)

    fun rememberArtistUrl(db: Db, artistKey: String, url: String) = db.kvSet(ARTIST_URL_KV + artistKey, url)

    /** Drop a learned artist page (UG no longer serves it), so it is learned again. */
    fun forgetArtistUrl(db: Db, artistKey: String) = db.kvDelete(ARTIST_URL_KV + artistKey)

    /** One tab of the index by id, or null when the sitemaps list it bare (or not at all). */
    fun indexTab(db: Db, tabId: Long): IndexTab? = db.one("$SELECT WHERE tab_id = ?", tabId) { indexTab(it) }

    /** A tab's page URL: its slugged path when the index has it, else the bare `/tab/{id}`. */
    fun tabUrlFor(db: Db, tabId: Long): String = indexTab(db, tabId)?.url ?: UgPage.pageUrl(tabId)

    /** A few slugged tabs of an artist, oldest first, with the paths their pages live at: of any type, as each links
     * to the artist's page (ug/fetch.py reads one for that alone). A [limit] below 0 is none, as SQLite reads it. */
    fun artistTabs(db: Db, artistKey: String, limit: Int = 5): List<IndexTab> =
        db.query("$SELECT WHERE artist_key = ? ORDER BY tab_id LIMIT ?", artistKey, limit.toLong()) { indexTab(it) }
}
