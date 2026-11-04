package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py

/**
 * ug/artist_tabs.py's keys: how the tabs of the artist pages caracole read (`ug_artist_tabs`) are filed, made again
 * where they came in from another database's index ([refile]) or after a change to caracole's keys
 * ([ensureCurrentKeys]), with no request.
 *
 * A tab is filed under the index's keys where the index lists one of its page's tabs (the artist, by the key most of
 * them have) or of its song's (the song, by that tab's), so that a song with both slugged and bare-id tabs is one
 * search hit; else under its names' slug keys (`'song-dongye-宋冬野'`). Its names' forms (Normalize.nameForms and
 * listingForms) are kept beside, for the search's prefilter and its scores. Every call runs inside Database.write.
 */
object ArtistTabs {
    /** artist_tabs.KEYS_KEY: the Normalize.KEY_VERSION the keys were made with. */
    const val KEYS_KEY = "ug:artist_tabs:keys"

    private const val MADE =
        "SELECT page, tab_id, artist_key, song_key, artist_forms, title_forms, forms FROM ug_artist_tabs"

    /** ensure_current_keys: every row's keys and forms made again from its names after a change to caracole's keys,
     * once (kv [KEYS_KEY]); how many rows changed. */
    fun ensureCurrentKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(KEYS_KEY) == version) return 0
        return db.savepoint("ug_artist_tabs_keys") {
            val before = made(db)
            val rows = db.query("SELECT page, tab_id, artist, title FROM ug_artist_tabs") {
                listOf(it.text(0)!!, it.long(1)!!, it.text(2)!!, it.text(3)!!)
            }
            for ((page, tabId, artist, title) in rows) {
                val n = names(artist as String, title as String)
                db.execute(
                    "UPDATE ug_artist_tabs SET artist_key = ?, song_key = ?, artist_forms = ?, title_forms = ?, " +
                        "forms = ? WHERE page = ? AND tab_id = ?",
                    n.artistKey, n.songKey, n.artistForms, n.titleForms, n.forms, page, tabId,
                )
            }
            for (page in before.keys.map { it.first }.distinct().sortedWith(Py.CODE_POINT_ORDER)) file(db, page)
            val after = made(db)
            db.kvSet(KEYS_KEY, version)
            before.count { (k, v) -> after[k] != v }
        }
    }

    /**
     * refile: the tabs of these artist pages (their addresses; every page the table holds for null) filed again, as
     * tabs merged from another database's index came in (index_transfer.py); how many rows it filed under other keys.
     * Python's refile takes the pages too, and answers nothing.
     */
    fun refile(db: Db, pages: Collection<String>? = null): Int {
        val before = keysOf(db)
        val which = pages?.toList()
            ?: db.query("SELECT DISTINCT page FROM ug_artist_tabs") { it.text(0)!! }.sortedWith(Py.CODE_POINT_ORDER)
        for (page in which) file(db, page)
        val after = keysOf(db)
        return before.count { (k, v) -> after[k] != v }
    }

    /** _names: a tab's slug keys (the artist's, the song's without a variant label, and that label), its names'
     * forms, space-separated, and every form both hyphenated and written together, for the prefilter ("banma" is in
     * `ban-ma-ban-ma`, a Chinese name's pinyin). */
    internal fun names(artist: String, title: String): Names {
        val clean = Normalize.cleanTitle(title)
        val (base, variant) = Normalize.splitVariant(Normalize.slugKey(clean))
        val artistForms = Normalize.nameForms(artist)
        val titleForms = Normalize.listingForms(clean)
        val every = artistForms + titleForms
        val forms = LinkedHashSet(every + every.map { it.replace("-", "") }).joinToString(" ")
        return Names(Normalize.slugKey(artist), base, variant, artistForms.joinToString(" "),
                     titleForms.joinToString(" "), forms)
    }

    internal data class Names(val artistKey: String, val songKey: String, val variant: String?,
                              val artistForms: String, val titleForms: String, val forms: String)

    /** _file: the page's tabs filed: the artist under the index's key of most of the page's tabs the index lists, a
     * song under the index's key of one of its tabs, and the rest under their names' slug keys. */
    internal fun file(db: Db, page: String) {
        val rows = db.query("SELECT tab_id, artist, title FROM ug_artist_tabs WHERE page = ? ORDER BY tab_id", page) {
            Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }
        if (rows.isEmpty()) return
        val indexed = LinkedHashMap<Long, Pair<String, String>>()
        db.query(
            "SELECT i.tab_id, i.artist_key, i.song_key FROM ug_index i JOIN ug_artist_tabs a ON a.tab_id = i.tab_id " +
                "WHERE a.page = ? ORDER BY i.tab_id",
            page,
        ) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
            .forEach { (tabId, artistKey, songKey) -> indexed[tabId] = artistKey to Normalize.splitVariant(songKey).first }
        val own = LinkedHashMap<Long, Pair<String, String>>()
        for ((tabId, artist, title) in rows) own[tabId] = names(artist, title).let { it.artistKey to it.songKey }
        val artistKey = Py.mostCommonFirst(indexed.values.map { it.first })
            ?: Py.mostCommonFirst(own.values.map { it.first })!!
        val songs = LinkedHashMap<String, String>() // a song's own key -> the index's
        for ((tabId, keys) in indexed) songs.putIfAbsent(own.getValue(tabId).second, keys.second)
        for ((tabId, keys) in own) {
            db.execute("UPDATE ug_artist_tabs SET artist_key = ?, song_key = ? WHERE page = ? AND tab_id = ?",
                       artistKey, songs[keys.second] ?: keys.second, page, tabId)
        }
    }

    private fun made(db: Db): LinkedHashMap<Pair<String, Long>, List<String>> {
        val out = LinkedHashMap<Pair<String, Long>, List<String>>()
        db.query(MADE) { r -> (r.text(0)!! to r.long(1)!!) to (2..6).map { r.text(it)!! } }.forEach { out[it.first] = it.second }
        return out
    }

    private fun keysOf(db: Db): Map<Pair<String, Long>, Pair<String, String>> =
        db.query("SELECT page, tab_id, artist_key, song_key FROM ug_artist_tabs") {
            (it.text(0)!! to it.long(1)!!) to (it.text(2)!! to it.text(3)!!)
        }.toMap()

    // --- milestone 4's additions (lane ug-pages): an artist page's tabs stored as a lookup reads them -----------

    fun store(db: Db, page: String, name: String, tabs: List<UgVersion>, readAt: String): List<Long> =
        TODO("lane ug-pages")
    fun keepOnly(db: Db, page: String, kind: String, ids: Collection<Long>, readAt: String): Int = TODO("lane ug-pages")
    fun forget(db: Db, page: String): Unit = TODO("lane ug-pages")
    fun backfill(db: Db, cached: CachedAnswers): Int = TODO("lane ug-pages")
}
