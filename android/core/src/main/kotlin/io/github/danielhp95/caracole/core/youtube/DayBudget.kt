package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The phone's day of yt-dlp runs (the phone-youtube design's §5.3): at most `PhoneConfig.provider("youtube").budget`
 * runs in any 24 hours, the computer's budget for one run used as the phone's day. Every run the phone sent in that
 * window counts, asked-now ones and the bench's among them, whatever its run id: `events` rows of provider `youtube`
 * whose decision is `ok`, `error` or `blocked`; a `budget` row ran nothing. A run frees its slot 24 hours after it.
 * Settings' YouTube row and the bench say the same count ([runs], the one function).
 *
 * A run is reserved before its gate opens, so that it counts whatever ends it (the process killed before its row is
 * written): the product's runner ([YtDlp]) with [reserve] (kv [RESERVED], a JSON list of UTC stamps, given back by
 * [release] for a run that never started), the debug bench with its own (kv [BENCH], DbLedger's). [runs] is the union
 * of the rows and the stamps: each stamp, oldest first, is the run of the first row not yet matched that came at or
 * after it within [MATCH_S] (the longest a run takes, its pauses and its timeout); a stamp no row follows is one run
 * more, a row no stamp names (one sent before reservations, or under none) one run.
 */
object DayBudget {
    private const val PROVIDER = "youtube"
    private const val DAY_S = 24 * 3600L

    /** The product's reservations: kv `youtube-runs`, the phone's own (OwnRecords), never synced. */
    const val RESERVED = "youtube-runs"

    /** The debug bench's (DbLedger.RUNS). */
    const val BENCH = "ytbench:runs"

    /** How long after its stamp a run's row may come: the download's timeout and a margin for its pauses. */
    val MATCH_S: Long by lazy { YouTubeData.read().number("download_timeout").toLong() + 120 }

    /** The runs left of the day at [now]: the budget less [runs], never below 0. */
    fun left(db: Db, config: PhoneConfig, now: Instant): Int =
        maxOf(0L, config.provider(PROVIDER).budget - runs(db, now)).toInt()

    /** The yt-dlp runs the phone sent in the 24 hours before [now] (a run stamped exactly 24 hours before included):
     * the rows and the reservations no row followed, as one set. */
    fun runs(db: Db, now: Instant): Int = counted(db, now).size

    /** When [least] runs are left of the day: [now] when they are; else the moment the run whose slot frees the last of
     * them leaves the day (24 hours and a second after it: one exactly 24 hours old still counts); null for a budget
     * under [least], which never leaves them. The automatic pass's next one after it stopped at fewer than 2 runs. */
    fun freesAt(db: Db, config: PhoneConfig, now: Instant, least: Int): Instant? {
        val budget = config.provider(PROVIDER).budget
        if (budget < least) return null
        val times = counted(db, now).map { Stamps.parse(it)?.let(Stamps::instant) ?: now }.sorted()
        val need = times.size - (budget - least)  // the runs that must leave the day
        if (need <= 0) return now
        return times[(need - 1).toInt()].plusSeconds(DAY_S + 1)
    }

    /** The times of the runs [runs] counts, as stored: each row's, and each reservation no row followed. */
    private fun counted(db: Db, now: Instant): List<String> {
        val since = stamp(now.minusSeconds(DAY_S))
        val rows = db.query("SELECT at FROM events WHERE provider = ? AND at >= ? " +
                                "AND decision IN ('ok', 'error', 'blocked') ORDER BY at", PROVIDER, since) { it.text(0)!! }
        val stamps = (stamps(db, BENCH) + stamps(db, RESERVED)).filter { it >= since }.sorted()
        val matched = BooleanArray(rows.size)
        val unmatched = ArrayList<String>()
        for (s in stamps) {
            val latest = stamp(Instant.parse(s).plusSeconds(MATCH_S))
            val i = rows.indices.firstOrNull { !matched[it] && rows[it] >= s && rows[it] <= latest }
            if (i == null) unmatched += s else matched[i] = true
        }
        return rows + unmatched
    }

    /** One write (the caller's): a run's reservation at [now], its stamp; those older than a day dropped. */
    fun reserve(db: Db, now: Instant): String {
        val stamp = stamp(now)
        val since = stamp(now.minusSeconds(DAY_S))
        write(db, stamps(db, RESERVED).filter { it >= since } + stamp)
        return stamp
    }

    /** One write: [stamp] given back (one of it), for a run that never started. */
    fun release(db: Db, stamp: String) {
        val kept = stamps(db, RESERVED).toMutableList()
        if (kept.remove(stamp)) write(db, kept)
    }

    private fun write(db: Db, stamps: List<String>) =
        db.kvSet(RESERVED, JsonArray(stamps.map(::JsonPrimitive)).toString())

    private fun stamps(db: Db, key: String): List<String> = db.kvGet(key)?.let { text ->
        (runCatching { PyJson.loads(text) }.getOrNull() as? JsonArray)?.mapNotNull {
            (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content
                ?.takeIf { c -> runCatching { Instant.parse(c) }.isSuccess }
        }
    }.orEmpty()

    private fun stamp(at: Instant): String = at.truncatedTo(ChronoUnit.SECONDS).toString()
}
