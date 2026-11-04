package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import java.time.Instant
import kotlin.math.ceil

/**
 * get.py's `_Lookup._ask` on the phone, the envelope every stage of a lookup and every lookup command asks through:
 *
 * - a provider that can't be asked now says why and sends nothing ([usable]: turned off, [blocked] or [failed]
 *   earlier in this lookup, each [Asked.Off] with get.py's words; cooling down after a block, [Asked.Cooling]);
 * - else its client, made once a lookup through [Clients.interactive] at [runId] (`lookup:` and the time, or a
 *   command's own run, `lookup:lacuerda-search:…`), runs the work: its value [Asked.Done];
 * - a block cools the provider down ([Health.recordBlock], [Asked.Blocked] with the cooldown it began), alerts once
 *   ([Alerts.blocked]: on the phone a lookup alerts, where the computer's sends none, since the phone has no nightly
 *   run to tell) and ends its part of the lookup;
 * - a spent budget is [Asked.Spent]: the hour's lookups spent when the client's budget was below `lookup_requests`,
 *   or what follows the sheet held to what [LookupWords.SHEETS_SHARE] leaves ([afterTheSheet]);
 * - a provider's error is counted ([Health.recordError]), [Asked.Failed], and ends its part too.
 *
 * None of them is a miss. A song whose Ultimate Guitar part a cooldown, a block, a spent budget or an error cut short
 * is owed a fetch ([owedSong]: get.py's `_owed`, `ug_dirty` set on a matched song). Anything else the work throws (a
 * [io.github.danielhp95.caracole.core.library.SharedFolder], a bug) is the caller's. [db] is the lookup's, in
 * autocommit: each event, block and record commits as it happens. [make] stands in for [Clients.interactive], a
 * test's; [config] is the phone's settings the lookup began with.
 */
