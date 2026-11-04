package io.github.danielhp95.caracole.core.config

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyFloat
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.math.BigDecimal
import java.math.BigInteger

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
            PyJson.loads(Database.resource("caracole/config/config.json")).jsonObject
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
         * the library's name (null: none), `user_agent`, `providers`, `match` and `rank`, each field by its config.py
         * name.
         *
         * - A provider the phone knows takes its `enabled` (only one of [SWITCHABLE], as config.py lets only those be
         *   off), `lookup_delay`, `lookup_requests` and `lookup_per_hour`; its `budget` and `delay` stay config.py's,
         *   the phone doing no bulk work. A provider the phone doesn't know (a newer computer's) is passed over.
         * - `per_day` is the stricter of config.json's and the document's (null: no cap), never looser: caracole.toml
         *   can't set it, so the computer's is config.py's own, and a phone and a computer of other versions never
         *   lift each other's cap.
         * - Each value as config.py would hold it, or it keeps its default: a delay `[min, max]` of finite numbers with
         *   `0 <= min <= max` (`_delay`); a count a whole number of 0 or more (`_count`; one past an Int the most an
         *   Int holds, as many as any lookup sends); `[match]`'s and `[rank]`'s in their ranges (`_MATCH_RANGES`,
         *   `_RANK_RANGES`; `scored_sheets` an int), and a `review` above `accept` the defaults' `[match]` whole.
         *   [RankPolicy]'s `lineMatch` and `priorVotes` are Ints: a fraction there (`line_match = 82.5`, which
         *   caracole.toml may give) keeps the default.
         *
         * A record that isn't a JSON object (PyJson.loads's), the defaults whole.
         */
        fun read(db: Db): PhoneConfig {
            val text = db.kvGet(SETTINGS_KV) ?: return DEFAULTS
            val doc = runCatching { PyJson.loads(text) }.getOrNull() as? JsonObject ?: return DEFAULTS
            return over(DEFAULTS, doc)
        }

        /** [base] with the settings document [doc]'s values over it, as [read] lays them. */
        internal fun over(base: PhoneConfig, doc: JsonObject): PhoneConfig {
            val given = doc["providers"] as? JsonObject ?: JsonObject(emptyMap())
            val providers = LinkedHashMap(base.providers)
            for ((name, value) in given) {
                val p = value as? JsonObject ?: continue
                val was = base.providers[name] ?: continue
                providers[name] = was.copy(
                    enabled = if (name in SWITCHABLE) p.bool("enabled") ?: was.enabled else was.enabled,
                    lookupDelay = p.delay("lookup_delay") ?: was.lookupDelay,
                    lookupRequests = p.count("lookup_requests") ?: was.lookupRequests,
                    lookupPerHour = p.count("lookup_per_hour") ?: was.lookupPerHour,
                    perDay = stricter(was.perDay, p["per_day"]),
                )
            }
            val m = doc["match"] as? JsonObject ?: JsonObject(emptyMap())
            val r = doc["rank"] as? JsonObject ?: JsonObject(emptyMap())
            val match = MatchPolicy(
                accept = m.number("accept", 0.0, 100.0) ?: base.match.accept,
                margin = m.number("margin", 0.0, 100.0) ?: base.match.margin,
                review = m.number("review", 0.0, 100.0) ?: base.match.review,
                artistGate = m.number("artist_gate", 0.0, 100.0) ?: base.match.artistGate,
            )
            return PhoneConfig(
                providers = providers,
                userAgent = doc.text("user_agent") ?: base.userAgent,
                match = if (match.review > match.accept) base.match else match,
                rank = RankPolicy(
                    coverageThreshold = r.number("coverage_threshold", 0.0, 1.0) ?: base.rank.coverageThreshold,
                    lineMatch = r.whole("line_match", 0, 100, floats = true) ?: base.rank.lineMatch,
                    priorVotes = r.whole("prior_votes", 0, null, floats = true) ?: base.rank.priorVotes,
                    scoredSheets = r.whole("scored_sheets", 1, null, floats = false) ?: base.rank.scoredSheets,
                    labelPenalty = r.number("label_penalty", 0.0, null) ?: base.rank.labelPenalty,
                    variantBonus = r.number("variant_bonus", 0.0, null) ?: base.rank.variantBonus,
                ),
                libraryName = if ("name" in doc) doc.text("name") else base.libraryName,
            )
        }

        /** A JSON number's literal (never a boolean, a text or null), as PyJson.loads writes it. */
        private fun literal(e: JsonElement?): String? =
            (e as? JsonPrimitive)?.takeIf { it !is JsonNull && !it.isString }?.content
                ?.takeIf { it != "true" && it != "false" }

        /** Whether [literal] is an int's, `-?[0-9]+` (PyJson.loads writes a float with a point or an exponent). */
        private fun isInt(literal: String): Boolean {
            val digits = literal.removePrefix("-")
            return digits.isNotEmpty() && digits.all { it in '0'..'9' }
        }

        /** config._number(value, low, high, whole=False): a finite int or float from [low] up to [high]. */
        private fun number(e: JsonElement?, low: Double, high: Double?): Double? {
            val x = literal(e)?.let { PyFloat.parse(it) } ?: return null
            return x.takeIf { it.isFinite() && it >= low && (high == null || it <= high) }
        }

        private fun JsonObject.number(key: String, low: Double, high: Double?): Double? = number(this[key], low, high)

        /**
         * An Int of config.py's from [low] up to [high]: an int (`_count`, `_number(…, whole=True)`) or, where
         * config.py takes a float too ([floats], `_number(…, whole=False)`), a float that is a whole number; past an
         * Int, the most an Int holds.
         */
        private fun whole(e: JsonElement?, low: Long, high: Long?, floats: Boolean): Int? {
            val literal = literal(e) ?: return null
            val n = when {
                isInt(literal) -> BigInteger(literal)
                !floats -> return null
                else -> PyFloat.parse(literal)?.takeIf { it.isFinite() && it == Math.rint(it) }
                    ?.let { BigDecimal(it).toBigIntegerExact() } ?: return null
            }
            if (n < BigInteger.valueOf(low)) return null
            if (high != null && n > BigInteger.valueOf(high)) return null
            return n.min(BigInteger.valueOf(Int.MAX_VALUE.toLong())).toInt()
        }

        private fun JsonObject.whole(key: String, low: Long, high: Long?, floats: Boolean): Int? =
            whole(this[key], low, high, floats)

        /** config._count: an int of 0 or more. */
        private fun JsonObject.count(key: String): Int? = whole(this[key], 0, null, floats = false)

        /** config._delay: two finite numbers (never booleans) with `0 <= min <= max`. */
        private fun JsonObject.delay(key: String): Pair<Double, Double>? {
            val a = this[key] as? JsonArray ?: return null
            if (a.size != 2) return null
            val low = number(a[0], 0.0, null) ?: return null
            val high = number(a[1], low, null) ?: return null
            return low to high
        }

        /** The stricter of a provider's `per_day` and the document's: null is no cap; a value that is neither null nor
         * a count leaves [mine]. */
        private fun stricter(mine: Int?, given: JsonElement?): Int? {
            if (given == null || given is JsonNull) return mine
            val theirs = whole(given, 0, null, floats = false) ?: return mine
            return if (mine == null) theirs else minOf(mine, theirs)
        }

        private fun JsonObject.bool(key: String): Boolean? =
            (this[key] as? JsonPrimitive)?.takeIf { !it.isString && it !is JsonNull }?.content
                ?.let { if (it == "true") true else if (it == "false") false else null }

        private fun JsonObject.text(key: String): String? =
            (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** The computer's settings document (GET /api/peer/state's `settings`) kept as kv `phone:settings`. */
        fun take(db: Db, settings: JsonObject): Unit = TODO("lane crossing-phone")
    }
}
