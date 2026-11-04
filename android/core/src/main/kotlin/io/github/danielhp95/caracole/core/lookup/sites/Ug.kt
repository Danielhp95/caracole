package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.internal.fetch.ArtistPages

/**
 * get.py's sheet stage from Ultimate Guitar (`_sheet_from_ug`'s UG pass): the song's first pass, one versions page
 * read (`max_pages_per_group` 1), one sheet scored (`scored_sheets` 1), no version kept beside it and no tab, so the
 * sheet is readable soonest; its words [UgStages.sheetSaid]'s. The frame (LookupRun's `sheetFromUg`) says it asks
 * Ultimate Guitar (`_sheet_from`), asks LaCuerda when no sheet is kept after it, and then says it skipped.
 */
object UgSheetStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        UgStages.notReady(ctx)?.let { return StageEnd("skipped", it) }
        return UgStages.ask(ctx, first = true, UgStages::sheetSaid)
    }
}

/**
 * get.py's ug stage: Ultimate Guitar again, as the nightly run would (the defaults: the top sheets scored, the
 * versions kept beside the one, the tab); its words [UgStages.restSaid]'s. The frame asks it through
 * `InteractiveAsk.afterTheSheet`, so it spends only what leaves `LookupWords.SHEETS_SHARE` of the hour's lookup
 * requests to Ultimate Guitar for sheets (`after_the_sheet`).
 */
object UgStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        UgStages.notReady(ctx)?.let { return StageEnd("skipped", it) }
        return UgStages.ask(ctx, first = false, UgStages::restSaid)
    }
}

/** What the two UG stages share: `_ug_ready`, `_fetch_context`, and get.py's words for what a pass did. */
internal object UgStages {
    /** `_ug_ready`'s words for a review of other UG songs. */
    const val REVIEW = "caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, or run " +
        "caracole review"

    /** get._FIRST_PAGES and _FIRST_SCORED: the first pass's versions pages and sheets fetched. */
    private const val FIRST_PAGES = 1
    private const val FIRST_SCORED = 1

    /**
     * `_ug_ready`: why Ultimate Guitar has nothing to fetch for the song, or null when it has. Where Python reads the
     * song's artist page (a song the index can't settle whose artist page can be found, `artist_is_known`), the phone
     * says it can't yet ([NotYet.WORDS]) until lane ug-fetch-artist fills ArtistPages' route and makes this null.
     */
    fun notReady(ctx: StageContext): String? {
        val song = ctx.song
        if (song.matchDecision in setOf("accept", "pinned")) return null
        if (UgFetch.needsArtistPage(song) && ArtistPages.artistIsKnown(ctx.db, song, ctx.overrides)) {
            return NotYet.WORDS  // ug-fetch-artist: null, its artist's UG page may list it (A6)
        }
        if (song.matchDecision == "review") return REVIEW
        return LookupWords.NOT_IN_INDEX
    }

    /** The sheet stage's words for what its pass kept: "tab N from Ultimate Guitar", or that it kept none. */
    fun sheetSaid(out: SongFetchOutcome): String =
        if (out.sheet != null) "tab ${out.sheet} from Ultimate Guitar" else "Ultimate Guitar has no sheet to keep"

    /** The ug stage's words for what its pass kept: "sheet N · tab M · kept beside it: tab A, tab B". */
    fun restSaid(out: SongFetchOutcome): String {
        val parts = mutableListOf(if (out.sheet != null) "sheet ${out.sheet}" else "no UG sheet")
        if (out.tab != null) parts += "tab ${out.tab}"
        if (out.keptVersions.isNotEmpty()) parts += "kept beside it: " + out.keptVersions.joinToString(", ") { "tab $it" }
        return parts.joinToString(" · ")
    }

    /** `_fetch_context`: the first pass scores one sheet alone, and the versions kept beside it wait for the ug stage. */
    fun context(ctx: StageContext, client: Client, first: Boolean): FetchContext =
        if (first) {
            FetchContext(ctx.db, client, ctx.overrides, ctx.config.rank.copy(scoredSheets = FIRST_SCORED), ctx.library,
                         ctx.now, maxPagesPerGroup = FIRST_PAGES, versions = false)
        } else {
            FetchContext(ctx.db, client, ctx.overrides, ctx.config.rank, ctx.library, ctx.now)
        }

    /**
     * One pass of the song asked of Ultimate Guitar, as get.py's `asking` ends it: [said]'s words for what it kept, a
     * SharedFolder's words (nothing written over the other song's file: this one waits, as in the run), or
     * `LookupWords.end`'s for why it sent nothing more. The envelope marks a matched song whose pass a cooldown, a
     * block, a spent budget or an error cut short owed a fetch (`_owed`: InteractiveAsk's).
     */
    fun ask(ctx: StageContext, first: Boolean, said: (SongFetchOutcome) -> String): StageEnd {
        val song = Songs.byId(ctx.db, ctx.song.id) ?: ctx.song
        val asked = ctx.asking.ask(UgFetch.PROVIDER) { client ->
            try {
                StageEnd("done", said(UgFetch.processSong(context(ctx, client, first), song, guitar = !first)))
            } catch (e: SharedFolder) {
                StageEnd("failed", LookupWords.sharedFolder(e))
            }
        }
        return LookupWords.end(ctx.config, UgFetch.PROVIDER, asked)
    }
}
