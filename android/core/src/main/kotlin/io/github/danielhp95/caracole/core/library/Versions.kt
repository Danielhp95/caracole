package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.internal.writes.SongColumns
import kotlinx.serialization.json.JsonObject

/** versions.VersionRow: a row of `versions`, [gone] when its provider answered 404 for it, [stale] when it was found
 * under an earlier match of its song and not listed since. */
data class VersionRow(val id: Long, val provider: String, val tabId: String, val songId: Long, val slot: String,
                      val kind: String, val rating: Double, val votes: Int, val version: Int, val label: String?,
                      val coverage: Double?, val url: String, val raw: JsonObject, val fetchedAt: String,
                      val pickRank: Int?, val gone: Boolean, val stale: Boolean = false)

/**
 * versions.py's writers, and songs.py's update_song and refresh_status, as a site's pass calls them: the rows a
 * song's sync unit carries (its versions, their raw hashed by the JSON it holds, its status), the computer's after
 * the same writes (vectors/library/writes.jsonl). Every method that writes is called inside Database.write.
 */
object Versions {
    /** versions.SHEET_KINDS: every kind the sheet slot holds (UG chords and ukulele chords, LaCuerda's acordes,
     * auto-chords); a kept sheet becomes the slot's only pick, so picks are cleared across all of them. */
    val SHEET_KINDS: List<String> = listOf("chords", "ukulele", "acordes", "auto")

    /** `versions.gone`: a live version, one its provider says is gone, one an earlier match found. */
    const val LIVE = 0
    const val GONE = 1
    const val STALE = 2

    /**
     * versions.upsert_version: the version of [provider]'s [tabId] for the song inserted, or recorded again
     * (refreshed, and live: never gone or stale), its pick and coverage kept; its id. [raw] is stored as
     * json.dumps writes it (its members in their order, its numbers' literals as given: PyJson.float's for a
     * Double). A [version] of 0 is 1, as Python's `int(version or 1)`. [now] is stored as given.
     */
    fun upsert(db: Db, provider: String, tabId: String, songId: Long, slot: String, kind: String, rating: Double,
               votes: Int, version: Int, label: String?, url: String, raw: JsonObject, now: String): Long {
        db.execute(
            "INSERT INTO versions (provider, tab_id, song_id, slot, kind, rating, votes, version, label, url, raw, " +
                "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) " +
                "ON CONFLICT(provider, tab_id, song_id) DO UPDATE SET slot = excluded.slot, kind = excluded.kind, " +
                "rating = excluded.rating, votes = excluded.votes, version = excluded.version, " +
                "label = excluded.label, url = excluded.url, raw = excluded.raw, fetched_at = excluded.fetched_at, " +
                "gone = $LIVE",
            provider, tabId, songId, slot, kind, rating, votes.toLong(), (if (version == 0) 1 else version).toLong(),
            label, url, PyJson.dumps(raw), now,
        )
        return db.one("SELECT id FROM versions WHERE provider = ? AND tab_id = ? AND song_id = ?",
                      provider, tabId, songId) { it.long(0)!! } ?: error("version $provider/$tabId upserted and gone")
    }

    /** versions.set_raw: what the version keeps of its provider's record, replaced; nothing else of it changes. */
    fun setRaw(db: Db, id: Long, raw: JsonObject) {
        db.execute("UPDATE versions SET raw = ? WHERE id = ?", PyJson.dumps(raw), id)
    }

    /** versions.get_version: the version of [id], or null where Python raises KeyError. */
    fun get(db: Db, id: Long): VersionRow? = db.one("SELECT * FROM versions WHERE id = ?", id) { row(it) }

    /** versions.song_versions: the song's versions by id, of the [slot] and [kinds] given (an empty list of kinds:
     * none), live ones alone unless [includeGone]. */
    fun songVersions(db: Db, songId: Long, slot: String? = null, kinds: List<String>? = null,
                     includeGone: Boolean = false): List<VersionRow> {
        val sql = StringBuilder("SELECT * FROM versions WHERE song_id = ?")
        val args = mutableListOf<Any?>(songId)
        if (slot != null) {
            sql.append(" AND slot = ?")
            args.add(slot)
        }
        if (kinds != null) {
            sql.append(" AND kind IN (").append(kinds.joinToString(",") { "?" }).append(")")
            args.addAll(kinds)
        }
        if (!includeGone) sql.append(" AND gone = $LIVE")
        return db.query("$sql ORDER BY id", *args.toTypedArray()) { row(it) }
    }

    /** versions.set_coverage. */
    fun setCoverage(db: Db, id: Long, coverage: Double?) {
        db.execute("UPDATE versions SET coverage = ? WHERE id = ?", coverage, id)
    }

