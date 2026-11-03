package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.keys.Normalize
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/**
 * A row of `songs`, as songs.py's `Song` reads it: the read side every lane shares. JSON columns stay text
 * ([sourceIds], [matchCandidates], [lyricsJson]) but [artists], read once.
 */
data class SongRow(
    val id: Long, val key: String, val artist: String, val title: String, val artists: List<String>,
    val album: String?, val durationMs: Long?, val isrc: String?, val sourceIds: String, val addedAt: String,
    val variant: String?, val status: String, val review: Boolean, val matchDecision: String?, val matchStep: String?,
    val matchScore: Double?, val matchArtistKey: String?, val matchSongKey: String?, val matchCandidates: String,
    val matchedAt: String?, val ugDirty: Boolean, val ugCheckedAt: String?, val lyricsStatus: String,
    val lyricsJson: String?, val lyricsAt: String?, val lacuerdaCheckedAt: String?, val createdAt: String,
) {
    /** song.display: "Artist - Clean Title", as overrides.toml and the to-do page write it. */
    val display: String get() = Normalize.displayKey(artist, title)
}

/** A row of `removed`: the tombstone a removal leaves. */
data class RemovedRow(val key: String, val artist: String, val title: String, val sourceIds: String, val removedAt: String)

/** The songs and tombstones of the phone's database, read. */
object Songs {
    /** list_songs: newest added first. */
    fun list(db: Db): List<SongRow> = db.query("SELECT * FROM songs ORDER BY added_at DESC, id DESC") { song(it) }

    fun byKey(db: Db, key: String): SongRow? = db.one("SELECT * FROM songs WHERE key = ?", key) { song(it) }

    fun byId(db: Db, id: Long): SongRow? = db.one("SELECT * FROM songs WHERE id = ?", id) { song(it) }

    /** Every tombstone, the latest removed first, as search_removed reads them (list_removed). */
    fun removed(db: Db): List<RemovedRow> =
        db.query("SELECT key, artist, title, source_ids, removed_at FROM removed ORDER BY removed_at DESC, key") {
            RemovedRow(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.text(4)!!)
        }

    /** Whether a tombstone of [key] stands and no song of it does. */
    fun isRemoved(db: Db, key: String): Boolean =
        db.one("SELECT 1 FROM removed WHERE key = ? AND NOT EXISTS (SELECT 1 FROM songs WHERE key = ?)", key, key) {
            true
        } ?: false

    private fun song(r: Row): SongRow = SongRow(
        id = r.long("id")!!, key = r.text("key")!!, artist = r.text("artist")!!, title = r.text("title")!!,
        artists = Json.parseToJsonElement(r.text("artists")!!).jsonArray.map { it.jsonPrimitive.content },
        album = r.text("album"), durationMs = r.long("duration_ms"), isrc = r.text("isrc"),
        sourceIds = r.text("source_ids")!!, addedAt = r.text("added_at")!!, variant = r.text("variant"),
        status = r.text("status")!!, review = r.long("review")!! != 0L, matchDecision = r.text("match_decision"),
        matchStep = r.text("match_step"), matchScore = r.double("match_score"),
        matchArtistKey = r.text("match_artist_key"), matchSongKey = r.text("match_song_key"),
        matchCandidates = r.text("match_candidates")!!, matchedAt = r.text("matched_at"),
        ugDirty = r.long("ug_dirty")!! != 0L, ugCheckedAt = r.text("ug_checked_at"),
        lyricsStatus = r.text("lyrics_status")!!, lyricsJson = r.text("lyrics_json"), lyricsAt = r.text("lyrics_at"),
        lacuerdaCheckedAt = r.text("lacuerda_checked_at"), createdAt = r.text("created_at")!!,
    )
}
