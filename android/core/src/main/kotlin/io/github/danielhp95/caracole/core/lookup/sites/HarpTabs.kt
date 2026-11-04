package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * get.py's harptabs stage: the song's harmonica tab from harptabs.com, from the index the computer's nightly run keeps
 * (HarpTabsFetch: the song's candidates at the lookup pace, or the tab you picked under `[harptabs]`). "harmonica tab
 * kept", "no tab there by the artist", or skipped when no tab was wanted or the index has no candidate; a spent budget
 * or the pass's first failure raised again inside the asking, so that the envelope ends it as get.py's `asking` does,
 * a file another song keeps where the tab goes ([SharedFolder]) its words too.
 */
object HarpTabsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val asked = try {
            ctx.asking.ask(HarpTabsFetch.PROVIDER) { client ->
                val s = HarpTabsFetch.harptabsTabs(ctx.db, client, ctx.library, ctx.now, ctx.overrides, setOf(ctx.song.id))
                if (s.budgetExhausted) throw BudgetExhausted(HarpTabsFetch.PROVIDER)
                s.failures.firstOrNull()?.let { throw it.second }
                when {
                    s.tried == 0 -> StageEnd("skipped", NOT_TRIED)
                    s.kept > 0 -> StageEnd("done", KEPT)
                    else -> StageEnd("done", NONE_THERE)
                }
            }
        } catch (e: SharedFolder) {  // nothing written over the other song's file: this one waits, as in the run
            return StageEnd("failed", HarpTabsEnvelope.sharedFolder(e))
        }
        return HarpTabsEnvelope.end(ctx.config, HarpTabsFetch.PROVIDER, asked)
    }

    /** get.HARPTABS_KEPT: the stage's detail for a tab kept. */
    const val KEPT = "harmonica tab kept"
    const val NONE_THERE = "no tab there by the artist"
    const val NOT_TRIED = "no tab wanted, or harptabs.com's index has no tab of the title by the artist"
}

/**
 * get.py's words for what asking a site came to besides the work's own (`_usable` and `asking`): until lane lookup's
 * LookupWords (`LookupWords.end`, `sharedFolder`) is on main, the harptabs stage's copy of them, word for word; then
 * this goes and the stage calls those.
 */
internal object HarpTabsEnvelope {
    private val NAMES = mapOf("harptabs" to "harptabs.com")
    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    private fun name(provider: String) = NAMES[provider] ?: provider

    /** A cooldown's end as get.py says it, `strftime("%Y-%m-%d %H:%M UTC")`, or "later" for none. */
    fun until(at: Instant?): String = at?.let(WHEN::format) ?: "later"

    fun end(config: PhoneConfig, provider: String, asked: Asked<StageEnd>): StageEnd = when (asked) {
        is Asked.Done -> asked.value
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", "${name(provider)} is cooling down after a block, until ${until(asked.until)}")
        is Asked.Blocked -> StageEnd("skipped", "${name(asked.error.provider)} blocked caracole (${asked.error.message}): " +
            "no more requests to it until ${until(asked.state.cooldownUntil)}. Nothing was marked not found.")
        is Asked.Spent -> {
            val p = config.provider(provider)
            val spent = when {
                asked.keptForSheets -> "this hour's lookups have spent half of their ${p.lookupPerHour} requests to " +
                    "${name(provider)}, and the other half is kept for sheets"
                asked.hour -> "this hour's ${p.lookupPerHour} lookup requests to ${name(provider)} are spent"
                else -> "the lookup's ${p.lookupRequests} requests to ${name(provider)} are spent"
            }
            StageEnd("skipped", "$spent; the nightly run does the rest")
        }
        is Asked.Failed -> StageEnd("failed", "${name(asked.error.provider)} failed (${asked.error.message}); the nightly " +
            "run tries again")
    }

    /** report.shared_folder: a file that would go where another song keeps one. */
    fun sharedFolder(error: SharedFolder): String =
        "${error.message}. Nothing is written over it, and the song waits until the folder is its own: remove one of " +
            "the two (caracole remove), and ask for it again under a shorter title."
}
