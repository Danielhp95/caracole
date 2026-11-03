package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize

/**
 * ug/index.py's `mark_dirty_for_new`, as a merge of UG's sitemaps runs it: the accepted and pinned songs (none
 * ignored) that new tabs belong to are flagged (`ug_dirty = 1`), so that the computer's next fetch ranks their
 * versions again. A song covers a tab listed under its matched keys, or under a variant of its title (`creep-intro`
 * for `creep`), as `ug.lookup.song_tabs` reads them.
 */
internal object NewTabs {
    /** The songs [tabIds] are for, flagged, [now] their `updated_at` (songs.update_song's); their ids. */
    fun markDirty(db: Db, tabIds: Collection<Long>, now: String): Set<Long> {
        val new = tabIds.toHashSet()
        if (new.isEmpty()) return emptySet()
        val songs = db.query(
            "SELECT id, match_artist_key, match_song_key FROM songs WHERE match_decision IN ('accept', 'pinned') " +
                "AND status != 'ignored' AND match_artist_key IS NOT NULL AND match_song_key IS NOT NULL",
        ) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
        val marked = LinkedHashSet<Long>()
        for ((id, artistKey, songKey) in songs) {
            if (songTabs(db, artistKey, songKey).any { it in new }) {
                db.execute("UPDATE songs SET ug_dirty = ?, updated_at = ? WHERE id = ?", 1L, now, id)
                marked.add(id)
            }
        }
        return marked
    }

    /** ug.lookup.song_tabs' ids: every indexed tab of a song, its variant slugs' included. */
    private fun songTabs(db: Db, artistKey: String, songKey: String): List<Long> = db.query(
        "SELECT tab_id, song_key FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) " +
            "ORDER BY tab_id",
        artistKey, songKey, "$songKey-%",
    ) { it.long(0)!! to it.text(1)!! }
        .filter { (_, key) -> key == songKey || Normalize.splitVariant(key).first == songKey }
        .map { it.first }
}
