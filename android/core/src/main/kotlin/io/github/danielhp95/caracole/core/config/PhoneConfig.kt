package io.github.danielhp95.caracole.core.config

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
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

        /**
         * The phone's settings now: [DEFAULTS] with kv `phone:settings` laid over them, the computer's settings
         * document as a sync took it (docs/superpowers/specs/2026-11-03-politeness-crossing.md, "Settings"): `name`
         * the library's name (null: none), `user_agent`, `providers` (each one's `enabled`, `lookup_delay`,
         * `lookup_requests`, `lookup_per_hour` and `per_day` over its defaults; `budget` and `delay` stay config.py's,
         * the phone doing no bulk work; `enabled` only for a provider of [SWITCHABLE], as config.py lets only those be
         * off; a provider config.py doesn't name with no budget and no pause beneath what it gives), `match` and
         * `rank`, each field by its config.py name. A member that is missing or not of its field's kind keeps the
         * default; a record that isn't a JSON object, the defaults whole.
         */
        fun read(db: Db): PhoneConfig {
            val text = db.kvGet(SETTINGS_KV) ?: return DEFAULTS
            val doc = runCatching { Json.parseToJsonElement(text) }.getOrNull() as? JsonObject ?: return DEFAULTS
            return over(DEFAULTS, doc)
        }

        /** [base] with the settings document [doc]'s values over it. */
        internal fun over(base: PhoneConfig, doc: JsonObject): PhoneConfig {
            val given = doc["providers"] as? JsonObject ?: JsonObject(emptyMap())
            val providers = LinkedHashMap(base.providers)
            for ((name, value) in given) {
                val p = value as? JsonObject ?: continue
                val was = base.providers[name] ?: ProviderPolicy(budget = 0, delay = 0.0 to 0.0)
                providers[name] = was.copy(
                    enabled = if (name in SWITCHABLE) p.bool("enabled") ?: was.enabled else was.enabled,
                    lookupDelay = p.pair("lookup_delay") ?: was.lookupDelay,
                    lookupRequests = p.int("lookup_requests") ?: was.lookupRequests,
                    lookupPerHour = p.int("lookup_per_hour") ?: was.lookupPerHour,
                    perDay = when {
                        "per_day" !in p -> was.perDay
                        p["per_day"] is JsonNull -> null
                        else -> p.int("per_day") ?: was.perDay
                    },
                )
            }
            val m = doc["match"] as? JsonObject ?: JsonObject(emptyMap())
            val r = doc["rank"] as? JsonObject ?: JsonObject(emptyMap())
            return PhoneConfig(
                providers = providers,
                userAgent = doc.text("user_agent") ?: base.userAgent,
                match = MatchPolicy(
                    accept = m.double("accept") ?: base.match.accept, margin = m.double("margin") ?: base.match.margin,
                    review = m.double("review") ?: base.match.review,
                    artistGate = m.double("artist_gate") ?: base.match.artistGate,
                ),
                rank = RankPolicy(
                    coverageThreshold = r.double("coverage_threshold") ?: base.rank.coverageThreshold,
                    lineMatch = r.int("line_match") ?: base.rank.lineMatch,
                    priorVotes = r.int("prior_votes") ?: base.rank.priorVotes,
                    scoredSheets = r.int("scored_sheets") ?: base.rank.scoredSheets,
                    labelPenalty = r.double("label_penalty") ?: base.rank.labelPenalty,
                    variantBonus = r.double("variant_bonus") ?: base.rank.variantBonus,
                ),
                libraryName = if ("name" in doc) doc.text("name") else base.libraryName,
            )
        }

        private fun JsonObject.number(key: String): JsonPrimitive? =
            (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull && !it.isString && it.content != "true" && it.content != "false" }

        private fun JsonObject.double(key: String): Double? = number(key)?.doubleOrNull

        private fun JsonObject.int(key: String): Int? = number(key)?.content?.toIntOrNull()

        private fun JsonObject.bool(key: String): Boolean? =
            (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull

        private fun JsonObject.text(key: String): String? =
            (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

        private fun JsonObject.pair(key: String): Pair<Double, Double>? {
            val a = this[key] as? JsonArray ?: return null
            if (a.size != 2) return null
            val low = (a[0] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull ?: return null
            val high = (a[1] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull ?: return null
            return low to high
        }

        /** The computer's settings document (GET /api/peer/state's `settings`) kept as kv `phone:settings`. */
        fun take(db: Db, settings: JsonObject): Unit = TODO("lane crossing-phone")
    }
}
