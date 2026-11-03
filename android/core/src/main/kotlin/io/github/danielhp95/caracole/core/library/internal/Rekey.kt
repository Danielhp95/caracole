package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.RemovedRow
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/**
 * songs.ensure_current_keys on the phone: when normalize's rules changed (Normalize.KEY_VERSION, kv
 * songs:key_version), every song and tombstone takes the key today's rules give it, once, and songs that now share a
 * key become one, the oldest record kept. vectors/library/ensure_current_keys.jsonl holds Python's answer.
 */
internal object Rekey {
    /** The SONG_FILE_NAMES of songs.py: a song is found once it keeps one of them. */
    private val SHEETS = listOf("sheet.txt", "sheet (auto).txt")

    /** How many songs were re-keyed or merged; nothing (one kv read) when the keys are current. [now] is the time
     * the records changed are written. */
    fun ensure(db: Db, now: String): Int {
        if (db.kvGet(SongKv.KEY_VERSION) == Normalize.KEY_VERSION.toString()) return 0
        return db.savepoint("rekey_songs") {
            val changed = rekey(db, now)
            rekeyRemoved(db)
            db.kvSet(SongKv.KEY_VERSION, Normalize.KEY_VERSION.toString())
            changed
        }
    }

    private class Kept(val song: SongRow) {
        val ids = SongKv.sourceIds(song.sourceIds)
    }

    private fun rekey(db: Db, now: String): Int {
        val groups = LinkedHashMap<String, MutableList<SongRow>>()
        for (song in db.query("SELECT id FROM songs ORDER BY id") { it.long(0)!! }.map { Songs.byId(db, it)!! }) {
            groups.getOrPut(Normalize.identityKey(song.artist, song.title)) { mutableListOf() }.add(song)
        }
        val moves = groups.filter { (key, songs) -> songs.size > 1 || songs[0].key != key }
        // Keys are unique, and one song's new key can be another's old one: park them all first.
        for ((_, songs) in moves) {
            val keep = Kept(songs[0])
            for (other in songs.drop(1)) merge(db, keep, other, now)
            db.execute("UPDATE songs SET key = ? WHERE id = ?", "#rekey:${keep.song.id}", keep.song.id)
        }
        for ((key, songs) in moves) {
            db.execute("UPDATE songs SET key = ? WHERE id = ?", key, songs[0].id)
            followWanted(db, songs[0].id, songs.map { it.key }.toSet() - key, key, now)
        }
        return moves.entries.sumOf { (key, songs) -> songs.size - 1 + (if (songs[0].key != key) 1 else 0) }
    }

    private fun rekeyRemoved(db: Db) {
        val groups = LinkedHashMap<String, MutableList<RemovedRow>>()
        val stones = db.query("SELECT key, artist, title, source_ids, removed_at FROM removed ORDER BY removed_at, key") {
            RemovedRow(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.text(4)!!)
        }
        for (stone in stones) groups.getOrPut(Normalize.identityKey(stone.artist, stone.title)) { mutableListOf() }.add(stone)
        for ((key, group) in groups) {
            if (group.size == 1 && group[0].key == key) continue
            val oldKeys = group.map { it.key }.toSet()
            val ids = LinkedHashMap<String, MutableList<JsonElement>>()
            for (stone in group) {
                SongKv.addIds(ids, SongKv.sourceIds(stone.sourceIds).mapValues { (source, values) ->
                    values.map { v ->
                        if (source == SongKv.WANTED && v is JsonPrimitive && v.isString && v.content in oldKeys) {
                            JsonPrimitive(key)
                        } else v
                    }
                })
            }
            val latest = group.last()
            for (old in oldKeys) db.execute("DELETE FROM removed WHERE key = ?", old)
            Upsert.writeRemoved(db, RemovedRow(key, latest.artist, latest.title, SongKv.idsText(ids), latest.removedAt))
        }
    }

    /** songs._merge: [other] folded into [keep] and deleted; versions [keep] hasn't seen move over unpicked, kept
     * files under names it hasn't used with them. */
    private fun merge(db: Db, keep: Kept, other: SongRow, now: String) {
        SongKv.addIds(keep.ids, SongKv.sourceIds(other.sourceIds))
        db.execute(
            "UPDATE songs SET source_ids = ?, added_at = MAX(added_at, ?), album = COALESCE(album, ?), " +
                "duration_ms = COALESCE(duration_ms, ?), isrc = COALESCE(isrc, ?), " +
                "variant = COALESCE(variant, ?), ug_dirty = 1, updated_at = ? WHERE id = ?",
            SongKv.idsText(keep.ids), other.addedAt, other.album, other.durationMs, other.isrc, other.variant, now,
            keep.song.id,
        )
        db.execute(
            "UPDATE versions SET song_id = ?, pick_rank = NULL WHERE song_id = ? AND NOT EXISTS (" +
                "SELECT 1 FROM versions AS mine WHERE mine.song_id = ? " +
                "AND mine.provider = versions.provider AND mine.tab_id = versions.tab_id)",
            keep.song.id, other.id, keep.song.id,
        )
        db.execute(
            "UPDATE files SET song_id = ?, version_id = (" +
                "SELECT mine.id FROM versions AS mine, versions AS theirs " +
                "WHERE theirs.id = files.version_id AND mine.song_id = ? " +
                "AND mine.provider = theirs.provider AND mine.tab_id = theirs.tab_id) " +
                "WHERE song_id = ? AND name NOT IN (SELECT name FROM files WHERE song_id = ?)",
            keep.song.id, keep.song.id, other.id, keep.song.id,
        )
        db.execute("DELETE FROM songs WHERE id = ?", other.id)
        SongKv.deleteSongKv(db, other.id)
        refreshStatus(db, keep.song.id, ignored = keep.song.status == "ignored", now = now)
    }

    /** songs.refresh_status: ignored, found (a sheet kept) or wanted. */
    fun refreshStatus(db: Db, id: Long, ignored: Boolean, now: String): String {
        val status = when {
            ignored -> "ignored"
            db.one("SELECT 1 FROM files WHERE song_id = ? AND name IN (?, ?) LIMIT 1", id, SHEETS[0], SHEETS[1]) { true }
                == true -> "found"
            else -> "wanted"
        }
        db.execute("UPDATE songs SET status = ?, updated_at = ? WHERE id = ?", status, now, id)
        return status
    }

    /** songs._follow_wanted: a wanted.txt source id is its line's key, and so is its first-seen time's kv key: both
     * move from the song's old keys to its new one. */
    private fun followWanted(db: Db, id: Long, oldKeys: Set<String>, key: String, now: String) {
        val ids = SongKv.sourceIds(Songs.byId(db, id)!!.sourceIds)
        val wanted = ids[SongKv.WANTED]
        if (!wanted.isNullOrEmpty()) {
            ids[SongKv.WANTED] = wanted.map { v ->
                if (v is JsonPrimitive && v.isString && v.content in oldKeys) JsonPrimitive(key) else v
            }.distinct().toMutableList()
            db.execute("UPDATE songs SET source_ids = ?, updated_at = ? WHERE id = ?", SongKv.idsText(ids), now, id)
        }
        for (old in oldKeys) {
            val seen = db.kvGet(SongKv.FIRST_SEEN + old) ?: continue
            val current = db.kvGet(SongKv.FIRST_SEEN + key)
            db.kvSet(SongKv.FIRST_SEEN + key,
                     if (!current.isNullOrEmpty() && Canonical.KEY_ORDER.compare(current, seen) < 0) current else seen)
            db.kvDelete(SongKv.FIRST_SEEN + old)
        }
    }
}
