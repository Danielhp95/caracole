package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.GameTabsFetch
import io.github.danielhp95.caracole.core.sites.GameTabsPages
import java.time.Instant

/**
 * get.py's gametabs stage: a song's text tab of game music from gametabs.net, from the index the computer's nightly
 * run read (no sitemap is asked for by a lookup), or the tab you picked (`[gametabs]`): [GameTabsFetch.gametabsTabs]
 * for the song alone, its spent budget and its first failure raised again inside the asking, as get.py's `ask` raises
 * them. "game music tab kept" ([KEPT]) or "no tab there of its game or composer"; skipped when no tab was wanted or the
 * index has no tab of the title of its game or composer. What the asking came to otherwise (the site off, cooling,
 * blocked, a spent budget, an error) is said in get.py's `_usable` and `asking` words ([end]).
 */
object GameTabsStage : SiteStage {
    /** get.GAMETABS_KEPT. */
    const val KEPT = "game music tab kept"
    const val NONE_THERE = "no tab there of its game or composer"
    const val NOT_ASKED = "no tab wanted, or gametabs.net's index has no tab of the title of its game or composer"

    override fun run(ctx: StageContext): StageEnd {
        val asked = ctx.asking.ask(GameTabsPages.PROVIDER) { client ->
            val s = GameTabsFetch.gametabsTabs(ctx.db, client, ctx.library, ctx.now, ctx.overrides, setOf(ctx.song.id))
            if (s.budgetExhausted) throw BudgetExhausted(GameTabsPages.PROVIDER)
            s.failures.firstOrNull()?.let { throw it.second }
            when {
                s.tried == 0 -> StageEnd("skipped", NOT_ASKED)
                s.kept > 0 -> StageEnd("done", KEPT)
                else -> StageEnd("done", NONE_THERE)
            }
        }
        return end(ctx.config, asked)
    }

    /** get.NAMES' "gametabs.net". */
    private const val NAME = "gametabs.net"

    /**
     * The stage's end for what asking came to: the work's own, else get.py's words for the rest, as lane lookup's
     * LookupWords.end says them for any site (`_usable`: off, blocked or failed earlier, said by the asking itself;
     * cooling; `asking`: blocked now, its cooldown's end; the budget spent; a provider's error).
     */
    internal fun end(config: PhoneConfig, asked: Asked<StageEnd>): StageEnd = when (asked) {
        is Asked.Done -> asked.value
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", "$NAME is cooling down after a block, until ${until(asked.until)}")
        is Asked.Blocked -> StageEnd("skipped", "${name(asked.error.provider)} blocked caracole (${asked.error.message}): " +
            "no more requests to it until ${until(asked.state.cooldownUntil)}. Nothing was marked not found.")
        is Asked.Spent -> {
            val p = config.provider(GameTabsPages.PROVIDER)
            val spent = when {
                asked.keptForSheets -> "this hour's lookups have spent half of their ${p.lookupPerHour} requests to " +
                    "$NAME, and the other half is kept for sheets"
                asked.hour -> "this hour's ${p.lookupPerHour} lookup requests to $NAME are spent"
                else -> "the lookup's ${p.lookupRequests} requests to $NAME are spent"
            }
            StageEnd("skipped", "$spent; the nightly run does the rest")
        }
        is Asked.Failed -> StageEnd("failed", "${name(asked.error.provider)} failed (${asked.error.message}); the " +
            "nightly run tries again")
    }

    private fun name(provider: String) = if (provider == GameTabsPages.PROVIDER) NAME else provider

    /** `strftime("%Y-%m-%d %H:%M UTC")`, or "later" for no time. */
    private fun until(at: Instant?): String {
        if (at == null) return "later"
        val stamp = Stamps.of(at)  // 2026-11-04T14:00:00Z
        return stamp.substring(0, 10) + " " + stamp.substring(11, 16) + " UTC"
    }
}
