package io.github.danielhp95.caracole.core.lacuerda.internal.fetch

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.ug.Coverage
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.UgPage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** lacuerda_fetch.py's keeping: `_record`, `_keep` and `_retire_auto_sheet`, writing what Python writes in its order
 * (no savepoint: a [io.github.danielhp95.caracole.core.library.SharedFolder] leaves what was written before it, as
 * Python's does). Every time is [stamp], the pass's `now` as caracole stores a time. */
internal object Keeping {
    /** songs.AUTO_SHEET: the auto-chords sheet, which a complete sheet retires. */
    const val AUTO_SHEET = "sheet (auto).txt"

    /**
     * _record: LaCuerda's version recorded with its coverage of the song's lyrics; kept when no sheet is (or the
     * LaCuerda one kept was lost), when it beats the kept one (Rank.replacesSheet), or when you picked it. The sheet
     * already kept, met again, is only rescored, and once it proves complete the auto sheet gives way. Whether the
     * sheet was kept now.
     */
    fun record(db: Db, lib: LibraryStore, rank: RankPolicy, song: SongRow, sheet: Sheet, stamp: String,
               picked: Boolean = false): Boolean {
        val lyrics = lyricsFromJson(song.lyricsJson)
        val lines = if (lyrics != null) Coverage.lyricLines(lyrics.plain) else emptyList()
        val value = Coverage.coverage(sheet.markup, lines, lineMatch = rank.lineMatch)
        var kept = ToTry.keptSheet(db, song.id)
        if (kept != null && kept.provider == LaCuerdaSheets.PROVIDER && ToTry.lost(db, lib, song)) kept = null
        val vid = Versions.upsert(
            db, provider = LaCuerdaSheets.PROVIDER, tabId = sheet.tabId, songId = song.id, slot = "sheet",
            kind = "acordes", rating = 0.0, votes = 0, version = sheet.version, label = null, url = sheet.url,
            raw = JsonObject(linkedMapOf("lcd" to JsonPrimitive(sheet.song.lcd), "title" to JsonPrimitive(sheet.song.title))),
            now = stamp,
        )
        Versions.setCoverage(db, vid, value)
        val alreadyKept = kept != null && kept.id == vid
        val keep = kept == null ||
            (!alreadyKept && (picked || Rank.replacesSheet(value, kept.coverage, rank.coverageThreshold)))
        if (keep) {
            keep(db, lib, song, vid, sheet, complete = Rank.complete(value, rank.coverageThreshold), stamp = stamp)
        } else if (alreadyKept && Rank.complete(value, rank.coverageThreshold)) {
            retireAutoSheet(db, lib, song, vid)
        }
        Versions.updateSong(db, song.id, mapOf("lacuerda_checked_at" to stamp), stamp)
        return keep
    }

    /**
     * _keep: the sheet kept as `sheet.json` (its record, `json.dumps(doc, ensure_ascii=False, indent=2)` and a
     * newline) then `sheet.txt` (no markup), and picked for the slot. A file of this version kept already and still
     * in the library isn't written again (Kept.keptAlready). A complete sheet retires the auto sheet.
     */
    private fun keep(db: Db, lib: LibraryStore, song: SongRow, versionId: Long, sheet: Sheet, complete: Boolean,
                     stamp: String) {
        val doc = JsonObject(linkedMapOf(
            "provider" to JsonPrimitive(LaCuerdaSheets.PROVIDER), "url" to JsonPrimitive(sheet.url),
            "content" to JsonPrimitive(sheet.markup), "version" to JsonPrimitive(sheet.version),
        ))
        val files = linkedMapOf(
            ToTry.SHEET_JSON to PyJson.dumps(doc, indent = 2, ensureAscii = false) + "\n",
            ToTry.HUMAN_SHEET to UgPage.stripMarkup(sheet.markup),
        )
        for ((name, text) in files) {
            val data = text.toByteArray(Charsets.UTF_8)
            if (!Kept.keptAlready(db, lib, song, versionId, name, data)) {
                Kept.keepFile(db, lib, song, versionId, name, data, rank = 1, now = stamp)
            }
        }
        if (complete) retireAutoSheet(db, lib, song, versionId)
        Versions.setPicks(db, song.id, Versions.SHEET_KINDS, listOf(versionId))
        Versions.refreshStatus(db, song.id, ignored = false, now = stamp)
    }

    /** _retire_auto_sheet: the kept sheet is complete, so `sheet (auto).txt` goes and the kept sheet is the only
     * pick. */
    private fun retireAutoSheet(db: Db, lib: LibraryStore, song: SongRow, versionId: Long) {
        Kept.dropFile(db, lib, song, AUTO_SHEET)
        Versions.setPicks(db, song.id, Versions.SHEET_KINDS, listOf(versionId))
    }
}
