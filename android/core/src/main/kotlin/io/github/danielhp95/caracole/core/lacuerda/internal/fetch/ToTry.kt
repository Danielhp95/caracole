package io.github.danielhp95.caracole.core.lacuerda.internal.fetch

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.ug.Rank
import java.math.BigInteger
import java.time.Instant

/** lacuerda_fetch.py's songs to try: `_to_try`, `may_ask`, `_kept_sheet`, `_lost` and `_pinned`, as Python reads
 * them. */
internal object ToTry {
    /** HUMAN_SHEET and SHEET_DOCS: what keeping a sheet writes, `sheet.json` first. */
    const val HUMAN_SHEET = "sheet.txt"
    const val SHEET_JSON = "sheet.json"
    val SHEET_DOCS: List<String> = listOf(SHEET_JSON, HUMAN_SHEET)

    /** _to_try: whether LaCuerda is worth asking about [song] now (LaCuerdaSheets' KDoc). */
    fun toTry(db: Db, lib: LibraryStore, rank: RankPolicy, now: Instant, overrides: Overrides, song: SongRow): Boolean {
        val cutoff = now - LaCuerdaSheets.RECHECK_AFTER
        if (song.status == "ignored" || song.key in overrides.ignore) return false
        val kept = keptSheet(db, song.id)
        val pick = overrides.lacuerda[song.key]
        if (pick != null) {  // your pick: until its sheet is the one kept, unless you pinned a UG sheet
            val lost = kept != null && kept.provider == LaCuerdaSheets.PROVIDER && lost(db, lib, song)
            if (kept != null && !lost &&
                (pinned(overrides, song, kept) || (kept.provider == LaCuerdaSheets.PROVIDER && pick.holds(kept.tabId)))) {
                return false
            }
            return lost || before(song.lacuerdaCheckedAt, cutoff)
        }
        if (!(kept != null && kept.provider == LaCuerdaSheets.PROVIDER && lost(db, lib, song))) {
            if (!before(song.lacuerdaCheckedAt, cutoff)) return false  // asked about in the last 30 days
            if (kept != null && (Rank.complete(kept.coverage, rank.coverageThreshold) || pinned(overrides, song, kept))) {
                return false
            }
        }
        return mayAsk(song)
    }

    /** may_ask: it looks Spanish, by its lyrics when it has any, else its title; and a slug can be built from its
     * artist's name. */
    fun mayAsk(song: SongRow): Boolean {
        val lyrics = lyricsFromJson(song.lyricsJson)
        return LaCuerdaPages.looksSpanish(Normalize.cleanTitle(song.title), lyrics?.plain) &&
            LaCuerdaPages.artistSlugCandidates(song.artists[0]).isNotEmpty()
    }

    /** _kept_sheet: the version kept as the song's `sheet.txt` (UG's or LaCuerda's), if any. */
    fun keptSheet(db: Db, songId: Long): VersionRow? {
        val f = Kept.keptFiles(db, songId).firstOrNull { it.name == HUMAN_SHEET } ?: return null
        return Versions.get(db, f.versionId) ?: throw NoSuchElementException("version ${f.versionId}")
    }

    /** _lost: whether a file of the song's kept LaCuerda sheet is no longer in the library as kept (deleted on a synced
     * device, cut short, a link in its place), each hashed. */
    fun lost(db: Db, lib: LibraryStore, song: SongRow): Boolean = Kept.keptFiles(db, song.id).any { f ->
        f.name in SHEET_DOCS && Versions.get(db, f.versionId)?.provider == LaCuerdaSheets.PROVIDER &&
            !Kept.holds(db, lib, song, f.name, f.sha256)
    }

    /** _pinned: whether the kept sheet is a UG tab you pinned for the song (`kept.tab_id.isdigit()`, then `int()`). */
    fun pinned(overrides: Overrides, song: SongRow, kept: VersionRow): Boolean {
        if (kept.provider != "ug" || !isDigits(kept.tabId)) return false
        val tab = PyInt.parse(kept.tabId) ?: return false
        return overrides.pin[song.key].orEmpty().any { BigInteger.valueOf(it) == tab }
    }

    /** str.isdigit: at least one code point, each a digit. */
    fun isDigits(s: String): Boolean {
        if (s.isEmpty()) return false
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (!PyUnicode.isDigit(cp)) return false
            i += Character.charCount(cp)
        }
        return true
    }

    /** stamps.before: whether a stored time is older than [cutoff]; a missing or unreadable one is. */
    fun before(value: String?, cutoff: Instant): Boolean {
        val at = Stamps.parse(value) ?: return true
        return at < Stamps.micros(cutoff)
    }
}
