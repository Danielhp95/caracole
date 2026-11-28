package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The phone's day of yt-dlp runs (the phone-youtube design's §5.3): at most `PhoneConfig.provider("youtube").budget`
 * runs in any 24 hours, the computer's budget for one run used as the phone's day. Every run the phone sent in that
 * window counts, asked-now ones and the bench's among them, whatever its run id: `events` rows of provider `youtube`
 * whose decision is `ok`, `error` or `blocked` ([runs]); a `budget` row ran nothing. A run frees its slot 24 hours
 * after it. Settings' YouTube row says the same count (YouTubeRow.runsSince).
 */
object DayBudget {
    private const val PROVIDER = "youtube"
    private const val DAY_S = 24 * 3600L

    /** The runs left of the day at [now]: the budget less [runs], never below 0. */
    fun left(db: Db, config: PhoneConfig, now: Instant): Int =
        maxOf(0L, config.provider(PROVIDER).budget - runs(db, now)).toInt()

    /** The yt-dlp runs the phone sent in the 24 hours before [now] (a run stamped exactly 24 hours before included). */
    fun runs(db: Db, now: Instant): Int =
        db.one("SELECT COUNT(*) FROM events WHERE provider = ? AND at >= ? AND decision IN ('ok', 'error', 'blocked')",
               PROVIDER, now.truncatedTo(ChronoUnit.SECONDS).minusSeconds(DAY_S).toString()) { it.long(0) }!!.toInt()
}
