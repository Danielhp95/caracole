package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.internal.fetch.ArtistPages
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * get.py's sheet stage from Ultimate Guitar (`_sheet_from_ug`'s UG pass): the song's first pass, one versions page
 * read (`max_pages_per_group` 1), one sheet scored (`scored_sheets` 1), no version kept beside it and no tab, so the
 * sheet is readable soonest; "tab N from Ultimate Guitar", or "Ultimate Guitar has no sheet to keep". The frame (lane
 * lookup's Lookup) asks LaCuerda when no sheet is kept after it, as `_sheet_from_ug` does, and then says it skipped.
 */
object UgSheetStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        UgStages.notReady(ctx)?.let { return StageEnd("skipped", it) }
        return UgStages.ask(ctx, first = true) { out ->
            if (out.sheet != null) "tab ${out.sheet} from Ultimate Guitar" else "Ultimate Guitar has no sheet to keep"
        }
    }
}

/**
 * get.py's ug stage: Ultimate Guitar again, as the nightly run would (the defaults: the top sheets scored, the
 * versions kept beside the one, the tab), within what the frame's asking leaves for sheets (`after_the_sheet`, lane
 * lookup's); "sheet N · tab M · kept beside it: tab A, tab B", or "no UG sheet".
 */
object UgStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        UgStages.notReady(ctx)?.let { return StageEnd("skipped", it) }
        return UgStages.ask(ctx, first = false) { out ->
            val parts = mutableListOf(if (out.sheet != null) "sheet ${out.sheet}" else "no UG sheet")
            if (out.tab != null) parts += "tab ${out.tab}"
            if (out.keptVersions.isNotEmpty()) {
                parts += "kept beside it: " + out.keptVersions.joinToString(", ") { "tab $it" }
            }
            parts.joinToString(" · ")
        }
    }
}

/** What the two UG stages share: `_ug_ready`, `_fetch_context`, and get.py's words for what asking came to. */
internal object UgStages {
    const val NAME = "Ultimate Guitar"  // get.NAMES["ug"]

    /** get.NOT_IN_INDEX: the sheet stage's words for a song Ultimate Guitar can't be asked about. */
    const val NOT_IN_INDEX = "the offline index doesn't have it, and its artist's UG page isn't known"
    const val REVIEW = "caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, or run " +
        "caracole review"

    /** get._FIRST_PAGES and _FIRST_SCORED: the first pass's versions pages and sheets fetched. */
    private const val FIRST_PAGES = 1
    private const val FIRST_SCORED = 1

    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    /** `_ug_ready`: why Ultimate Guitar has nothing to fetch for the song, or null when it has. */
    fun notReady(ctx: StageContext): String? {
        val song = ctx.song
        if (song.matchDecision in setOf("accept", "pinned")) return null
        if (UgFetch.needsArtistPage(song) && ArtistPages.artistIsKnown(ctx.db, song, ctx.overrides)) return null
        if (song.matchDecision == "review") return REVIEW
        return NOT_IN_INDEX
    }

    /** `_fetch_context`: the first pass scores one sheet alone, and the versions kept beside it wait for the ug stage. */
    fun context(ctx: StageContext, client: Client, first: Boolean): FetchContext =
        if (first) {
            FetchContext(ctx.db, client, ctx.overrides, ctx.config.rank.copy(scoredSheets = FIRST_SCORED), ctx.library,
                         ctx.now, maxPagesPerGroup = FIRST_PAGES, versions = false)
        } else {
            FetchContext(ctx.db, client, ctx.overrides, ctx.config.rank, ctx.library, ctx.now)
        }

    /** One pass of the song asked of Ultimate Guitar, as get.py's `asking` ends it: [said]'s words for what it kept,
     * a SharedFolder's words, or the envelope's for why it sent nothing more. */
    fun ask(ctx: StageContext, first: Boolean, said: (SongFetchOutcome) -> String): StageEnd {
        val song = Songs.byId(ctx.db, ctx.song.id) ?: ctx.song
        val asked = ctx.asking.ask(UgFetch.PROVIDER) { client ->
            try {
                Pass(UgFetch.processSong(context(ctx, client, first), song, guitar = !first), null)
            } catch (e: SharedFolder) {
                Pass(null, e)  // nothing written over the other song's file: this one waits, as in the run
            }
        }
        if (asked !is Asked.Done) {
            owed(ctx)
            return ended(ctx, asked)
        }
        val pass = asked.value
        pass.shared?.let { return StageEnd("failed", sharedFolder(it)) }
        return StageEnd("done", said(pass.outcome!!))
    }

    private class Pass(val outcome: SongFetchOutcome?, val shared: SharedFolder?)

    /** report.shared_folder's words. */
    fun sharedFolder(e: SharedFolder): String = "${e.message}. Nothing is written over it, and the song waits until " +
        "the folder is its own: remove one of the two (caracole remove), and ask for it again under a shorter title."

    /** get.py's `_owed`: a matched song whose Ultimate Guitar part was cut short is owed a fetch at night. */
    private fun owed(ctx: StageContext) {
        val song = Songs.byId(ctx.db, ctx.song.id) ?: return
        if (song.matchDecision in setOf("accept", "pinned") && !song.ugDirty) {
            Versions.updateSong(ctx.db, song.id, mapOf("ug_dirty" to true), now = Stamps.of(ctx.now))
        }
    }

    private fun shown(at: Instant?): String = at?.let(WHEN::format) ?: "later"

    /** get.NAMES.get(provider, provider). */
    private fun named(provider: String): String = if (provider == UgFetch.PROVIDER) NAME else provider

    /** get.py's `asking`'s words for an answer that isn't the work's: the site off, cooling, blocked, spent or failed;
     * never a miss. */
    fun ended(ctx: StageContext, asked: Asked<*>): StageEnd = when (asked) {
        is Asked.Done -> error("a pass done has its own words")
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", "$NAME is cooling down after a block, until ${shown(asked.until)}")
        is Asked.Blocked -> StageEnd("skipped", "${named(asked.error.provider)} blocked caracole " +
            "(${asked.error.message}): no more requests to it until ${shown(asked.state.cooldownUntil)}. Nothing was " +
            "marked not found.")
        is Asked.Spent -> {
            val p = ctx.config.provider(UgFetch.PROVIDER)
            val spent = when {
                asked.keptForSheets -> "this hour's lookups have spent half of their ${p.lookupPerHour} requests to " +
                    "$NAME, and the other half is kept for sheets"
                asked.hour -> "this hour's ${p.lookupPerHour} lookup requests to $NAME are spent"
                else -> "the lookup's ${p.lookupRequests} requests to $NAME are spent"
            }
            StageEnd("skipped", "$spent; the nightly run does the rest")
        }
        is Asked.Failed -> StageEnd("failed", "${named(asked.error.provider)} failed (${asked.error.message}); the " +
            "nightly run tries again")
    }
}
