package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.http.Transport
import java.io.File
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * A lookup's clients, `_common.make_client(..., interactive=True)` on the phone, each made at [cfg] (the phone's
 * settings as the lookup began, PhoneConfig.read): its run id `lookup:…`; its policy [Pace.lookupPolicy] (or the one
 * given), within the day's `per_day` ([Pace.withinTheDay]); its first request paced after the last one this side sent
 * ([Pace.pauseAfterLastRequest]); every request logged to `events` ([EventLog]) and, for one sent ([Pace.SENT]), kv
 * `http:last_request:<provider>` written as `f"{time.time():.3f}"` writes it; the user agent `cfg.userAgent`, the
 * computer's once a sync brought it; the cache under [cacheDir] (`<cacheDir>/http/<provider>/`, http.py's layout); the
 * transport [transport] gives for the provider. [pacing] is every clock, draw and pause, a test's to fix.
 */
class Clients(val cfg: PhoneConfig, val cacheDir: File, val transport: (provider: String) -> Transport,
              val pacing: Pacing) {
    /** [provider]'s client for the lookup [runId] (`lookup:` put before it when it has none), [onEvent] hearing each
     * event once it is logged, as make_client's `on_event`. */
    fun interactive(db: Db, provider: String, runId: String, policy: ProviderPolicy? = null,
                    onEvent: ((Event) -> Unit)? = null): PoliteClient {
        val run = if (runId.startsWith(Pace.LOOKUP_RUN)) runId else Pace.LOOKUP_RUN + runId
        val now = pacing.clock()
        val paced = Pace.withinTheDay(db, provider, policy ?: Pace.lookupPolicy(cfg, db, provider, now), now)
        Pace.pauseAfterLastRequest(db, provider, paced.delay, pacing.draws, pacing.sleep, pacing.wallSeconds)
        val log = EventLog(db, run, pacing.clock)
        val logged: (Event) -> Unit = { event ->
            log(event)
            if (event.decision in Pace.SENT) db.kvSet(Pace.LAST_SENT + provider, seconds(pacing.wallSeconds()))
            onEvent?.invoke(event)
        }
        return PoliteClient(provider, paced, cacheDir, cfg.userAgent, transport(provider), pacing.sleep, pacing.draws,
                            onEvent = logged, monotonic = pacing.monotonic, wallClock = pacing.clock)
    }

    companion object {
        /** `f"{x:.3f}"`: the exact double rounded half to even at the third decimal, as Python's formatting rounds
         * it (never String.format's, which rounds the shortest decimal half up: 1.0005 is 1.000, not 1.001). */
        internal fun seconds(x: Double): String = when {
            x.isNaN() -> "nan"
            x.isInfinite() -> if (x > 0) "inf" else "-inf"
            else -> (if (x < 0 || 1 / x < 0) "-" else "") +
                BigDecimal(Math.abs(x)).setScale(3, RoundingMode.HALF_EVEN).toPlainString()
        }
    }
}
