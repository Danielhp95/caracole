package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import java.time.Instant

/** commands/_common.py's lookup pace on the phone: each count its own side's requests alone. */
object Pace {
    const val LOOKUP_RUN = "lookup:"
    const val LAST_SENT = "http:last_request:"
    val SENT: Set<String> = linkedSetOf("ok", "not_modified", "blocked", "error")

    fun lookupRunId(now: Instant): String = TODO("lane health-pace")
    fun lookupRequestsUsed(db: Db, provider: String, now: Instant, run: String = LOOKUP_RUN): Int = TODO("lane health-pace")
    fun lookupPolicy(cfg: PhoneConfig, db: Db, provider: String, now: Instant): ProviderPolicy = TODO("lane health-pace")
    fun requestsToday(db: Db, provider: String, now: Instant): Int = TODO("lane health-pace")
    fun withinTheDay(db: Db, provider: String, policy: ProviderPolicy, now: Instant): ProviderPolicy = TODO("lane health-pace")
    fun lastRequest(db: Db, provider: String): Double? = TODO("lane health-pace")
    fun pauseAfterLastRequest(db: Db, provider: String, delay: Pair<Double, Double>, draws: Draws,
                              sleep: (Double) -> Unit, wallSeconds: () -> Double): Unit = TODO("lane health-pace")
}
