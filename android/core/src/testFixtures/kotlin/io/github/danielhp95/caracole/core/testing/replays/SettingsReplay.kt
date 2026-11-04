package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.nio.file.Files

/**
 * The computer's settings taken (tests/test_conformance_sync.py; the spec
 * docs/superpowers/specs/2026-11-03-politeness-crossing.md, "Settings"), each record on a database of its own:
 *
 * - vectors/sync/settings.jsonl: for each caracole.toml of Python's (`args[0]`), its settings document (`out`,
 *   politeness.settings_document) taken by PhoneConfig.take, kept as kv `phone:settings` as db.kv_set_json writes a
 *   value, and PhoneConfig.read then answering what config.py holds for that caracole.toml (`phone`: config.json's
 *   shape, its `switchable` aside, with `name`);
 * - vectors/sync/settings_take.jsonl: the take rule by rule, `args` `[kept, settings]` (kv `phone:settings` before, a
 *   document or null; the state's `settings`, null when it gives none, which the agree stage then takes nothing of),
 *   `out` `{kept, read}` (the record after, and what PhoneConfig.read answers then, in `phone`'s shape).
 *
 * Value for value: a number by its value, since Python writes `accept` 90 where the phone holds 90.0.
 */
object SettingsReplay : AreaReplay {
    override val area = "settings"

    const val VECTOR = "sync/settings.jsonl"
    const val TAKES = "sync/settings_take.jsonl"

    override fun replay(misses: Misses) {
        // waiting on crossing-computer (the vectors) and health-pace (PhoneConfig.read): Phase A's guard.
        if (!reads()) return
        withDb { db ->
            if (present(VECTOR)) documents(db, misses)
            if (present(TAKES)) takes(db, misses)
        }
    }

    private fun documents(db: Db, misses: Misses) {
        for (r in Corpus.records(VECTOR)) {
            val case = r.extra["case"]?.let(::text) ?: r.args.toString().take(80)
            val doc = r.out as? JsonObject
            if (doc == null) {
                misses.check(false) { "$case: no settings document (${r.out})" }
                continue
            }
            db.kvDelete(PhoneConfig.SETTINGS_KV)
            PhoneConfig.take(db, doc)
            val kept = db.kvGet(PhoneConfig.SETTINGS_KV)
            misses.check(kept == PyJson.dumps(doc)) { "$case: phone:settings = $kept, kv_set_json's ${PyJson.dumps(doc)}" }
            val got = shape(PhoneConfig.read(db))
            val want = r.extra["phone"]
            misses.check(want != null && same(got, want)) { "$case: PhoneConfig.read = $got, Python's $want" }
        }
    }

    private fun takes(db: Db, misses: Misses) {
        for (r in Corpus.records(TAKES)) {
            val case = r.extra["case"]?.let(::text) ?: r.args.toString().take(80)
            val before = r.args.getOrNull(0)
            val settings = r.args.getOrNull(1)
            val out = r.out as? JsonObject
            if (out == null || (before !is JsonObject && before !is JsonNull) ||
                (settings !is JsonObject && settings !is JsonNull)) {
                misses.check(false) { "$case: a record that can't be read (${r.args}, ${r.out})" }
                continue
            }
            db.kvDelete(PhoneConfig.SETTINGS_KV)
            if (before is JsonObject) db.kvSetJson(PhoneConfig.SETTINGS_KV, before)
            if (settings is JsonObject) PhoneConfig.take(db, settings)  // the agree stage: none given, none taken
            val kept = db.kvGetJson(PhoneConfig.SETTINGS_KV) ?: JsonNull
            val wantKept = out["kept"] ?: JsonNull
            misses.check(same(kept, wantKept)) { "$case: phone:settings = $kept, Python's $wantKept" }
            val got = shape(PhoneConfig.read(db))
            val want = out["read"]
            misses.check(want != null && same(got, want)) { "$case: PhoneConfig.read = $got, Python's $want" }
        }
    }

    /** Whether the vectors are there (lane crossing-computer writes them), each or [name]. */
    fun present(name: String? = null): Boolean =
        (name?.let(::listOf) ?: listOf(VECTOR, TAKES)).all { Corpus.open(it)?.use { true } ?: false }

    /** Whether PhoneConfig.read lays kv `phone:settings` over the defaults (lane health-pace's; the defaults alone
     * before it). */
    fun reads(): Boolean {
        var reads = false
        withDb { db ->
            db.kvSet(PhoneConfig.SETTINGS_KV, """{"user_agent": "caracole/0.1 (a probe)"}""")
            reads = PhoneConfig.read(db).userAgent == "caracole/0.1 (a probe)"
        }
        return reads
    }

    /** [cfg] in config.json's shape (tests/test_conformance_config.py's, its `switchable` aside), with `name`. */
    fun shape(cfg: PhoneConfig): JsonObject = JsonObject(linkedMapOf(
        "match" to obj("accept" to num(cfg.match.accept), "artist_gate" to num(cfg.match.artistGate),
                       "margin" to num(cfg.match.margin), "review" to num(cfg.match.review)),
        "name" to (cfg.libraryName?.let(::JsonPrimitive) ?: JsonNull),
        "providers" to JsonObject(cfg.providers.mapValues { (_, p) -> policy(p) }),
        "rank" to obj("coverage_threshold" to num(cfg.rank.coverageThreshold),
                      "label_penalty" to num(cfg.rank.labelPenalty), "line_match" to num(cfg.rank.lineMatch),
                      "prior_votes" to num(cfg.rank.priorVotes), "scored_sheets" to num(cfg.rank.scoredSheets),
                      "variant_bonus" to num(cfg.rank.variantBonus)),
        "user_agent" to JsonPrimitive(cfg.userAgent),
    ))

    private fun policy(p: ProviderPolicy): JsonObject = obj(
        "budget" to num(p.budget), "delay" to pair(p.delay), "enabled" to JsonPrimitive(p.enabled),
        "lookup_delay" to pair(p.lookupDelay), "lookup_per_hour" to num(p.lookupPerHour),
        "lookup_requests" to num(p.lookupRequests), "per_day" to (p.perDay?.let(::num) ?: JsonNull),
    )

    /** Two JSON values alike as Python compares them once read: objects by their members (in any order), arrays item
     * for item, numbers by their value (90 is 90.0), everything else as written. */
    fun same(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.all { (k, v) -> same(v, b.getValue(k)) }
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
        a is JsonPrimitive && b is JsonPrimitive && isNumber(a) && isNumber(b) ->
            a.content.toBigDecimal().compareTo(b.content.toBigDecimal()) == 0
        else -> a == b
    }

    private fun isNumber(p: JsonPrimitive) = p !is JsonNull && !p.isString && p.content != "true" && p.content != "false"

    private fun num(n: Number): JsonPrimitive = JsonPrimitive(n)

    private fun pair(p: Pair<Double, Double>) = JsonArray(listOf(JsonPrimitive(p.first), JsonPrimitive(p.second)))

    private fun obj(vararg members: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*members))

    private fun withDb(block: (Db) -> Unit) {
        val dir = Files.createTempDirectory("caracole-settings").toFile()
        try {
            TestDb.fresh(dir).use { database -> database.writeBlocking(block) }
        } finally {
            dir.deleteRecursively()
        }
    }
}
