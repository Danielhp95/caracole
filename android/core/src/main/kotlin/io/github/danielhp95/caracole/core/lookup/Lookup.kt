package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.internal.LookupRun

/** What `caracole get` is asked: the song's names (and what its wanted.txt line would say), and the pages a lookup
 * picks (`--ug`, `--tab`, `--lacuerda`, `--harptabs`, `--gametabs`); [songbooks]: its songbooks stage too. */
data class LookupRequest(val artist: String, val title: String, val album: String? = null,
                         val durationMs: Long? = null, val ug: String? = null, val tab: String? = null,
                         val lacuerda: String? = null, val harptabs: String? = null, val gametabs: String? = null,
                         val songbooks: Boolean = true) {
    /** get.LookupRequest.display: "Artist - Title", as given. */
    val display: String get() = "$artist - $title"
}

/** What a lookup came to, as get.py's `--progress` end says it. */
data class LookupResult(val songId: Long?, val display: String, val states: Map<String, String>,
                        val details: Map<String, String>, val files: Map<String, String>,
                        val secondsToSheet: Double?, val seconds: Double, val requests: Map<String, Int>,
                        val bug: String?, val refused: String?) {
    val ok: Boolean get() = bug == null
}

/** What a lookup tells as it goes, as get.py's `--progress` lines: a stage's state and words, the song once known,
 * and the files a reader can open. */
interface Progress {
    fun stage(name: String, state: String, detail: String = "")
    fun song(id: Long, display: String) {}
    fun readable(files: Map<String, String>, seconds: Double) {}
}

/**
 * get.py on the phone: one song looked up now, its stages in get.py's order ([LookupWords.STAGES]), each reported as
 * it starts and ends, at the lookup pace alone ([Clients], through [InteractiveAsk]):
 *
 * - `song`: the song found in the library or added to it ([LibraryStore.add], the phone's wanted.txt line), the
 *   pages picked recorded in its overrides (OverrideWriters' `[match]`, `[pin]` in place of the song's pin of its
 *   kind group alone, `[lacuerda]`, `[harptabs]`, `[gametabs]`); an ignored song, a tab of a kind caracole doesn't use
 *   or a pick that can't be recorded refuses the lookup: the song stage failed, the others skipped;
 * - `match`, then `sheet`: a LaCuerda pick first, else Ultimate Guitar's first pass, then LaCuerda's when no sheet is
 *   kept, its running detail the site it asks ([LookupWords.SHEET_FROM]); the sheet readable from here on
 *   ([Progress.readable]);
 * - `pdf`: the song's pages ([pages], milestone 5's PhoneRender; while it is [SongPages.NONE], skipped with get.py's
 *   [LookupWords.NO_PDFS]);
 * - `lyrics`: LRCLIB, Megalobiz, AZLyrics, put together as get.py's `_then` does;
 * - `ug` and `lacuerda` (once the song has a sheet) within what [LookupWords.SHEETS_SHARE] leaves for sheets,
 *   `gtptabs`, `harptabs`, `gametabs`;
 * - `pages`: the song's pages again where it keeps a sheet or a harmonica tab, and the library page, which the phone
 *   makes as it is asked for ([LookupWords.LIBRARY_PAGE]);
 * - `songbooks`: those that list it made again ([songbooks], milestone 6; while [SongbookPages.NONE], skipped).
 *
 * Each site's stage is its file in core/lookup/sites/ ([stages]): the frame calls it with a [StageContext] whose
 * asking is the envelope ([InteractiveAsk]) or, for what follows the sheet, [InteractiveAsk.afterTheSheet]; a file
 * that would go where another song keeps one fails the stage in get.py's words; anything else a stage throws is a bug,
 * said in its stage and in [LookupResult.bug], and the other stages go on. At the end each provider that answered and
 * never blocked has a good run ([io.github.danielhp95.caracole.core.health.Health.recordOk]).
 *
 * [run] blocks: the runner calls it inside `database.writeBlocking`, in autocommit, never one transaction, so each
 * event, block and kv record commits as it happens. [readOverrides] reads the phone's overrides (overrides.py's
 * load_overrides), a test's to stand in.
 */
class Lookup(val cfg: PhoneConfig, val database: Database, val store: LibraryStore, val clients: Clients,
             val pages: SongPages, val songbooks: SongbookPages, val alerts: Alerts, val request: LookupRequest,
             val progress: Progress, val pacing: Pacing, val stages: SiteStages = SiteStages.ALL,
             val readOverrides: (Db) -> Overrides = Overrides::read) {
    fun run(db: Db): LookupResult = LookupRun(this, db).run()
}
