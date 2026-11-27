package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneOffset

/**
 * Settings' row "YouTube audio" (the phone-youtube design's §7): its one line, what this phone's sheets from a YouTube
 * video stand on now.
 *
 * - "On · yt-dlp 2026.11.23 · 2 of 50 runs today": yt-dlp's version, the runs of the UTC day (`events` of provider
 *   `youtube`, the bench's among them) against the computer's settings' budget (PhoneConfig's `youtube`);
 * - "Off (the computer's settings)": `[providers.youtube] enabled = false`, taken at a sync;
 * - "Needs the chord models": the models not downloaded (AudioRunner.NOT_DOWNLOADED), else the chords' own reason
 *   ("Chords from audio need Android 13 or later");
 * - "Cooling down until 2026-11-28 13:00 UTC": YouTube refused caracole, asked again after that;
 * - "Out of date: …": the app's yt-dlp no longer reads YouTube (kv `youtube-outdated` naming this version: Y3.6).
 *
 * In that order, the first that holds. Null, no row, for a build that carries no yt-dlp (the release, until stage Y5).
 */
object YouTubeRow {
    /** What the line is made of ([of] reads it; a test gives it). [problem]: Phone.youtubeProblem. */
    data class State(val problem: String?, val coolingUntil: String?, val outdated: String?, val version: String?,
                     val runs: Long, val budget: Long)

    const val OFF = "Off (the computer's settings)"
    const val NEEDS_MODELS = "Needs the chord models"
    const val COOLING = "Cooling down until {when}"
    const val OUTDATED = "Out of date: YouTube changed what yt-dlp {version} reads: caracole's next release brings a fix"

    /** The row's line, null for none. */
    fun line(s: State): String? = when {
        s.problem == YouTubeSheetRunner.OFF -> OFF
        s.problem == YouTubeSheetRunner.NO_YTDLP -> null
        s.problem == AudioRunner.NOT_DOWNLOADED -> NEEDS_MODELS
        s.problem != null -> s.problem.replaceFirstChar { if (it in 'a'..'z') it - 32 else it }
        s.coolingUntil != null -> COOLING.replace("{when}", s.coolingUntil)
        s.outdated != null -> OUTDATED.replace("{version}", s.outdated)
        else -> listOfNotNull("On", s.version?.let { "yt-dlp $it" }, "${s.runs} of ${s.budget} runs today")
            .joinToString(" · ")
    }

    /** The state as the phone holds it now: [problem] Phone.youtubeProblem(), read before the database. */
    fun of(db: Db, config: PhoneConfig, problem: String?, version: String?, now: Instant): State {
        val cooling = if (Health.isCooling(db, PROVIDER, now)) YtDlp.coolingUntil(db) else null
        val runs = db.one("SELECT COUNT(*) FROM events WHERE provider = ? AND at >= ?", PROVIDER, dayOf(now)) { it.long(0) } ?: 0
        return State(problem, cooling, outdated(db.kvGet(OUTDATED_KV), version), version, runs,
                     config.provider(PROVIDER).budget)
    }

    /** The UTC day [now] is in, its first second as `events.at` writes one: the runs counted from it. */
    fun dayOf(now: Instant): String =
        now.atOffset(ZoneOffset.UTC).toLocalDate().atStartOfDay().toInstant(ZoneOffset.UTC).toString()

    /** kv `youtube-outdated` ([kv], `{version, at, reason}`) when it names this [version], its version; null else, and
     * for a record that won't read. */
    fun outdated(kv: String?, version: String?): String? {
        val said = kv?.let { text ->
            ((runCatching { PyJson.loads(text) }.getOrNull() as? JsonObject)?.get("version") as? JsonPrimitive)
                ?.takeIf { it.isString }?.content
        }
        return said?.takeIf { it == version }
    }

    private const val PROVIDER = "youtube"
    private const val OUTDATED_KV = "youtube-outdated"
}
