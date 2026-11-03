package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.py.Py

/**
 * A tab an artist page listed (ug/artist_tabs.py `ListedTab`). [page] is that page's address; [artist] and [title]
 * are UG's names, [type] caracole's kind and [label] its part or "acoustic" (null for none); [url] its page.
 * [artistKey] and [songKey] are what it is filed under, [artistForms] and [titleForms] its names' forms, [readAt]
 * when UG gave the list.
 */
internal data class ListedTab(
    val page: String, val tabId: Long, val type: String, val artist: String, val title: String, val label: String?,
    val rating: Double, val votes: Int, val url: String, val artistKey: String, val songKey: String,
    val artistForms: List<String>, val titleForms: List<String>, val readAt: String,
)

/** ug/artist_tabs.py's read side, for searches: the tabs of the artist pages caracole read (`ug_artist_tabs`). */
internal object ListedTabs {
    /** artist_tabs.ROWS_READ: rows the prefilter reads, at most. */
    const val ROWS_READ = 2000

    private const val SELECT = "SELECT page, tab_id, type, artist, title, label, rating, votes, url, artist_key, " +
        "song_key, artist_forms, title_forms, read_at FROM ug_artist_tabs"

    private fun listed(r: Row): ListedTab = ListedTab(
        page = r.text(0)!!, tabId = r.long(1)!!, type = r.text(2)!!, artist = r.text(3)!!, title = r.text(4)!!,
        label = r.text(5), rating = r.double(6)!!, votes = r.long(7)!!.toInt(), url = r.text(8)!!,
        artistKey = r.text(9)!!, songKey = r.text(10)!!, artistForms = Py.split(r.text(11)!!),
        titleForms = Py.split(r.text(12)!!), readAt = r.text(13)!!,
    )

    /** rows_like: the tabs whose names' forms hold one of the `LIKE` [patterns], hyphens and all or written together
     * ("banma" is in `ban-ma-ban-ma`): those holding more of them first, then the shortest names, at most
     * [ROWS_READ]. */
    fun rowsLike(db: Db, patterns: List<String>): List<ListedTab> {
        if (patterns.isEmpty()) return emptyList()
        val numbers = (1..patterns.size)
        val where = numbers.joinToString(" OR ") { "forms LIKE ?$it" }
        val held = numbers.joinToString(" + ") { "(forms LIKE ?$it)" }
        return db.query(
            "$SELECT WHERE $where ORDER BY $held DESC, length(forms), page, tab_id LIMIT $ROWS_READ",
            *patterns.toTypedArray(),
        ) { listed(it) }
    }

    /** song_tabs: the tabs of a song, as it is filed, each once (its latest read), by id. */
    fun songTabs(db: Db, artistKey: String, songKey: String): List<ListedTab> {
        val rows = db.query("$SELECT WHERE artist_key = ? AND song_key = ? ORDER BY tab_id, read_at DESC", artistKey,
                            songKey) { listed(it) }
        val tabs = LinkedHashMap<Long, ListedTab>()
        for (tab in rows) tabs.putIfAbsent(tab.tabId, tab)
        return tabs.values.toList()
    }

    /** unindexed_songs: each song of an artist, as filed, with its tabs the offline index doesn't list (bare ids). */
    fun unindexedSongs(db: Db, artistKey: String): LinkedHashMap<String, Int> {
        val out = LinkedHashMap<String, Int>()
        db.query(
            "SELECT song_key, COUNT(DISTINCT tab_id) FROM ug_artist_tabs a WHERE artist_key = ? " +
                "AND NOT EXISTS (SELECT 1 FROM ug_index i WHERE i.tab_id = a.tab_id) GROUP BY song_key",
            artistKey,
        ) { it.text(0)!! to it.long(1)!!.toInt() }.forEach { (k, n) -> out[k] = n }
        return out
    }

    /** artist_page: the artist page that lists most of an artist's tabs, as filed; null when none does. */
    fun artistPage(db: Db, artistKey: String): String? = db.one(
        "SELECT page FROM ug_artist_tabs WHERE artist_key = ? GROUP BY page ORDER BY COUNT(*) DESC, page LIMIT 1",
        artistKey,
    ) { it.text(0) }
}
