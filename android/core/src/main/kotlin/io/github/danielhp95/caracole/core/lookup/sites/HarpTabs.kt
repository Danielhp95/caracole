package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch

/**
 * get.py's harptabs stage: the song's harmonica tab from harptabs.com, from the index the computer's nightly run keeps
 * (HarpTabsFetch: the song's candidates at the lookup pace, or the tab you picked under `[harptabs]`). "harmonica tab
 * kept", "no tab there by the artist", or skipped when no tab was wanted or the index has no candidate; a spent budget
 * or the pass's first failure raised again inside the asking, so that the envelope ends it as get.py's `asking` does
 * (LookupWords.end). get.py's `asking` also ends a SharedFolder in report.shared_folder's words, which the frame does
 * for every stage (LookupRun.site); this pass never meets one, as harmonica_number (Numbering.harmonica) takes no
 * number a file another song keeps in the folder holds (the stage record "a number another song keeps in the folder
 * they share is never taken").
 */
object HarpTabsStage : SiteStage {
    /** The stage's detail when nothing was asked: no song wanting a tab, or no candidate. */
    const val NOT_TRIED = "no tab wanted, or harptabs.com's index has no tab of the title by the artist"

    /** The stage's detail when every candidate answered and none is the artist's. */
    const val NONE_THERE = "no tab there by the artist"

    override fun run(ctx: StageContext): StageEnd {
        val asked = ctx.asking.ask(HarpTabsFetch.PROVIDER) { client ->
            val s = HarpTabsFetch.harptabsTabs(ctx.db, client, ctx.library, ctx.now, ctx.overrides, setOf(ctx.song.id))
            if (s.budgetExhausted) throw BudgetExhausted(HarpTabsFetch.PROVIDER)
            s.failures.firstOrNull()?.let { throw it.second }
            when {
                s.tried == 0 -> StageEnd("skipped", NOT_TRIED)
                s.kept > 0 -> StageEnd("done", LookupWords.HARPTABS_KEPT)
                else -> StageEnd("done", NONE_THERE)
            }
        }
        return LookupWords.end(ctx.config, HarpTabsFetch.PROVIDER, asked)
    }
}
