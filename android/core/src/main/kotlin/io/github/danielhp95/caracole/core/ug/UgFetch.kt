package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.ug.internal.fetch.SongFetch
import io.github.danielhp95.caracole.core.ug.internal.fetch.Slots
import java.time.Duration
import java.time.Instant

/**
 * ug/fetch.py for a lookup's song (its lookup path, never its bulk work: no fetch_songs, rescore_kept_sheets or
 * handoffs): its sheet, the versions kept beside it and its tab, through [FetchContext]'s client.
 *
 * - **Candidates**: the song's tabs in the offline index, at their slugged URLs, and its pins, which replace the kind
 *   group they belong to and are read at the slugged address you pasted; blocked ids never compete, nor a tab at a URL
 *   robots.txt closes, nor one UG redirects there (RobotsClosed: neither gone nor unreadable). A not-found song is
 *   looked up on its artist's UG page, as `_artist_page_route` does ([ArtistRoute], internal/fetch/ArtistPages.kt).
 * - **Ratings**: for each kind group (chords; tabs; ukulele) the page of the lowest unrated id, a slug naming no part
 *   first, up to `maxPagesPerGroup` pages (`guitarPagesPerGroup` for the tabs).
 * - **Slots**, one at a time: the sheet (the top `scoredSheets` chords versions scored for lyric coverage, ranked
 *   complete-first, the best kept as `sheet.txt` and `sheet.json`, the others scored kept beside it as
 *   `version-<tab>.txt` and `.json`, no request more; a pinned sheet's from the cache alone; a complete one retires
 *   `sheet (auto).txt`), then the tab (`tab.txt` and `tab.json`).
 * - A page that won't parse, even fetched again, is asked for again after [UNREADABLE_RETRY], twice as long each time
 *   it still won't, [UNREADABLE_RETRY_MAX] at most (kv `ug:unreadable:<tab>`); the song stays dirty, never a miss.
 * - Only when every slot is done is the song marked checked and clean (`ug_dirty`, `ug_checked_at`); info.json is the
 *   viewer's (M5), which the phone doesn't write.
 *
 * The JSON kept is UG's raw, as PyJson read it (its members in UG's order, its numbers' literals as UG wrote them),
 * written as json.dumps(indent=2, ensure_ascii=False) writes it (vectors/lookup/ug_sheet.jsonl, ug_keep.jsonl;
 * tests/test_conformance_ug_fetch.py). A song's rows are stamped with the fetch's time ([FetchContext.now]), its
 * `updated_at` too.
 */
object UgFetch {
    const val PROVIDER = "ug"
    val CHORDS_KINDS: List<String> = listOf("chords")  // UG's kinds for the sheet slot
    val TAB_KINDS: List<String> = listOf("tabs")
    val UKULELE_KINDS: List<String> = listOf("ukulele")  // the sheet slot's for a song with no chords
    const val AUTO_SHEET = "sheet (auto).txt"
    val SHEET_FILES: List<String> = listOf("sheet.txt", "sheet.json")
    val TAB_FILES: List<String> = listOf("tab.txt", "tab.json")

    /** ug/fetch.py's KEPT_WITHOUT: what a kept version's JSON leaves out of UG's raw record, the tab's rating and votes
     * as they are the day its page is read, so that one tab read on two days, here or by the computer, is kept in the
     * same bytes (a sync's digest leaves them out of the raw record too: Units.VOLATILE_RAW). */
    val KEPT_WITHOUT: Set<String> = setOf("rating", "votes")

    /** A tab page that won't parse, even fetched again, is asked for again after a week, then after twice as long each
     * time it still won't, 90 days at most. */
    val UNREADABLE_RETRY: Duration = Duration.ofDays(7)
    val UNREADABLE_RETRY_MAX: Duration = Duration.ofDays(90)

    /** process_song: one song's UG versions fetched, ranked and kept, one slot at a time; with [guitar] false, the
     * sheet alone (a lookup's first pass), the song left dirty for its tab slot. A block, a spent budget, a provider's
     * error or a [io.github.danielhp95.caracole.core.library.SharedFolder] raises, the song never marked a miss. */
    fun processSong(ctx: FetchContext, song: SongRow, guitar: Boolean = true): SongFetchOutcome =
        SongFetch.processSong(ctx, song, guitar)

    /** keep_version: kept, same, held, sheet, gone, unreadable, closed, no text or unknown. */
    fun keepVersion(ctx: FetchContext, song: SongRow, tabId: Long): String = SongFetch.keepVersion(ctx, song, tabId)

    /** checked_since: whether a fetch settled the song at [since] or after, so what it lacks now, UG lacks. */
    fun checkedSince(db: Db, song: SongRow, since: Instant): Boolean = SongFetch.checkedSince(db, song, since)

    /** needs_artist_page: whether the index can't settle the song, so its artist's UG page should be read. */
    fun needsArtistPage(song: SongRow): Boolean = SongFetch.needsArtistPage(song)

    /** sheet_group: the UG kinds the song's sheet comes from (ukulele chords for a UG ukulele sheet, else chords). */
    fun sheetGroup(db: Db, songId: Long): List<String> = Slots.sheetGroup(db, songId)
}
