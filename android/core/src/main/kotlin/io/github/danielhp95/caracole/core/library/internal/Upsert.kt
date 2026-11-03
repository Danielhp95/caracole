package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.RemovedRow
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonPrimitive

/**
 * songs.upsert_song and the tombstones of removed songs, on the phone: the one way a song is added, so that a song
 * removed stays removed until it is asked for again, and then comes back new (AGENTS.md's invariant).
 * vectors/library/add.jsonl holds Python's answers.
 */
internal object Upsert {
    /** What [upsertSong] did: the song's id, and whether it is new. */
    data class Upserted(val id: Long, val created: Boolean)

    /**
     * songs.upsert_song: the song of these names inserted, or the one that has [sourceId] (else the song's identity
     * key) found and given what its source says now (its album, duration, ISRC, variant: [variant], else the one
     * its title names). A tombstone of the source id or of the key goes. A new song's artist takes the library's
     * spelling when it differs in case alone ([artistAsWritten]). [now] is the time its record is written (songs.py's
     * clock). IllegalArgumentException for no artist.
     */
    fun upsertSong(db: Db, artists: List<String>, title: String, album: String?, durationMs: Long?, isrc: String?,
                   source: String, sourceId: String, addedAt: String, now: String, variant: String? = null): Upserted {
        val names = artists.map { Py.strip(it) }.filter { it.isNotEmpty() }.toMutableList()
        require(names.isNotEmpty()) { "a song needs at least one artist" }
        val cleanTitle = Py.strip(title)
        val key = Normalize.identityKey(names[0], cleanTitle)
        val said = Said(album, durationMs, isrc, variant ?: Normalize.titleVariant(cleanTitle))
        Rekey.ensure(db, now)
        removedWithSourceId(db, source, sourceId)?.let { forgetRemoved(db, it.key) }
        val row = withSourceId(db, source, sourceId) ?: Songs.byKey(db, key)
        removedSong(db, row?.key ?: key)?.let { forgetRemoved(db, it.key) }
        if (row == null) {
            names[0] = artistAsWritten(db, names[0], key)
            db.execute(
                "INSERT INTO songs (key, artist, title, artists, album, duration_ms, isrc, source_ids, added_at, " +
                    "variant, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                key, names[0], cleanTitle, SongKv.namesText(names), album, durationMs, isrc,
                SongKv.idsText(mapOf(source to listOf(JsonPrimitive(sourceId)))), addedAt, said.variant, now, now,
            )
            return Upserted(db.lastRowid(), true)
        }
        val before = SongKv.sourceIds(row.sourceIds)
        val ids = SongKv.addIds(SongKv.sourceIds(row.sourceIds), mapOf(source to listOf(JsonPrimitive(sourceId))))
        val added = if (Canonical.KEY_ORDER.compare(row.addedAt, addedAt) >= 0) row.addedAt else addedAt
        if (ids == before && added == row.addedAt && said == Said(row.album, row.durationMs, row.isrc, row.variant)) {
            return Upserted(row.id, false)
        }
        db.execute(
            "UPDATE songs SET source_ids = ?, added_at = ?, album = ?, duration_ms = ?, isrc = ?, variant = ?, " +
                "updated_at = ? WHERE id = ?",
            SongKv.idsText(ids), added, said.album, said.durationMs, said.isrc, said.variant, now, row.id,
        )
        return Upserted(row.id, false)
    }

    private data class Said(val album: String?, val durationMs: Long?, val isrc: String?, val variant: String?)

    /**
     * songs._artist_as_written: the primary [artist] of a new song keyed [key], as the library writes them: when no
     * song of that artist (by the key's artist side) has their folder but one has a folder that differs from it in
     * case alone, the oldest such song's spelling, so that an artist keeps one folder on a file system blind to case.
     */
    fun artistAsWritten(db: Db, artist: String, key: String): String {
        val folder = SafeName.safeName(artist)
        val theirs = artistSongs(db, key).map { (_, other) -> other to SafeName.safeName(other) }
        if (theirs.any { it.second == folder }) return artist
        val wanted = PyUnicode.casefold(folder)
        return theirs.firstOrNull { PyUnicode.casefold(it.second) == wanted }?.first ?: artist
    }

    /** The songs whose key's artist side is [key]'s, by id: (id, artist). "0" is the character after "/". */
    fun artistSongs(db: Db, key: String): List<Pair<Long, String>> {
        val side = key.substringBefore('/')
        return db.query("SELECT id, artist FROM songs WHERE key >= ? AND key < ? ORDER BY id", "$side/", "${side}0") {
            it.long(0)!! to it.text(1)!!
        }
    }

    /** songs._with_source_id: the first song with [sourceId] among its ids from [source]. */
    private fun withSourceId(db: Db, source: String, sourceId: String): SongRow? =
        db.one(
            "SELECT songs.id FROM songs, json_each(songs.source_ids, ?) AS sid WHERE sid.value = ? " +
                "ORDER BY songs.id LIMIT 1",
            "$.\"$source\"", sourceId,
        ) { it.long(0)!! }?.let { Songs.byId(db, it) }

    private fun removedWithSourceId(db: Db, source: String, sourceId: String): RemovedRow? =
        db.one(
            "SELECT removed.key, removed.artist, removed.title, removed.source_ids, removed.removed_at " +
                "FROM removed, json_each(removed.source_ids, ?) AS sid WHERE sid.value = ? " +
                "ORDER BY removed.removed_at DESC LIMIT 1",
            "$.\"$source\"", sourceId,
        ) { removed(it) }

    /** songs.removed_song: the tombstone of [key]. */
    fun removedSong(db: Db, key: String): RemovedRow? =
        db.one("SELECT key, artist, title, source_ids, removed_at FROM removed WHERE key = ?", key) { removed(it) }

    private fun removed(r: Row) =
        RemovedRow(r.text(0)!!, r.text(1)!!, r.text(2)!!, r.text(3)!!, r.text(4)!!)

    /** songs.forget_removed: whether [key] had a tombstone, now gone. */
    fun forgetRemoved(db: Db, key: String): Boolean = db.execute("DELETE FROM removed WHERE key = ?", key) > 0

    /** songs.mark_removed: the song's tombstone, a tombstone of its key there already gaining its source ids and
     * the later time. */
    fun markRemoved(db: Db, song: SongRow, removedAt: String): RemovedRow {
        val before = removedSong(db, song.key)
        val ids = SongKv.addIds(before?.let { SongKv.sourceIds(it.sourceIds) } ?: LinkedHashMap(),
                                SongKv.sourceIds(song.sourceIds))
        val at = if (before != null && Canonical.KEY_ORDER.compare(before.removedAt, removedAt) > 0) before.removedAt
                 else removedAt
        val stone = RemovedRow(song.key, song.artist, song.title, SongKv.idsText(ids), at)
        writeRemoved(db, stone)
        return stone
    }

    /** songs._write_removed. */
    fun writeRemoved(db: Db, stone: RemovedRow) {
        db.execute(
            "INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?) " +
                "ON CONFLICT(key) DO UPDATE SET artist = excluded.artist, title = excluded.title, " +
                "source_ids = excluded.source_ids, removed_at = excluded.removed_at",
            stone.key, stone.artist, stone.title, stone.sourceIds, stone.removedAt,
        )
    }
}
