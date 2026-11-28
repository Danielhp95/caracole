package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.youtube.DayBudget
import io.github.danielhp95.caracole.core.youtube.Outdated
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import java.time.Instant

/**
 * Settings' row "YouTube audio" (the phone-youtube design's §7): its one line, what this phone's sheets from a YouTube
 * video stand on now. No row at all for a build that carries no yt-dlp ([State.engine] false: the release, until stage
 * Y5), whatever Phone.youtubeProblem says there (its chords' reason or the computer's switch come before its yt-dlp's).
 * Else the first that holds:
 *
 * - "Off (the computer's settings)": `[providers.youtube] enabled = false`, taken at a sync;
 * - "Needs the chord models": the models not downloaded (AudioRunner.NOT_DOWNLOADED), else the chords' own reason or
 *   the engine's, capitalised ("Chords from audio need Android 13 or later");
 * - "Cooling down until 2026-11-28 13:00 UTC": YouTube refused caracole, asked again after that;
 * - "Out of date: …": the app's yt-dlp no longer reads YouTube (Outdated.state: kv `youtube-outdated` naming this
 *   version, within 7 days), its words Outcomes.outdated;
 * - "On · yt-dlp 2026.11.23 · 2 of 50 runs in the last 24 hours": the version, and the yt-dlp runs of a rolling 24
 *   hours (`events` of provider `youtube` that ran: ok, error or blocked, and the runs reserved no row followed; a
 *   budget's refusal ran nothing), the bench's among them, of the day's budget (DayBudget: the count and the limit the
 *   automatic pass goes by, PhoneConfig's `youtube` budget); with no [State.budget], the runs alone.
 */
object YouTubeRow {
    /** What the line is made of ([of] reads it; a test gives it). [engine]: PhoneDeps.youtube is there; [problem]:
     * Phone.youtubeProblem. */
    data class State(val engine: Boolean, val problem: String?, val coolingUntil: String?, val outdated: String?,
                     val version: String?, val runs: Long, val budget: Long? = null)

    const val OFF = "Off (the computer's settings)"
    const val NEEDS_MODELS = "Needs the chord models"
    const val COOLING = "Cooling down until {when}"
    const val OUTDATED = "Out of date: {words}"

    /** The row's line, null for no row. */
    fun line(s: State): String? = when {
        !s.engine || s.problem == YouTubeSheetRunner.NO_YTDLP -> null
        s.problem == YouTubeSheetRunner.OFF -> OFF
        s.problem == AudioRunner.NOT_DOWNLOADED -> NEEDS_MODELS
        s.problem != null -> s.problem.replaceFirstChar { if (it in 'a'..'z') it - 32 else it }
        s.coolingUntil != null -> COOLING.replace("{when}", s.coolingUntil)
        s.outdated != null -> OUTDATED.replace("{words}", Outcomes.outdated(s.outdated))
        else -> listOfNotNull("On", s.version?.let { "yt-dlp $it" }, runs(s.runs, s.budget)).joinToString(" · ")
    }

    private fun runs(n: Long, budget: Long?): String = if (budget != null) {
        "$n of $budget run${if (budget == 1L) "" else "s"} in the last 24 hours"
    } else when (n) {
        0L -> "no runs in the last 24 hours"
        1L -> "1 run in the last 24 hours"
        else -> "$n runs in the last 24 hours"
    }

    /** The state as the phone holds it at [now]: [engine] whether it has a yt-dlp, [problem] Phone.youtubeProblem(),
     * read before the database. */
    fun of(db: Db, engine: Boolean, problem: String?, version: String?, now: Instant): State {
        val cooling = if (Health.isCooling(db, PROVIDER, now)) YtDlp.coolingUntil(db) else null
        return State(engine, problem, cooling, version?.takeIf { Outdated.state(db, it, now) != null }, version,
                     runsSince(db, now),
                     PhoneConfig.read(db).provider(PROVIDER).budget)
    }

    /** The yt-dlp runs of the 24 hours before [now]: the phone's day's count, DayBudget.runs. */
    fun runsSince(db: Db, now: Instant): Long = DayBudget.runs(db, now).toLong()

    private const val PROVIDER = "youtube"
}
