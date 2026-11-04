package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.py.PyFormat
import java.io.File

/**
 * A lookup's clients, `_common.make_client(..., interactive=True)` on the phone, each made at [cfg] (the phone's
 * settings as the lookup began, PhoneConfig.read): its run id `lookup:…`; its policy [Pace.lookupPolicy] (or the one
 * given), within the day's `per_day` ([Pace.withinTheDay]); its first request paced after the last one this side sent
 * ([Pace.pauseAfterLastRequest]: one draw from [Pacing.draws] when this side sent the provider anything, before the
 * client's own, which pace its requests after the first); every request logged to `events` ([EventLog]) and, for one
 * sent ([Pace.SENT]), kv `http:last_request:<provider>` written as `f"{time.time():.3f}"` writes it
 * ([PyFormat.fixed]); the user agent `cfg.userAgent`, the computer's once a sync brought it; the cache under
 * [cacheDir] (`<cacheDir>/http/<provider>/`, http.py's layout); the transport [transport] gives for the provider.
 * [pacing] is every clock, draw and pause, a test's to fix.
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
            if (event.decision in Pace.SENT) {
                db.kvSet(Pace.LAST_SENT + provider, PyFormat.fixed(pacing.wallSeconds(), 3))
            }
            onEvent?.invoke(event)
        }
        return PoliteClient(provider, paced, cacheDir, cfg.userAgent, transport(provider), pacing.sleep, pacing.draws,
                            onEvent = logged, monotonic = pacing.monotonic, wallClock = pacing.clock)
    }
}
