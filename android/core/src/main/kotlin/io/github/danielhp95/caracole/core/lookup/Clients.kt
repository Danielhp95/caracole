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
        return built(Writes.of(db), provider, run, { d, now -> policy ?: Pace.lookupPolicy(cfg, d, provider, now) }, onEvent)
    }

    /** [provider]'s client under the run [runId] as it is, at the provider's own policy (its `budget` and `delay`,
     * within the day), as `make_client` makes bulk work's: what the owner asked for now that the computer asks so too
     * (a pasted video's thumbnail, youtube_search.py's, provider `ytimg`). Its database is reached through [writes],
     * a write a touch (the day's count and the last request's pause read before it, each event and its
     * `http:last_request:` after its request), so that no write is held while a request goes. */
    fun named(writes: Writes, provider: String, runId: String, onEvent: ((Event) -> Unit)? = null): PoliteClient =
        built(writes, provider, runId, { _, _ -> cfg.provider(provider) }, onEvent)

    /** [provider]'s client for bulk work under the run [run] as it is (never a `lookup:` one): the provider's own
     * policy, its `budget` and `delay`, within the day's `per_day`, every event logged and its `http:last_request:`
     * written, as `make_client` makes the nightly run's; over [db], the caller's (a lookup's stage holds its write). An
     * automatic YouTube job's lyrics stage asks through it (the design's §5.3), so its requests count in no hour's
     * lookups. */
    fun bulk(db: Db, provider: String, run: String, onEvent: ((Event) -> Unit)? = null): PoliteClient {
        require(!run.startsWith(Pace.LOOKUP_RUN)) { "a bulk run is no lookup's: $run" }
        return named(Writes.of(db), provider, run, onEvent)
    }

    /** The one builder: the policy within the day, the pause after the last request this side sent (read in a touch,
     * slept after it), every event logged and, for one sent, kv `http:last_request:<provider>` written. */
    private fun built(writes: Writes, provider: String, run: String, policy: (Db, java.time.Instant) -> ProviderPolicy,
                      onEvent: ((Event) -> Unit)?): PoliteClient {
        val now = pacing.clock()
        var owed = 0.0
        val paced = writes.use { db ->
            Pace.withinTheDay(db, provider, policy(db, now), now).also {
                Pace.pauseAfterLastRequest(db, provider, it.delay, pacing.draws, { seconds -> owed = seconds },
                                           pacing.wallSeconds)
            }
        }
        if (owed > 0) pacing.sleep(owed)
        val logged: (Event) -> Unit = { event ->
            writes.use { db ->
                EventLog(db, run, pacing.clock)(event)
                if (event.decision in Pace.SENT) {
                    db.kvSet(Pace.LAST_SENT + provider, PyFormat.fixed(pacing.wallSeconds(), 3))
                }
            }
            onEvent?.invoke(event)
        }
        return PoliteClient(provider, paced, cacheDir, cfg.userAgent, transport(provider), pacing.sleep, pacing.draws,
                            onEvent = logged, monotonic = pacing.monotonic, wallClock = pacing.clock)
    }

    /** How a client reaches the database: [use] runs its block with it, as one write. */
    interface Writes {
        fun <T> use(block: (Db) -> T): T

        companion object {
            /** [db] itself, for a caller that holds its write the whole time (a lookup's stage). */
            fun of(db: Db): Writes = object : Writes {
                override fun <T> use(block: (Db) -> T): T = block(db)
            }
        }
    }
}
