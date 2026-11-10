package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lyrics.Megalobiz

/**
 * get.py's `_megalobiz`, the lyrics stage's second site: Megalobiz's timed lyrics for a song LRCLIB left without them
 * ([Megalobiz.megalobizLyrics]), "timed lyrics from Megalobiz" or "Megalobiz has no timed ones"; nothing to ask
 * ([LyricsStages.NOTHING_TO_ASK]) when Megalobiz is off or the song isn't one it asks about (lyrics timed already, an
 * instrumental, a miss within 30 days). Its per-day limit is the lookup's client's (Pace.withinTheDay).
 */
object MegalobizStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val only = setOf(ctx.song.id)
        if (!ctx.config.provider(Megalobiz.PROVIDER).enabled || Megalobiz.songsToAsk(ctx.db, ctx.now, only = only).isEmpty()) {
            return LyricsStages.NOTHING_TO_ASK
        }
        val asked = ctx.asking.ask(Megalobiz.PROVIDER) { client ->
            val s = LyricsStages.ended(Megalobiz.PROVIDER, Megalobiz.megalobizLyrics(ctx.db, client, ctx.library, ctx.now, only))
            if (s.found > 0 || s.timed > 0) "timed lyrics from Megalobiz" else "Megalobiz has no timed ones"
        }
        return LyricsStages.end(ctx, Megalobiz.PROVIDER, asked)
    }
}
