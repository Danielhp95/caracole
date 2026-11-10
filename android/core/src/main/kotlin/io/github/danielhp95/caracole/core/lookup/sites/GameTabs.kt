package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.GameTabsFetch
import io.github.danielhp95.caracole.core.sites.GameTabsPages

/**
 * get.py's gametabs stage: a song's text tab of game music from gametabs.net, from the index the computer's nightly
 * run read (no sitemap is asked for by a lookup), or the tab you picked (`[gametabs]`): [GameTabsFetch.gametabsTabs]
 * for the song alone, its spent budget and its first failure raised again inside the asking, as get.py's `ask` raises
 * them. "game music tab kept" ([LookupWords.GAMETABS_KEPT]) or "no tab there of its game or composer"; skipped when
 * no tab was wanted or the index has no tab of the title of its game or composer. What the asking came to otherwise
 * (the site off, cooling, blocked, a spent budget, an error) is said in get.py's `_usable` and `asking` words,
 * [LookupWords.end]'s.
 */
object GameTabsStage : SiteStage {
    const val NONE_THERE = "no tab there of its game or composer"
    const val NOT_ASKED = "no tab wanted, or gametabs.net's index has no tab of the title of its game or composer"

    override fun run(ctx: StageContext): StageEnd {
        val asked = ctx.asking.ask(GameTabsPages.PROVIDER) { client ->
            val s = GameTabsFetch.gametabsTabs(ctx.db, client, ctx.library, ctx.now, ctx.overrides, setOf(ctx.song.id))
            if (s.budgetExhausted) throw BudgetExhausted(GameTabsPages.PROVIDER)
            s.failures.firstOrNull()?.let { throw it.second }
            when {
                s.tried == 0 -> StageEnd("skipped", NOT_ASKED)
                s.kept > 0 -> StageEnd("done", LookupWords.GAMETABS_KEPT)
                else -> StageEnd("done", NONE_THERE)
            }
        }
        return LookupWords.end(ctx.config, GameTabsPages.PROVIDER, asked)
    }
}
