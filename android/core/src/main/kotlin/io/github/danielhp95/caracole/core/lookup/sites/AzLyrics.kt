package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lyrics.AzLyrics
import io.github.danielhp95.caracole.core.lyrics.Lyrics

/**
 * get.py's `_azlyrics`, the lyrics stage's last site: AZLyrics' plain lyrics for a song the sites before it left
 * without any ([AzLyrics.azlyricsLyrics], `[azlyrics]`'s page and `[lyrics]` from the overrides), "lyrics from AZLyrics"
 * or "AZLyrics has none", "under “A - T”" when asked by `[lyrics]`' `as`, a record you picked said as kept or gone;
 * nothing to ask ([LyricsStages.NOTHING_TO_ASK]) when AZLyrics is off or the song isn't one it asks about.
 */
object AzLyricsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val only = setOf(ctx.song.id)
        val picks = ctx.overrides.azlyrics
        val lyrics = ctx.overrides.lyrics
        if (!ctx.config.provider(AzLyrics.PROVIDER).enabled ||
            AzLyrics.songsToAsk(ctx.db, ctx.now, picks, only = only, lyrics = lyrics).isEmpty()) {
            return LyricsStages.NOTHING_TO_ASK
        }
        val record = Lyrics.pickedRecord(ctx.song, lyrics)
        val paged = OverrideUrls.overrideKey(ctx.song.display) in picks // an [azlyrics] page: asked for it, not by name
        val name = if (record != null || paged) null else Lyrics.askedName(ctx.song, lyrics)
        val asked = ctx.asking.ask(AzLyrics.PROVIDER) { client ->
            val s = LyricsStages.ended(AzLyrics.PROVIDER,
                                       AzLyrics.azlyricsLyrics(ctx.db, client, ctx.library, ctx.now, ctx.overrides, only))
            if (record != null) {
                Lyrics.pickedSaid(record, kept = s.found > 0, gone = s.missing > 0)
            } else {
                val said = if (s.found > 0) "lyrics from AZLyrics" else "AZLyrics has none"
                if (s.tried > 0) Lyrics.askedUnder(said, name) else said
            }
        }
        return LyricsStages.end(ctx, AzLyrics.PROVIDER, asked)
    }
}
