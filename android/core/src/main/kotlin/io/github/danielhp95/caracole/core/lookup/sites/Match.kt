package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.ug.ArtistTabs

/**
 * get.py's match stage (`_Lookup.match`): once, the artist pages the phone's HTTP cache holds kept for searches
 * (`artist_tabs.backfill`, from the cache alone: nothing is sent, no client made, so it runs while UG cools down);
 * then the song matched against the offline index alone (Matcher.matchAll over it, at the lookup's time), and
 * get.py's words for what it came to, read from the song as stored (vectors/match/stage.jsonl). The lookup reads the
 * song again after it.
 *
 * The cache is the lookup's clients' (InteractiveAsk's `cacheDir`); a stage asked through another Asking (a test's)
 * has none, and backfills nothing, as Python's backfill does for a client without a cache.
 */
object MatchStage : SiteStage {
    /** get.MATCH_NOT_FOUND: how the stage ends for a song the offline index lacks, which the phone's Match step
     * reads ("Match: not on UG"). */
    const val MATCH_NOT_FOUND = "not in the offline Ultimate Guitar index"

    override fun run(ctx: StageContext): StageEnd {
        val asking = ctx.asking
        if (asking is InteractiveAsk) backfill(ctx.db, CachedAnswers("ug", asking.clients.cacheDir))
        return StageEnd("done", matched(ctx.db, ctx.song, ctx.overrides, ctx.config.match, Stamps.of(ctx.now)))
    }

    /** ArtistTabs.backfill, which only finds tabs for searches: the matcher reads none of them. Until lane ug-pages
     * fills its declaration (a `TODO`), the stage matches the song without it rather than failing the lookup. */
    private fun backfill(db: Db, cached: CachedAnswers) {
        try {
            ArtistTabs.backfill(db, cached)
        } catch (_: NotImplementedError) {
        }
    }

    /** The stage after the backfill: the song matched, stored at [now], and get.py's words for it. */
    fun matched(db: Db, song: SongRow, overrides: Overrides, policy: MatchPolicy, now: String): String {
        val state = Matcher.indexState(db)
        val r = Matcher.matchAll(db, overrides, policy, listOf(song), now = now).single().new
        val decision = Songs.byId(db, song.id)?.matchDecision
        val target = if (!r.artistKey.isNullOrEmpty() && !r.songKey.isNullOrEmpty()) "${r.artistKey}/${r.songKey}" else ""
        val words = mapOf(
            "accept" to "matched to $target", "pinned" to "pinned to ${target.ifEmpty { "your tab" }}",
            "review" to "not sure which Ultimate Guitar song: $target is the nearest", "not_found" to MATCH_NOT_FOUND,
            "ignored" to "ignored in overrides.toml",
        )
        var said = words[decision.takeUnless { it.isNullOrEmpty() } ?: "not_found"] ?: decision.orEmpty()
        if (state != "complete" && r.step != "override" && r.step != "pin") {
            said += if (state == "empty") " (the offline index is empty: run caracole index build once)"
                    else " (the offline index is incomplete)"
        }
        return said
    }
}
