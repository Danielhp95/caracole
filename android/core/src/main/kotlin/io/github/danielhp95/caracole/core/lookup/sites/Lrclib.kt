package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lyrics.Lrclib
import io.github.danielhp95.caracole.core.lyrics.LyricsStats
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * get.py's `_lrclib`, the lyrics stage's first site: LRCLIB's pass for the song ([Lrclib.fetchPendingLyrics]), "found",
 * "LRCLIB has none", "an instrumental", else "already there" (a song with lyrics, or none asked about); a spent budget
 * or an error the pass met said as the envelope says it. The frame (lane lookup's Lookup) puts the three sites' ends
 * together, as `_then` does.
 */
object LrclibStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd {
        val song = Songs.byId(ctx.db, ctx.song.id) ?: ctx.song
        if (song.lyricsStatus == "found" || song.lyricsStatus == "instrumental") return StageEnd("done", ALREADY)
        val asked = ctx.asking.ask(Lrclib.PROVIDER) { client ->
            said(LyricsStages.ended(Lrclib.PROVIDER,
                                    Lrclib.fetchPendingLyrics(ctx.db, client, ctx.library, ctx.now, setOf(song.id))))
        }
        return LyricsStages.end(ctx, Lrclib.PROVIDER, asked)
    }

    private const val ALREADY = "already there"

    /** What LRCLIB's counts say, get.py's table: one found, one missing, one instrumental, else already there. */
    internal fun said(s: LyricsStats): String = when {
        s.found == 1 && s.missing == 0 && s.instrumental == 0 -> "found"
        s.found == 0 && s.missing == 1 && s.instrumental == 0 -> "LRCLIB has none"
        s.found == 0 && s.missing == 0 && s.instrumental == 1 -> "an instrumental"
        else -> ALREADY
    }
}

/**
 * What the three lyrics stages share: a pass's spent budget or first failure raised again inside the asking, so that
 * the envelope ends it as get.py's `asking` does ([ended]); and the words of an end that isn't the work's ([end]):
 * get.py's `_usable` and `asking`, as lane lookup's LookupWords.end says them, and [NOTHING_TO_ASK], equal to its
 * LookupWords.NOTHING_TO_ASK (get.py's None: the Megalobiz and AZLyrics stages' when there is nothing to ask).
 *
 * A copy until lane lookup's LookupWords is on main: then the three stages call `LookupWords.end` and
 * `LookupWords.NOTHING_TO_ASK`, and this object goes (the integration's, or lookup-scenarios', which follows both).
 */
internal object LyricsStages {
    val NOTHING_TO_ASK = StageEnd("nothing", "")

    /** get.NAMES. */
    private val NAMES = mapOf("lrclib" to "LRCLIB", "megalobiz" to "Megalobiz", "azlyrics" to "AZLyrics")

    private fun name(provider: String) = NAMES[provider] ?: provider

    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    private fun until(at: Instant?): String = at?.let(WHEN::format) ?: "later"

    /** The pass's stats, its spent budget or its first failure raised again, as get.py's work raises them. */
    fun <S : PassStats> ended(provider: String, stats: S): S {
        if (stats.budgetExhausted) throw BudgetExhausted(provider)
        stats.failures.firstOrNull()?.let { throw it.second }
        return stats
    }

    /** A stage's end for what asking [provider] came to: the work's words done, else get.py's for the rest. */
    fun end(ctx: StageContext, provider: String, asked: Asked<String>): StageEnd = when (asked) {
        is Asked.Done -> StageEnd("done", asked.value)
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", "Waiting out ${name(provider)} until ${until(asked.until)}")
        is Asked.Blocked -> StageEnd("skipped", "${name(asked.error.provider)} turned us back (${asked.error.message}). " +
            "No more asks until ${until(asked.state.cooldownUntil)}. Nothing marked not on the sites.")
        is Asked.Spent -> {
            val p = ctx.config.provider(provider)
            val spent = when {
                asked.keptForSheets -> "half this hour's ${p.lookupPerHour} asks of ${name(provider)} are spent; the rest " +
                    "is kept for sheets"
                asked.hour -> "no more asks of ${name(provider)} this hour (${p.lookupPerHour} spent)"
                else -> "this fetch's ${p.lookupRequests} asks of ${name(provider)} are spent"
            }
            StageEnd("skipped", "$spent; tonight's run does the rest")
        }
        is Asked.Failed -> StageEnd("failed", "${name(asked.error.provider)} failed (${asked.error.message}); tried " +
            "again tonight")
    }
}
