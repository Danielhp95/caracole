package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize

/**
 * ug/index.py's `mark_dirty_for_new`, as a merge of UG's sitemaps runs it: the accepted and pinned songs (none
 * ignored) that new tabs belong to are flagged (`ug_dirty = 1`), so that the computer's next fetch ranks their
 * versions again. A song covers a tab listed under its matched keys, or under a variant of its title (`creep-intro`
 * for `creep`), as `ug.lookup.song_tabs` reads them.
 *
 * The new tabs stay in SQLite (a temporary table), never in the heap: a new phone's first import takes the whole of
 * UG's index, over a million of them, and has no song to mark.
 */
internal object NewTabs {
    private const val NEW = "temp._merge_new"

    /** A song new tabs may be for: its id and its matched keys. */
    class Song(val id: Long, val artistKey: String, val songKey: String)

    /** The songs [markDirty] may mark, read before the tabs are taken: with none, there are no new tabs to keep. */
    fun songs(db: Db): List<Song> = db.query(
        "SELECT id, match_artist_key, match_song_key FROM main.songs WHERE match_decision IN ('accept', 'pinned') " +
            "AND status != 'ignored' AND match_artist_key IS NOT NULL AND match_song_key IS NOT NULL ORDER BY id",
    ) { Song(it.long(0)!!, it.text(1)!!, it.text(2)!!) }

    /** The tabs [select] gives (one column of tab ids, read before they are stored), the new tabs [markDirty] reads. */
    fun remember(db: Db, select: String) {
        db.execute("CREATE TEMP TABLE IF NOT EXISTS _merge_new (tab_id INTEGER PRIMARY KEY)")
        db.execute("DELETE FROM $NEW")
        db.execute("INSERT OR IGNORE INTO $NEW (tab_id) $select")
    }

    /** Each of [songs] a tab [remember] kept is for, flagged, [now] its `updated_at` (songs.update_song's); their ids.
     * The tabs it kept are let go. */
    fun markDirty(db: Db, songs: List<Song>, now: String): Set<Long> {
        val marked = LinkedHashSet<Long>()
        if (db.one("SELECT EXISTS (SELECT 1 FROM $NEW)") { it.long(0)!! } == 1L) {
            for (song in songs) {
                if (newTabOf(db, song)) {
                    db.execute("UPDATE main.songs SET ug_dirty = ?, updated_at = ? WHERE id = ?", 1L, now, song.id)
                    marked.add(song.id)
                }
            }
        }
        db.execute("DROP TABLE $NEW")
        return marked
    }

    /** Whether a new tab is one of ug.lookup.song_tabs' for [song]: an indexed tab of its keys, its variant slugs'
     * included. */
    private fun newTabOf(db: Db, song: Song): Boolean = db.query(
        "SELECT song_key FROM main.ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) " +
            "AND tab_id IN (SELECT tab_id FROM $NEW)",
        song.artistKey, song.songKey, "${song.songKey}-%",
    ) { it.text(0)!! }
        .any { key -> key == song.songKey || Normalize.splitVariant(key).first == song.songKey }
}
