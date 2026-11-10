package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.sites.GtpTabsFetch

/**
 * get.py's gtptabs stage: a Guitar Pro file from gtptabs.com for the lookup's song, from the index the computer's
 * nightly run keeps ([GtpTabsFetch.gtptabsFiles] for the song alone, no sitemap read). Its own words are get.py's:
 * [KEPT] for a file kept, "no file there" for a song its artist's pages had none for or whose downloads gave none,
 * and [NOT_WANTED], skipped, for a song wanting no file or whose artist the index doesn't know. The pass's spent
 * budget and its first failure are raised again inside the asking, as get.py's work raises them, so that the
 * envelope ends the stage as get.py's `asking` does ([LookupWords.end]); a file that would go where another song
 * keeps one (SharedFolder) is the frame's, as get.py's `asking` catches it.
 */
object GtpTabsStage : SiteStage {
    /** get.GTPTABS_KEPT, which the Requests tab's line reads. */
    const val KEPT = LookupWords.GTPTABS_KEPT
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
        return LookupWords.end(ctx.config, GtpTabsFetch.PROVIDER, asked)
    }
}
