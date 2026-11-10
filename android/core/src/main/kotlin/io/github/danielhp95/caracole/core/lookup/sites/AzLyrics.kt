package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lyrics.AzLyrics

/**
 * get.py's `_azlyrics`, the lyrics stage's last site: AZLyrics' plain lyrics for a song the sites before it left
 * without any ([AzLyrics.azlyricsLyrics], `[azlyrics]`'s page from the overrides), "lyrics from AZLyrics" or "AZLyrics
 * has none"; nothing to ask ([LyricsStages.NOTHING_TO_ASK]) when AZLyrics is off or the song isn't one it asks about.
 */
object AzLyricsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val only = setOf(ctx.song.id)
        val picks = ctx.overrides.azlyrics
        if (!ctx.config.provider(AzLyrics.PROVIDER).enabled ||
            AzLyrics.songsToAsk(ctx.db, ctx.now, picks, only = only).isEmpty()) {
            return LyricsStages.NOTHING_TO_ASK
        }
        val asked = ctx.asking.ask(AzLyrics.PROVIDER) { client ->
            val s = LyricsStages.ended(AzLyrics.PROVIDER,
                                       AzLyrics.azlyricsLyrics(ctx.db, client, ctx.library, ctx.now, ctx.overrides, only))
            if (s.found > 0) "lyrics from AZLyrics" else "AZLyrics has none"
        }
        return LyricsStages.end(ctx, AzLyrics.PROVIDER, asked)
    }
}
