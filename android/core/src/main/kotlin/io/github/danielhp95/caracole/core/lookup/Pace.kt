package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Strptime
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.py.PyFloat
import java.time.Duration
import java.time.Instant

/**
 * commands/_common.py's lookup pace on the phone, each count this side's own requests alone (the owner's choice of
 * 2026-11-03: two caracoles at one address may together send more than either one's limits), read from `events`:
 *
 * - [lookupRequestsUsed]: the requests every lookup of the last hour sent the provider (runs named `lookup:…`, or
 *   [run]'s, `at` ≥ an hour ago, both compared as SQLite compares text), and [lookupPolicy], a lookup's budget:
 *   `lookup_requests`, or what the hour's lookups left of `lookup_per_hour`, never below none; its delay
 *   `lookup_delay`;
 * - [requestsToday] since UTC midnight, every run's, and [withinTheDay]: no more than a provider's `per_day` leaves;
 * - [lastRequest]: kv `http:last_request:<provider>` (`float()` of its text, [PyFloat]), else the last sent request
 *   of `events`, to the second; and [pauseAfterLastRequest], the pause after it, never longer than the delay's
 *   longest.
 *
 * There is no lock, no ticket and no handoff on the phone: one job worker is its one writer. A request counts when its
 * decision is one of [SENT]. tests/conformance/vectors/pace/ holds it to Python's (tests/test_conformance_health.py).
 */
object Pace {
    const val LOOKUP_RUN = "lookup:"
    const val LAST_SENT = "http:last_request:"
    val SENT: Set<String> = linkedSetOf("ok", "not_modified", "blocked", "error")

    private val sent: Array<String> = SENT.toTypedArray()
    private const val IN_SENT = "decision IN (?, ?, ?, ?)"

    /** lookup_run_id: `lookup:` and the time to the second, so its requests count in the hour's. */
    fun lookupRunId(now: Instant): String = LOOKUP_RUN + Strptime.format(now)

    /** lookup_requests_used: every lookup's requests to [provider] of the hour before [now], [run]'s alone when
     * given (`lookup:lacuerda-search:`, LaCuerda's searches). */
    fun lookupRequestsUsed(db: Db, provider: String, now: Instant, run: String = LOOKUP_RUN): Int {
        val since = Strptime.format(now.minus(Duration.ofHours(1)))
        return db.one("SELECT COUNT(*) FROM events WHERE provider = ? AND run LIKE ? AND at >= ? AND $IN_SENT",
                      provider, "$run%", since, *sent) { it.long(0) }!!.toInt()
    }

    /** lookup_policy: [provider]'s lookup pace, its budget what this hour's lookups leave of it. */
    fun lookupPolicy(cfg: PhoneConfig, db: Db, provider: String, now: Instant): ProviderPolicy {
        val p = cfg.provider(provider)
        val used = lookupRequestsUsed(db, provider, now)
        return p.copy(budget = maxOf(0, minOf(p.lookupRequests, p.lookupPerHour - used)).toLong(), delay = p.lookupDelay)
    }

    /** requests_today: every request to [provider] since UTC midnight of [now]. */
    fun requestsToday(db: Db, provider: String, now: Instant): Int {
        val midnight = Strptime.format(now).substring(0, 10) + "T00:00:00Z"
        return db.one("SELECT COUNT(*) FROM events WHERE provider = ? AND at >= ? AND $IN_SENT",
                      provider, midnight, *sent) { it.long(0) }!!.toInt()
    }

    /** within_the_day: [policy] with no more requests than the UTC day leaves of its `per_day` (none: as it is). */
    fun withinTheDay(db: Db, provider: String, policy: ProviderPolicy, now: Instant): ProviderPolicy {
        val perDay = policy.perDay ?: return policy
        val left = maxOf(0, perDay - requestsToday(db, provider, now)).toLong()
        return if (policy.budget <= left) policy else policy.copy(budget = left)
    }

    /** _last_request: when this side last sent [provider] a request, in seconds since the epoch: kv
     * `http:last_request:<provider>` read as `float()` reads it, else the last sent request's `at` (strptime's; a
     * time it can't read is none). */
    fun lastRequest(db: Db, provider: String): Double? {
        db.kvGet(LAST_SENT + provider)?.let { PyFloat.parse(it) }?.let { return it }
        val at = db.one("SELECT max(at) FROM events WHERE provider = ? AND $IN_SENT", provider, *sent) { it.text(0) }
            ?: return null
        return try {
            Strptime.parse(at).epochSecond.toDouble()
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    /** _pause_after_last_request: the rest of a pause from [delay] after the provider's last request, slept; at most
     * `delay`'s longest, the clock set back or not. */
    fun pauseAfterLastRequest(db: Db, provider: String, delay: Pair<Double, Double>, draws: Draws,
                              sleep: (Double) -> Unit, wallSeconds: () -> Double) {
        val last = lastRequest(db, provider) ?: return
        val remaining = draws.uniform(delay.first, delay.second) - (wallSeconds() - last)
        if (remaining <= 0) return
        sleep(if (delay.second < remaining) delay.second else remaining)  // min(remaining, delay[1])
    }
}
