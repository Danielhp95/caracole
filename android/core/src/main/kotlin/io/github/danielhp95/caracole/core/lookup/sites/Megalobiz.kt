package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.lyrics.Megalobiz

/**
 * get.py's `_megalobiz`, the lyrics stage's second site: Megalobiz's timed lyrics for a song LRCLIB left without them
 * ([Megalobiz.megalobizLyrics]), "timed lyrics from Megalobiz" or "Megalobiz has no timed ones" (its asking under
 * `[lyrics]`' `as` told the frame), a record you picked said as kept or gone; nothing to ask
 * ([LyricsStages.NOTHING_TO_ASK]) when Megalobiz is off or the song isn't one it asks about (lyrics timed already, an
 * instrumental, a miss within 30 days, a record picked on another site). Its per-day limit is the lookup's client's (Pace.withinTheDay).
 */
object MegalobizStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val only = setOf(ctx.song.id)
        val picks = ctx.overrides.lyrics
        if (!ctx.config.provider(Megalobiz.PROVIDER).enabled ||
            Megalobiz.songsToAsk(ctx.db, ctx.now, only = only, picks = picks).isEmpty()) {
            return LyricsStages.NOTHING_TO_ASK
        }
        val record = Lyrics.pickedRecord(ctx.song, picks)
        val named = record == null && Lyrics.askedName(ctx.song, picks) != null
        val asked = ctx.asking.ask(Megalobiz.PROVIDER) { client ->
            val stats = Megalobiz.megalobizLyrics(ctx.db, client, ctx.library, ctx.now, only, picks = picks)
            if (named && stats.tried > 0) ctx.askedUnderName()
            val s = LyricsStages.ended(Megalobiz.PROVIDER, stats)
            when {
                record != null -> Lyrics.pickedSaid(record, kept = s.found > 0 || s.timed > 0, gone = s.missing > 0)
                s.found > 0 || s.timed > 0 -> "timed lyrics from Megalobiz"
                else -> "Megalobiz has no timed ones"
            }
        }
        return LyricsStages.end(ctx, Megalobiz.PROVIDER, asked)
    }
}
