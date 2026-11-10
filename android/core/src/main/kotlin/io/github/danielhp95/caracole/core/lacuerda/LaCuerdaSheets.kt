package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lacuerda.internal.fetch.Finding
import io.github.danielhp95.caracole.core.lacuerda.internal.fetch.Keeping
import io.github.danielhp95.caracole.core.lacuerda.internal.fetch.ToTry
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import java.time.Duration
import java.time.Instant

/** lacuerda_fetch.LaCuerdaStats: the sheets kept, the misses, and the songs that wait for a shared folder. */
class LaCuerdaStats(var kept: Int = 0, var missing: Int = 0, val shared: MutableList<SharedFolder> = mutableListOf()) :
    PassStats()

/**
 * lacuerda_fetch.py for a lookup's songs, and an artist's page read (`caracole lacuerda --artist`), as the computer
 * asks, chooses and keeps them:
 *
 * - **Which songs** ([ToTry]): not ignored (its status, or `[ignore]`); no kept human sheet that is complete or that
 *   you pinned on Ultimate Guitar; one LaCuerda may have ([mayAsk]: it looks Spanish, by its lyrics, else its title,
 *   and a slug can be built from its artist's name); not asked about in the last 30 days (`lacuerda_checked_at`). A
 *   song whose kept LaCuerda sheet the library lost (deleted, cut short) is asked about whatever its sheet and the
 *   date, so that the sheet is written again; a song you picked on LaCuerda (`[lacuerda]`) is asked about whatever its
 *   language and its sheet, until its sheet is the one kept, or a UG tab you pinned is.
 * - **The artist's page** ([Finding]): the slugs LaCuerda's listings give the name (LaCuerda.artistSlugs), then those
 *   built from it; a 404 or LaCuerda's "aqui llega:" body moves on to the next. Each page is cached 30 days (a stale
 *   copy served once the budget is spent is [io.github.danielhp95.caracole.core.http.BudgetExhausted]), its songs
 *   stored in the index (LaCuerda.storeSongs, the page noted for the next push).
 * - **The version**: the title matched on the page, its best "acordes" version's page; your pick's version, or its
 *   song's best as the index names it, else as its artist's page does. No page, no title, no acordes version or a
 *   version gone is a miss, asked again after 30 days. A cached page that won't parse is asked for once more.
 * - **Keeping it** ([Keeping]): the sheet's coverage of the lyrics decides (Rank.replacesSheet), your pick whatever its
 *   coverage; kept as `sheet.json` (json.dumps(indent=2), a newline after) then `sheet.txt` (no markup), a file of
 *   this version that the library still holds not written again; a complete sheet retires the auto sheet; a sheet met
 *   again rescored. A sheet that would go where another song keeps one waits ([LaCuerdaStats.shared]).
 *
 * Python's nightly parts are left out: the most popular artists' pages, the listings pass and the handoffs of a run
 * that lets a lookup go first (the phone has no lock to hand over). Its info.json is the viewer's, milestone 5's.
 * Errors are never misses: a block propagates, a spent budget ends the pass, any other provider error counts in
 * `errors` and leaves the song for later (Passes.eachSong). vectors/lookup/lacuerda_sheets.jsonl holds every case to
 * Python's (tests/test_conformance_lacuerda_lookups.py, LaCuerdaReplay).
 */
object LaCuerdaSheets {
    const val PROVIDER = "lacuerda"

    /** ARTIST_PAGE_MAX_AGE: an artist page read again once its copy is older. */
    val ARTIST_PAGE_MAX_AGE: Duration = Duration.ofDays(30)

    /** RECHECK_AFTER: a song LaCuerda answered for is asked about again after this long. */
    val RECHECK_AFTER: Duration = Duration.ofDays(30)

    /** _SLUG: an artist's name written as the slug of their page. */
    private val SLUG = PyRegex.compile("[a-z0-9_]+")

    /**
     * lacuerda_sheets: the songs of [only] LaCuerda is worth asking about now, newest first, each asked and its sheet
     * kept when it helps (the object's KDoc), at [now] (each time stored as [Stamps.of] it). A [SharedFolder] waits in
     * [LaCuerdaStats.shared], with nothing written over the other song's file.
     */
    fun lacuerdaSheets(db: Db, client: Client, lib: LibraryStore, rank: RankPolicy, now: Instant, overrides: Overrides,
                       only: Set<Long>): LaCuerdaStats {
        val stats = LaCuerdaStats()
        val stamp = Stamps.of(now)
        val fetched = HashSet<String>()  // the URLs fetched from LaCuerda in this pass
        // _songs_to_try, read whole before the first turn as Python's list is, list_songs re-keying them first
        // (songs.ensure_current_keys: nothing but one kv read while the keys are current).
        Rekey.ensure(db, stamp)
        val songs = Songs.list(db).filter { it.id in only && ToTry.toTry(db, lib, rank, now, overrides, it) }
        val turns = Passes.eachSong(songs.asSequence(), stats, "LaCuerda") { song ->
            val pick = overrides.lacuerda[song.key]
            if (pick != null) {
                pick to Finding.pickedSheet(db, client, pick, song, now, stamp, fetched)
            } else {
                null to Finding.findSheet(db, client, song.artists[0], song.title, now, stamp, fetched)
            }
        }
        for ((song, answer) in turns) {
            val (pick, sheet) = answer
            if (sheet == null) {
                stats.missing++
                Versions.updateSong(db, song.id, mapOf("lacuerda_checked_at" to stamp), stamp)
                continue
            }
            try {
                if (Keeping.record(db, lib, rank, song, sheet, stamp, picked = pick != null)) stats.kept++
            } catch (e: SharedFolder) {  // nothing written over the other song's sheet: this one waits
                stats.shared += e
            }
        }
        return stats
    }

    /**
     * read_artist_page: one artist's page into the index, as caracole serve's Songs of a LaCuerda artist asks for it:
     * under [first] first (none given: [artist] itself when it is written as a slug, `soda_stereo`), then under the
     * slugs for the name, as a lookup tries them (the listings' first). The slug that answered and the songs its page
     * lists (each once), or null when LaCuerda has no page by any of them. Cached 30 days; provider errors propagate.
     */
    fun readArtistPage(db: Db, client: Client, artist: String, now: Instant, first: String? = null): Pair<String, Int>? {
        val firsts = when {
            first != null -> listOf(first)
            PyRe.fullmatch(SLUG, artist) != null -> listOf(artist)
            else -> emptyList()
        }
        val (slug, songs) = Finding.artistSongs(db, client, artist, now, Stamps.of(now), HashSet(), firsts)
            ?: return null
        return slug to songs.map { it.slug }.toSet().size
    }

    /** may_ask: whether LaCuerda may have the song, the rule a lookup and the to-do page go by: it looks Spanish (by
     * its lyrics when it has any, else its title), and a slug of LaCuerda's can be built from its artist's name. */
    fun mayAsk(song: SongRow): Boolean = ToTry.mayAsk(song)

    /** asked_lately: whether LaCuerda was asked about the song in the last 30 days, so that a lookup leaves it alone
     * until they are over (your pick too); for the Requests tab, which then offers no LaCuerda sheet. */
    fun askedLately(song: SongRow, now: Instant): Boolean = !ToTry.before(song.lacuerdaCheckedAt, now - RECHECK_AFTER)
}
