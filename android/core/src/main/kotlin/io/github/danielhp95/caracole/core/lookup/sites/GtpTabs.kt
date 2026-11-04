package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.GtpTabsFetch
import java.time.Instant

/**
 * get.py's gtptabs stage: a Guitar Pro file from gtptabs.com for the lookup's song, from the index the computer's
 * nightly run keeps ([GtpTabsFetch.gtptabsFiles] for the song alone, no sitemap read). Its own words are get.py's:
 * [KEPT] for a file kept, "no file there" for a song its artist's pages had none for or whose downloads gave none,
 * and [NOT_WANTED], skipped, for a song wanting no file or whose artist the index doesn't know. The pass's spent
 * budget and its first failure are raised again inside the asking, as get.py's work raises them, so that the
 * envelope ends the stage as get.py's `asking` does; a file that would go where another song keeps one
 * (SharedFolder) is the frame's, as get.py's `asking` catches it.
 */
object GtpTabsStage : SiteStage {
    /** get.GTPTABS_KEPT, which the Requests tab's line reads. */
    const val KEPT = "Guitar Pro file downloaded"
    const val NONE_THERE = "no file there"
    const val NOT_WANTED = "no file wanted, or gtptabs.com's index doesn't know the artist"

    override fun run(ctx: StageContext): StageEnd {
        val asked = ctx.asking.ask(GtpTabsFetch.PROVIDER) { client ->
            val s = GtpTabsFetch.gtptabsFiles(ctx.db, client, ctx.library, ctx.now, ctx.overrides, setOf(ctx.song.id))
            if (s.budgetExhausted) throw BudgetExhausted(GtpTabsFetch.PROVIDER)
            s.failures.firstOrNull()?.let { throw it.second }
            when {
                s.tried == 0 -> StageEnd("skipped", NOT_WANTED)
                s.kept > 0 -> StageEnd("done", KEPT)
                else -> StageEnd("done", NONE_THERE)
            }
        }
        return end(ctx, asked)
    }

    /**
     * The stage's end for what asking gtptabs.com came to: the work's own, else get.py's words for the rest
     * (`_usable` and `asking`), as lane lookup's LookupWords.end says them.
     */
    private fun end(ctx: StageContext, asked: Asked<StageEnd>): StageEnd = when (asked) {
        is Asked.Done -> asked.value
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", "$NAME is cooling down after a block, until ${until(asked.until)}")
        is Asked.Blocked -> StageEnd("skipped", "${name(asked.error.provider)} blocked caracole (${asked.error.message}): " +
                                         "no more requests to it until ${until(asked.state.cooldownUntil)}. Nothing " +
                                         "was marked not found.")
        is Asked.Spent -> {
            val p = ctx.config.provider(GtpTabsFetch.PROVIDER)
            val spent = when {
                asked.keptForSheets -> "this hour's lookups have spent half of their ${p.lookupPerHour} requests to " +
                    "$NAME, and the other half is kept for sheets"
                asked.hour -> "this hour's ${p.lookupPerHour} lookup requests to $NAME are spent"
                else -> "the lookup's ${p.lookupRequests} requests to $NAME are spent"
            }
            StageEnd("skipped", "$spent; the nightly run does the rest")
        }
        is Asked.Failed -> StageEnd("failed", "${name(asked.error.provider)} failed (${asked.error.message}); the nightly " +
                                        "run tries again")
    }

    private const val NAME = "gtptabs.com"

    /** get.NAMES' word for the provider an error names (`NAMES.get(p, p)`): gtptabs.com's client's errors are its. */
    private fun name(provider: String): String = if (provider == GtpTabsFetch.PROVIDER) NAME else provider

    /** A cooldown's end as get.py says it, `strftime("%Y-%m-%d %H:%M UTC")`, or "later" for none. */
    private fun until(at: Instant?): String {
        if (at == null) return "later"
        val stamp = Stamps.of(at)  // 2026-11-04T14:00:00Z
        return stamp.substring(0, 10) + " " + stamp.substring(11, 16) + " UTC"
    }
}
