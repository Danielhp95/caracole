package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Event
import java.time.Instant

/** health.py's ProviderState: a provider's strikes, cooldown and last answers, kv `provider:<name>`. */
data class ProviderState(val provider: String, val strikes: Int = 0, val cooldownUntil: Instant? = null,
                         val lastOk: Instant? = null, val lastError: String? = null, val lastErrorAt: Instant? = null)

/** health.py: cooldowns after a block (24 h × 2^(k−1) + 2 h after the k-th in a row), each side's own. */
object Health {
    fun state(db: Db, provider: String): ProviderState = TODO("lane health-pace")
    fun recordBlock(db: Db, provider: String, now: Instant, message: String): ProviderState = TODO("lane health-pace")
    fun recordOk(db: Db, provider: String, now: Instant): ProviderState = TODO("lane health-pace")
    fun recordError(db: Db, provider: String, now: Instant, message: String): ProviderState = TODO("lane health-pace")
    fun isCooling(db: Db, provider: String, now: Instant): Boolean = TODO("lane health-pace")

    /** Whether the run's requests to the provider got any answer: more requests than errors and blocks logged. */
    fun answeredAny(db: Db, runId: String, provider: String, requests: Int): Boolean = TODO("lane health-pace")
}

/** health.py's EventLog: each request's `events` row, and kv `http:last_request:<provider>`. */
class EventLog(val db: Db, val runId: String, val clock: () -> Instant) : (Event) -> Unit {
    override fun invoke(event: Event): Unit = TODO("lane health-pace")
}