    /** versions.mark_gone: the provider no longer has this version (it answered 404); no pick. */
    fun markGone(db: Db, id: Long) {
        db.execute("UPDATE versions SET gone = ?, pick_rank = NULL WHERE id = ?", GONE, id)
    }

    /** versions.mark_stale: the song's match changed, so its live versions from [provider] were found under the old
     * one: no slot's and no picks until the new match lists them again ([upsert]). How many there were. */
    fun markStale(db: Db, songId: Long, provider: String): Int =
        db.execute("UPDATE versions SET gone = ?, pick_rank = NULL WHERE song_id = ? AND provider = ? AND gone = ?",
                   STALE, songId, provider, LIVE)

    /** versions.set_picks: [versionIds] the picks for these [kinds], ranked 1..n in order (an id of another song's
     * version is none), every older pick of the kinds cleared; all or nothing, and inside a caller's savepoint
     * undone with it. */
    fun setPicks(db: Db, songId: Long, kinds: List<String>, versionIds: List<Long>) {
        db.savepoint("set_picks") {
            db.execute("UPDATE versions SET pick_rank = NULL WHERE song_id = ? AND kind IN (" +
                           kinds.joinToString(",") { "?" } + ")", songId, *kinds.toTypedArray())
            versionIds.forEachIndexed { i, id ->
                db.execute("UPDATE versions SET pick_rank = ? WHERE id = ? AND song_id = ?", i + 1, id, songId)
            }
        }
    }

    /** versions.picks: the song's picks of these [kinds], best first. */
    fun picks(db: Db, songId: Long, kinds: List<String>): List<VersionRow> =
        db.query("SELECT * FROM versions WHERE song_id = ? AND kind IN (" + kinds.joinToString(",") { "?" } +
                     ") AND pick_rank IS NOT NULL ORDER BY pick_rank", songId, *kinds.toTypedArray()) { row(it) }

    /**
     * songs.update_song: [columns] set on the song and `updated_at` [now] (the clock's, songs.utc_now_iso); a JSON
     * column's value (a JsonElement, a String, a number, a List or a Map) stored as json.dumps writes it, a boolean
     * column's as 0 or 1 by Python's truth (`int(bool(value))`), any other as given. No column: nothing, not even
     * `updated_at`. IllegalArgumentException, Python's ValueError and its words, for an unknown column or the id.
     */
    fun updateSong(db: Db, songId: Long, columns: Map<String, Any?>, now: String = Stamps.now()) {
        SongColumns.check(columns.keys)
        if (columns.isEmpty()) return
        val names = columns.keys.toList()
        db.execute("UPDATE songs SET " + names.joinToString(", ") { "$it = ?" } + ", updated_at = ? WHERE id = ?",
                   *names.map { SongColumns.stored(it, columns[it]) }.toTypedArray(), now, songId)
    }

    /** songs.refresh_status: the song's status computed and stored ([updateSong]): ignored, found (it keeps a human
     * or an auto sheet: a guitar part alone never makes it found) or wanted; the status. */
    fun refreshStatus(db: Db, songId: Long, ignored: Boolean, now: String = Stamps.now()): String {
        val status = when {
            ignored -> "ignored"
            db.one("SELECT 1 FROM files WHERE song_id = ? AND name IN (?, ?) LIMIT 1", songId,
                   SHEET_FILE_NAMES[0], SHEET_FILE_NAMES[1]) { true } != null -> "found"
            else -> "wanted"
        }
        updateSong(db, songId, mapOf("status" to status), now)
        return status
    }

    /** songs.SHEET_FILE_NAMES: a song's sheets, the human one first. */
    val SHEET_FILE_NAMES: List<String> = listOf("sheet.txt", "sheet (auto).txt")

    /** versions._row: raw read as json.loads reads it ("{}" for none), gone and stale from the `gone` column. */
    private fun row(r: Row): VersionRow {
        val text = r.text("raw")
        val raw = PyJson.loads(if (text.isNullOrEmpty()) "{}" else text) as? JsonObject
            ?: throw IllegalStateException("version ${r.long("id")}'s raw is no JSON object")
        val state = r.long("gone")!!
        return VersionRow(
            id = r.long("id")!!, provider = r.text("provider")!!, tabId = r.text("tab_id")!!,
            songId = r.long("song_id")!!, slot = r.text("slot")!!, kind = r.text("kind")!!,
            rating = r.double("rating")!!, votes = r.long("votes")!!.toInt(), version = r.long("version")!!.toInt(),
            label = r.text("label"), coverage = r.double("coverage"), url = r.text("url")!!, raw = raw,
            fetchedAt = r.text("fetched_at")!!, pickRank = r.long("pick_rank")?.toInt(), gone = state == GONE.toLong(),
            stale = state == STALE.toLong(),
        )
    }
}
