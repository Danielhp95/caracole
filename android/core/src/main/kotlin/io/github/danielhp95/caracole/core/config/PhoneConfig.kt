package io.github.danielhp95.caracole.core.config

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * The phone's settings: config.py's defaults (data/caracole/config/config.json, [DEFAULTS]) with what the computer
 * gave at the last sync laid over them (kv `phone:settings`, [SETTINGS_KV]: its providers' switches and lookup
 * settings, `[match]`, `[rank]`, its user agent and its library's name). The phone never does bulk work, so a
 * provider's `budget` and `delay` are config.py's alone.
 */
data class PhoneConfig(val providers: Map<String, ProviderPolicy>, val userAgent: String, val match: MatchPolicy,
                       val rank: RankPolicy, val libraryName: String?) {
    /** The provider's policy (a provider config.py doesn't name: no budget, no pause). */
    fun provider(name: String): ProviderPolicy = providers[name] ?: ProviderPolicy(budget = 0, delay = 0.0 to 0.0)

    companion object {
        const val SETTINGS_KV = "phone:settings"
        const val NO_BUDGET = Long.MAX_VALUE

        private val defaults: JsonObject by lazy {
            Json.parseToJsonElement(Database.resource("caracole/config/config.json")).jsonObject
        }

        /** config.py's defaults, as tests/test_conformance_config.py wrote them. */
        val DEFAULTS: PhoneConfig by lazy {
            fun pair(e: JsonElement) = e.jsonArray.let { it[0].jsonPrimitive.double to it[1].jsonPrimitive.double }
            val providers = defaults.getValue("providers").jsonObject.mapValues { (_, value) ->
                val p = value.jsonObject
                ProviderPolicy(
                    budget = p.getValue("budget").jsonPrimitive.long, delay = pair(p.getValue("delay")),
                    enabled = p.getValue("enabled").jsonPrimitive.boolean, lookupDelay = pair(p.getValue("lookup_delay")),
                    lookupRequests = p.getValue("lookup_requests").jsonPrimitive.int,
                    lookupPerHour = p.getValue("lookup_per_hour").jsonPrimitive.int,
                    perDay = p.getValue("per_day").let { if (it is JsonNull) null else it.jsonPrimitive.int },
                )
            }
            val m = defaults.getValue("match").jsonObject
            val r = defaults.getValue("rank").jsonObject
            PhoneConfig(
                providers = providers, userAgent = defaults.getValue("user_agent").jsonPrimitive.content,
                match = MatchPolicy(m.getValue("accept").jsonPrimitive.double, m.getValue("margin").jsonPrimitive.double,
                                    m.getValue("review").jsonPrimitive.double, m.getValue("artist_gate").jsonPrimitive.double),
                rank = RankPolicy(r.getValue("coverage_threshold").jsonPrimitive.double,
                                  r.getValue("line_match").jsonPrimitive.int, r.getValue("prior_votes").jsonPrimitive.int,
                                  r.getValue("scored_sheets").jsonPrimitive.int,
                                  r.getValue("label_penalty").jsonPrimitive.double,
                                  r.getValue("variant_bonus").jsonPrimitive.double),
                libraryName = null,
            )
        }

        /** config.SWITCHABLE: the providers that can be turned off. */
        val SWITCHABLE: Set<String> by lazy {
            (defaults.getValue("switchable") as JsonArray).map { it.jsonPrimitive.content }.toSet()
        }

        /** The phone's settings now: [DEFAULTS] with kv `phone:settings` laid over them. Neutral (the defaults alone)
         * until lane health-pace reads the record. */
        fun read(db: Db): PhoneConfig = DEFAULTS

        /** The computer's settings document (GET /api/peer/state's `settings`) kept as kv `phone:settings`, whole and
         * as db.kv_set_json writes a value, for [read] to lay over the defaults: a sync's agree stage takes it
         * (SyncEngine), each time replacing the last; a state with none leaves it as it was. */
        fun take(db: Db, settings: JsonObject): Unit = db.kvSetJson(SETTINGS_KV, settings)
    }
}
