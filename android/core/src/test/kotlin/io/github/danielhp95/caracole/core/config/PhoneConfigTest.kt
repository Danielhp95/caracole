package io.github.danielhp95.caracole.core.config

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertSame

/** The phone's defaults are config.py's, as data/caracole/config/config.json holds them, and kv `phone:settings`, the
 * computer's settings document a sync took, lies over them. */
class PhoneConfigTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    @Test fun theDefaultsAreConfigPys() {
        val ug = PhoneConfig.DEFAULTS.provider("ug")
        assertEquals(60, ug.budget)
        assertEquals(2.5 to 5.0, ug.delay)
        assertEquals(0.125 to 0.375, ug.lookupDelay)
        assertEquals(PhoneConfig.NO_BUDGET, PhoneConfig.DEFAULTS.provider("azlyrics").budget)
        assertEquals(900, PhoneConfig.DEFAULTS.provider("megalobiz").perDay)
        assertEquals(MatchPolicy(), PhoneConfig.DEFAULTS.match)
        assertEquals(RankPolicy(), PhoneConfig.DEFAULTS.rank)
        assertEquals("caracole/0.1 (personal tab library)", PhoneConfig.DEFAULTS.userAgent)
        assertEquals(setOf("azlyrics", "gametabs", "gtptabs", "harptabs", "megalobiz", "musescore", "youtube", "ytimg"),
                     PhoneConfig.SWITCHABLE)
    }

    @Test fun theDefaultsAreConfigJsonsEveryProviderFieldForField() {
        val json = Json.parseToJsonElement(Database.resource("caracole/config/config.json")).jsonObject
        val providers = json.getValue("providers").jsonObject
        assertEquals(providers.keys.toList(), PhoneConfig.DEFAULTS.providers.keys.toList())
        for ((name, value) in providers) {
            val p = value.jsonObject
            fun pair(key: String) = p.getValue(key).jsonArray.let { it[0].jsonPrimitive.double to it[1].jsonPrimitive.double }
            assertEquals(ProviderPolicy(
                budget = p.getValue("budget").jsonPrimitive.long, delay = pair("delay"),
                enabled = p.getValue("enabled").jsonPrimitive.boolean, lookupDelay = pair("lookup_delay"),
                lookupRequests = p.getValue("lookup_requests").jsonPrimitive.int,
                lookupPerHour = p.getValue("lookup_per_hour").jsonPrimitive.int,
                perDay = p.getValue("per_day").let { if (it is JsonNull) null else it.jsonPrimitive.int },
            ), PhoneConfig.DEFAULTS.provider(name), name)
        }
        assertNull(PhoneConfig.DEFAULTS.libraryName)
    }

    @Test fun withNoSettingsTheyAreTheDefaults() = db { db ->
        assertSame(PhoneConfig.DEFAULTS, PhoneConfig.read(db))
        db.kvSet(PhoneConfig.SETTINGS_KV, "not json")
        assertSame(PhoneConfig.DEFAULTS, PhoneConfig.read(db))
        db.kvSet(PhoneConfig.SETTINGS_KV, "[1, 2]")
        assertSame(PhoneConfig.DEFAULTS, PhoneConfig.read(db))
    }

    @Test fun theComputersSettingsLieOverTheDefaults() = db { db ->
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"name": "Tabs", "user_agent": "caracole/0.1 (the computer's)",
            "providers": {"ug": {"enabled": false, "lookup_delay": [0.5, 1.5], "lookup_requests": 4,
                                 "lookup_per_hour": 30, "per_day": 100},
                          "megalobiz": {"enabled": false, "lookup_delay": [0, 0], "lookup_requests": 6,
                                        "lookup_per_hour": 60, "per_day": null},
                          "newsite": {"enabled": true, "lookup_delay": [1, 2], "lookup_requests": 2,
                                      "lookup_per_hour": 10, "per_day": null}},
            "match": {"accept": 92, "margin": 8.5, "review": 70, "artist_gate": 88},
            "rank": {"coverage_threshold": 0.75, "line_match": 80, "prior_votes": 12, "scored_sheets": 4,
                     "label_penalty": 0.25, "variant_bonus": 0.5}}""")
        val cfg = PhoneConfig.read(db)
        assertEquals("Tabs", cfg.libraryName)
        assertEquals("caracole/0.1 (the computer's)", cfg.userAgent)
        // ug isn't switchable: config.py never lets it be off. Its bulk budget and delay stay config.py's.
        // A cap only tightens: ug's none takes the document's 100, megalobiz's 900 survives its null.
        assertEquals(PhoneConfig.DEFAULTS.provider("ug").copy(lookupDelay = 0.5 to 1.5, lookupRequests = 4,
                                                              lookupPerHour = 30, perDay = 100), cfg.provider("ug"))
        assertEquals(PhoneConfig.DEFAULTS.provider("megalobiz").copy(enabled = false, lookupDelay = 0.0 to 0.0),
                     cfg.provider("megalobiz"))
        assertEquals(900, cfg.provider("megalobiz").perDay)
        // A newer computer's provider is passed over.
        assertEquals(PhoneConfig.DEFAULTS.providers.keys, cfg.providers.keys)
        assertEquals(PhoneConfig.DEFAULTS.provider("lrclib"), cfg.provider("lrclib"))
        assertEquals(MatchPolicy(accept = 92.0, margin = 8.5, review = 70.0, artistGate = 88.0), cfg.match)
        assertEquals(RankPolicy(0.75, 80, 12, 4, 0.25, 0.5), cfg.rank)
    }

    @Test fun aMemberMissingOrOfAnotherKindKeepsItsDefault() = db { db ->
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"name": null, "user_agent": 5,
            "providers": {"lrclib": {"lookup_requests": "many", "lookup_delay": [1], "per_day": 3.5}, "ug": []},
            "match": {"accept": "high"}, "rank": []}""")
        val cfg = PhoneConfig.read(db)
        assertNull(cfg.libraryName)
        assertEquals(PhoneConfig.DEFAULTS.copy(libraryName = null), cfg)
    }

    @Test fun aDaysCapIsNeverLiftedNorLoosened() = db { db ->
        for (given in listOf("null", "901", "1e3", "-1", "\"800\"", "true")) {
            db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"megalobiz": {"per_day": $given}}}""")
            assertEquals(900, PhoneConfig.read(db).provider("megalobiz").perDay, given)
        }
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"megalobiz": {"per_day": 899}}}""")
        assertEquals(899, PhoneConfig.read(db).provider("megalobiz").perDay)
    }

    @Test fun aValueConfigPyWouldRefuseKeepsItsDefault() = db { db ->
        val ug = PhoneConfig.DEFAULTS.provider("ug")
        for (delay in listOf("[0.5, 0.1]", "[-1, -1]", "[-0.5, 1]", "[0, Infinity]", "[NaN, 1]", "[true, 1]",
                             "[\"0\", 1]", "[0, 1, 2]")) {
            db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"ug": {"lookup_delay": $delay}}}""")
            assertEquals(ug.lookupDelay, PhoneConfig.read(db).provider("ug").lookupDelay, delay)
        }
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"ug": {"lookup_delay": [0, 0]}}}""")
        assertEquals(0.0 to 0.0, PhoneConfig.read(db).provider("ug").lookupDelay)
        for (count in listOf("-1", "6.0", "true", "\"6\"", "null")) {
            db.kvSet(PhoneConfig.SETTINGS_KV,
                     """{"providers": {"ug": {"lookup_requests": $count, "lookup_per_hour": $count}}}""")
            val got = PhoneConfig.read(db).provider("ug")
            assertEquals(ug.lookupRequests to ug.lookupPerHour, got.lookupRequests to got.lookupPerHour, count)
        }
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"ug": {"lookup_per_hour": 1000000000000}}}""")
        assertEquals(Int.MAX_VALUE, PhoneConfig.read(db).provider("ug").lookupPerHour)  // config.py takes it
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"match": {"accept": 101, "margin": -1, "review": NaN},
            "rank": {"coverage_threshold": 1.5, "line_match": 82.5, "prior_votes": -2, "scored_sheets": 0,
                     "label_penalty": -0.1, "variant_bonus": Infinity}}""")
        assertEquals(PhoneConfig.DEFAULTS.match to PhoneConfig.DEFAULTS.rank,
                     PhoneConfig.read(db).let { it.match to it.rank })
        // A whole number config.py holds as a float is the Int it is; scored_sheets is an int alone.
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"rank": {"line_match": 80.0, "prior_votes": 2, "scored_sheets": 4.0}}""")
        assertEquals(RankPolicy(lineMatch = 80, priorVotes = 2), PhoneConfig.read(db).rank)
        // review above accept: config.py refuses that [match], so the phone keeps its own whole.
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"match": {"accept": 70, "margin": 5, "review": 75, "artist_gate": 80}}""")
        assertEquals(PhoneConfig.DEFAULTS.match, PhoneConfig.read(db).match)
    }
}