class InteractiveAsk(val clients: Clients, val db: Db, val runId: String, val now: Instant,
                     val alerts: Alerts = Alerts.NONE, val config: PhoneConfig = clients.cfg,
                     private val make: ((provider: String, policy: ProviderPolicy?) -> Client)? = null) : Asking {
    /** The providers that blocked caracole in this lookup, each asked nothing more. */
    val blocked: MutableSet<String> = linkedSetOf()

    /** The providers that failed in this lookup, each asked nothing more. */
    val failed: MutableSet<String> = linkedSetOf()

    /** The providers whose client what follows the sheet holds to [LookupWords.SHEETS_SHARE]. */
    val keptForSheets: MutableSet<String> = linkedSetOf()

    /** The song a cut-short Ultimate Guitar part owes a fetch (the lookup's, once found); null: none. */
    var owedSong: Long? = null

    private val made = LinkedHashMap<String, Client>()

    /** Why [provider] can't be asked now ([Asked.Off] or [Asked.Cooling]), or null when it can. */
    fun usable(provider: String): Asked<Nothing>? = when {
        !config.provider(provider).enabled -> Asked.Off(LookupWords.off(provider))
        provider in blocked -> Asked.Off(LookupWords.blockedEarlier(provider))
        provider in failed -> Asked.Off(LookupWords.failedEarlier(provider))
        Health.isCooling(db, provider, now) -> Asked.Cooling(Health.state(db, provider).cooldownUntil)
        else -> null
    }

    /** [provider]'s client for this lookup, made the first time it is asked for ([policy] its own, else the lookup
     * pace's), given [policy] after. */
    fun client(provider: String, policy: ProviderPolicy? = null): Client {
        made[provider]?.let { client ->
            if (policy != null) client.policy = policy
            return client
        }
        val client = make?.invoke(provider, policy) ?: clients.interactive(db, provider, runId, policy)
        made[provider] = client
        return client
    }

    override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> {
        usable(provider)?.let {
            owed(provider)
            return it
        }
        val client = client(provider, policy)
        return try {
            Asked.Done(work(client))
        } catch (e: ProviderBlocked) {
            owed(provider)
            val state = Health.recordBlock(db, e.provider, now, e.message.orEmpty())
            if (blocked.add(e.provider)) alerts.blocked(e.provider, state.cooldownUntil, e.message.orEmpty())
            Asked.Blocked(e, state)
        } catch (e: BudgetExhausted) {
            owed(provider)
            val p = config.provider(e.provider)
            Asked.Spent(hour = e.provider !in keptForSheets && client.policy.budget < p.lookupRequests,
                        keptForSheets = e.provider in keptForSheets)
        } catch (e: ProviderError) {
            owed(provider)
            Health.recordError(db, e.provider, now, e.message.orEmpty())
            failed.add(e.provider)
            Asked.Failed(e)
        }
    }

    /**
     * get.py's `after_the_sheet`: what follows the sheet, which the nightly run would do anyway, asked within what
     * leaves [LookupWords.SHEETS_SHARE] of the hour's lookup requests to the site for sheets (`left`: the hour's
     * `lookup_per_hour`, less its share rounded up, less the requests every lookup of the hour sent it), so that an
     * evening of songs looked up on the spot keeps getting them: none left and the site askable, [Asked.Spent] kept
     * for sheets with nothing sent; else the client's budget held to what it sent and `left`, when that is less.
     */
    val afterTheSheet: Asking = AfterTheSheet()

    /** [afterTheSheet]'s kind, which a test tells apart from the plain envelope. */
    inner class AfterTheSheet internal constructor() : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> {
            val left = left(provider)
            if (left <= 0 && usable(provider) == null) return Asked.Spent(hour = false, keptForSheets = true)
            return this@InteractiveAsk.ask(provider, policy) { client ->
                if (client.requestsMade + left < client.policy.budget) {  // no stage after it asks this site for a sheet
                    client.policy = client.policy.copy(budget = (client.requestsMade + left).toLong())
                    keptForSheets.add(provider)
                }
                work(client)
            }
        }

        override val requests: Map<String, Int> get() = this@InteractiveAsk.requests
    }

    /** What [LookupWords.SHEETS_SHARE] leaves of the hour's lookup requests to [provider] for what follows a sheet. */
    fun left(provider: String): Int {
        val p = config.provider(provider)
        val share = ceil(p.lookupPerHour * LookupWords.SHEETS_SHARE).toInt()
        return p.lookupPerHour - share - Pace.lookupRequestsUsed(db, provider, clients.pacing.clock())
    }

    override val requests: Map<String, Int> get() = made.mapValues { it.value.requestsMade }

    /** get.py's closing: each provider that answered this lookup ([Health.answeredAny] of its own events) and never
     * blocked it had a good run ([Health.recordOk]). */
    fun recordAnswers() {
        for ((provider, client) in made) {
            if (provider !in blocked && Health.answeredAny(db, runId(), provider, client.requestsMade)) {
                Health.recordOk(db, provider, now)
            }
        }
    }

    /** Every client closed; [requests] still says what each sent. */
    fun close() {
        for (client in made.values) (client as? AutoCloseable)?.close()
    }

    /** The run its clients log their events under, `lookup:` put before it as [Clients.interactive] puts it. */
    private fun runId(): String = if (runId.startsWith(Pace.LOOKUP_RUN)) runId else Pace.LOOKUP_RUN + runId

    /** get.py's `_owed`: a song whose Ultimate Guitar part was cut short is marked to fetch, as `caracole fetch
     * --song` marks it, when it is matched or pinned and not owed already. */
    private fun owed(provider: String) {
        if (provider != "ug") return
        val song = owedSong?.let { Songs.byId(db, it) } ?: return
        if (song.matchDecision in setOf("accept", "pinned") && !song.ugDirty) {
            Versions.updateSong(db, song.id, mapOf("ug_dirty" to true), Stamps.of(clients.pacing.clock()))
        }
    }
}
