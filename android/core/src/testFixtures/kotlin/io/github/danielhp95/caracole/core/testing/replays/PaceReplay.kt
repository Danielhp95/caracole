package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.time.Instant

/**
 * The lookup pace (vectors/pace/, tests/test_conformance_health.py): every record answered by core.lookup.Pace as
 * commands/_common.py answered it, over a database of its own that holds the record's events and kv alone; a pause
 * for the draw the record gives (`a + (b - a) * u`) and its wall clock.
 */
object PaceReplay : AreaReplay {
    override val area = "pace"

    override fun replay(misses: Misses) = PoliteDb.with { db ->
        for (r in Corpus.records("pace/run_id.jsonl")) misses.expect(r) { Pace.lookupRunId(Instant.parse(text(r.args[0]))) }
        counts(db, misses)
        policies(db, misses)
        lastRequests(db, misses)
        pauses(db, misses)
    }

    private fun counts(db: Db, misses: Misses) {
        var loaded: JsonElement? = null
        for (r in Corpus.records("pace/counts.jsonl")) {
            val events = r.kw.getValue("events").jsonArray
            if (events != loaded) {
                PoliteDb.fresh(db, events)
                loaded = events
            }
            val provider = text(r.kw.getValue("provider"))
            val now = Instant.parse(text(r.kw.getValue("now")))
            when (r.fn) {
                "caracole.commands._common.lookup_requests_used" -> misses.expect(r) {
                    r.kw["run"]?.let { Pace.lookupRequestsUsed(db, provider, now, text(it)) }
                        ?: Pace.lookupRequestsUsed(db, provider, now)
                }
                "caracole.commands._common.requests_today" -> misses.expect(r) { Pace.requestsToday(db, provider, now) }
                else -> misses.check(false) { "pace/counts.jsonl: no function ${r.fn}" }
            }
        }
    }

    private fun policies(db: Db, misses: Misses) {
        for (r in Corpus.records("pace/policy.jsonl")) {
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray)
            val overrides = r.kw.getValue("providers").jsonObject
            val cfg = PhoneConfig.DEFAULTS.copy(providers = PhoneConfig.DEFAULTS.providers.mapValues { (name, p) ->
                overrides[name]?.jsonObject?.let { fields(p, it) } ?: p
            })
            val provider = text(r.kw.getValue("provider"))
            val now = Instant.parse(text(r.kw.getValue("now")))
            val case = r.extra["case"]?.jsonPrimitive?.content
            val lookup = Pace.lookupPolicy(cfg, db, provider, now)
            val got = mapOf(
                "lookup_policy" to lookup,
                "within_the_day" to Pace.withinTheDay(db, provider, lookup, now),
                "bulk_within_the_day" to Pace.withinTheDay(db, provider, cfg.provider(provider), now),
            )
            val want = r.out!!.jsonObject
            for ((member, policy) in got) {
                val expected = fields(ProviderPolicy(budget = -1, delay = -1.0 to -1.0), want.getValue(member).jsonObject)
                misses.check(policy == expected) { "$case: $member = $policy, Python's $expected" }
            }
        }
    }

    /** [p] with a record's fields over it (config.py's names). */
    private fun fields(p: ProviderPolicy, f: JsonObject): ProviderPolicy {
        fun pair(e: JsonElement) = e.jsonArray.let { double(it[0]) to double(it[1]) }
        return ProviderPolicy(
            budget = f["budget"]?.jsonPrimitive?.long ?: p.budget,
            delay = f["delay"]?.let(::pair) ?: p.delay,
            enabled = f["enabled"]?.jsonPrimitive?.boolean ?: p.enabled,
            lookupDelay = f["lookup_delay"]?.let(::pair) ?: p.lookupDelay,
            lookupRequests = f["lookup_requests"]?.jsonPrimitive?.int ?: p.lookupRequests,
            lookupPerHour = f["lookup_per_hour"]?.jsonPrimitive?.int ?: p.lookupPerHour,
            perDay = if ("per_day" in f) f.getValue("per_day").intOrNull() else p.perDay,
        )
    }

    private fun lastRequests(db: Db, misses: Misses) {
        for (r in Corpus.records("pace/last_request.jsonl")) {
            val provider = text(r.kw.getValue("provider"))
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray, kv(r.kw, provider))
            val got = Pace.lastRequest(db, provider)
            val want = r.out.takeUnless { it == null || it is JsonNull }?.let(::double)
            misses.check(same(got, want)) { "${r.extra["case"]}: last request $got, Python's $want" }
        }
    }

    private fun pauses(db: Db, misses: Misses) {
        for (r in Corpus.records("pace/pause.jsonl")) {
            val provider = text(r.kw.getValue("provider"))
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray, kv(r.kw, provider))
            val delay = r.kw.getValue("delay").jsonArray.let { double(it[0]) to double(it[1]) }
            val u = double(r.kw.getValue("u"))
            val wall = double(r.kw.getValue("wall"))
            val slept = ArrayList<Double>()
            Pace.pauseAfterLastRequest(db, provider, delay, Draws { a, b -> a + (b - a) * u }, { slept += it }, { wall })
            val want = r.out!!.jsonArray.map(::double)
            misses.check(slept.size == want.size && slept.indices.all { same(slept[it], want[it]) }) {
                "${r.extra["case"]}: slept $slept, Python $want"
            }
        }
    }

    private fun kv(kw: JsonObject, provider: String): Map<String, String> =
        kw.getValue("kv").let { if (it is JsonNull) emptyMap() else mapOf("${Pace.LAST_SENT}$provider" to text(it)) }

    /** The same double, NaN the same as NaN; or both none. */
    private fun same(a: Double?, b: Double?): Boolean =
        if (a == null || b == null) a == b else (a.isNaN() && b.isNaN()) || a == b
}
