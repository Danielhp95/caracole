package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.share.ShareLinks.Linked
import io.github.danielhp95.caracole.core.share.ShareLinks.Read
import java.io.File
import java.time.Instant

/**
 * A shared link's service asked once ([ShareLinks]), as a lookup asks a site, and nothing looser (AGENTS.md,
 * Politeness, "A shared link read by asking its service once"):
 *
 * - **Off**: a service turned off (`[providers.spotify] enabled = false` in the computer's caracole.toml, which the
 *   phone took at a sync) is asked nothing, its cache read neither ([off]).
 * - **The cache first** ([cached]): every answer it accepted is kept forever (`<cacheDir>/http/<provider>/`), so a
 *   link shared again, or the page loaded again, sends nothing and writes nothing; a cached answer that won't parse
 *   is asked for once more, past the cache.
 * - **Else one ask** ([ask]), inside the caller's write: the lookup's envelope ([InteractiveAsk], run `lookup:share:`
 *   and the time, so its requests count in the hour's `lookup_per_hour` with every lookup's) with a client at the
 *   lookup pace (`lookup_delay`, and the pause after this side's last request to it), its budget the least of
 *   `lookup_requests`, what the hour leaves and what the link needs ([Linked.requests]: 1, a short link's hop 2);
 *   caracole's own user agent, robots.txt's rules, a block cooling the provider down and alerting once, an error
 *   counted ([io.github.danielhp95.caracole.core.health.Health]), each request an `events` row. What it came to is
 *   one line ([words]): never a miss, never "this link names no song" for an error.
 */
object ShareAsk {
    /** The run a share's requests are logged under: a lookup's, so the hour's `lookup_per_hour` counts them. */
    const val RUN = "lookup:share:"

    fun runId(now: Instant): String = RUN + Stamps.of(now)

    /** Why [linked]'s service can't be asked at all ([PhoneConfig.provider]'s `enabled`), or null. */
    fun off(linked: Linked, cfg: PhoneConfig): Read? {
        val p = linked.service.provider
        if (cfg.provider(p).enabled) return null
        return Read.NotRead(linked.service, "reading ${linked.service.name}'s links is off ([providers.$p] enabled = " +
                                "false in the computer's caracole.toml, which the phone took at its last sync)")
    }

    /** What the cache alone says of [linked], with no request and no write; null when a request is needed (an answer
     * not cached, or one that won't parse). */
    fun cached(linked: Linked, cacheDir: File): Read? {
        val answers = CachedAnswers(linked.service.provider, cacheDir)
        return try {
            ShareLinks.answer(linked) { url, accept -> answers.cached(url, accept) ?: throw NotCached() }
        } catch (e: NotCached) {
            null
        } catch (e: ShareParseError) {
            null
        }
    }

    private class NotCached : Exception()

    /** [linked]'s service asked once, inside a write on [db] (autocommit: each event and record commits as it
     * happens), through [clients] at [cfg]'s settings; a block alerts [alerts] once. */
    fun ask(db: Db, linked: Linked, clients: Clients, alerts: Alerts, cfg: PhoneConfig, now: Instant): Read {
        off(linked, cfg)?.let { return it }
        if (linked is ShareLinks.NoSong) return ShareLinks.answer(linked) { _, _ -> error("no request for it") }
        val provider = linked.service.provider
        val ask = InteractiveAsk(clients, db, runId(now), now, alerts, cfg)
        try {
            val pace = Pace.lookupPolicy(cfg, db, provider, clients.pacing.clock())
            val policy = pace.copy(budget = minOf(pace.budget, linked.requests.toLong()))
            val asked = ask.ask(provider, policy) { client ->
                var fromCache = false
                try {
                    ShareLinks.answer(linked) { url, accept ->
                        client.get(url, accept = accept).also { if (it.fromCache) fromCache = true }
                    }
                } catch (e: ShareParseError) {
                    if (!fromCache) throw e
                    ShareLinks.answer(linked) { url, accept -> client.get(url, cache = false, accept = accept) }
                }
            }
            ask.recordAnswers()
            val hour = Pace.lookupRequestsUsed(db, provider, clients.pacing.clock()) >= cfg.provider(provider).lookupPerHour
            return words(linked, asked, cfg, hourSpent = hour)
        } finally {
            ask.close()
        }
    }

    /** What asking came to, in one line: the service's own answer, or why it gave none ([hourSpent]: every lookup of
     * the hour has sent the service its `lookup_per_hour`, else a spent budget is the share's own). */
    fun words(linked: Linked, asked: Asked<Read>, cfg: PhoneConfig, hourSpent: Boolean): Read {
        val service = linked.service
        val name = service.name
        val p = cfg.provider(service.provider)
        return when (asked) {
            is Asked.Done -> asked.value
            is Asked.Off -> off(linked, cfg) ?: Read.NotRead(service, asked.why)
            is Asked.Cooling -> Read.NotRead(service, "$name blocked caracole earlier, and caracole asks it nothing " +
                                                 "until ${LookupWords.until(asked.until)}")
            is Asked.Blocked -> Read.NotRead(service, "$name blocked caracole (${what(asked.error)}), and caracole asks " +
                                                 "it nothing more until ${LookupWords.until(asked.state.cooldownUntil)}")
            is Asked.Spent -> Read.NotRead(service, if (hourSpent) {
                "this hour's ${p.lookupPerHour} requests to $name are spent"
            } else {
                val n = minOf(p.lookupRequests, linked.requests)
                "the ${if (n == 1) "one request" else "$n requests"} to $name a share of this link may send " +
                    (if (n == 1) "is" else "are") + " spent"
            })
            is Asked.Failed -> Read.NotRead(service, "asking $name failed (${what(asked.error)})")
        }
    }

    /** A provider's error in words: what it said, else its status. */
    private fun what(e: ProviderError): String = e.msg?.takeIf { it.isNotEmpty() }
        ?: e.status?.let { "HTTP $it" } ?: (e.message ?: e.provider)
}
