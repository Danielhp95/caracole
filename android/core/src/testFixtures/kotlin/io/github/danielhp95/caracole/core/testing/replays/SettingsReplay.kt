package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.sync.PeerState
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.Units
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
 * docs/superpowers/specs/2026-11-03-politeness-crossing.md, "Settings"), each record on a database of its own, and
 * each take the agree stage's own: a state document of the record's `settings` read by PeerState.read (as
 * PeerClient.state reads the computer's), then SyncEngine.takeSettings.
 *
 * - vectors/sync/settings.jsonl: for each caracole.toml of Python's (`args[0]`), its settings document (`out`,
 *   politeness.settings_document) taken, kv `phone:settings` then holding that document whole, and PhoneConfig.read
 *   answering what config.py holds for that caracole.toml (`phone`: config.json's shape, its `switchable` aside, with
 *   `name`);
 * - vectors/sync/settings_take.jsonl: the take rule by rule, `args` `[kept, settings]` (kv `phone:settings` before, a
 *   document or null; the state's `settings`, null when it gives none), `out` `{kept, read}` (the record after, and
 *   what PhoneConfig.read answers then, in `phone`'s shape).
 *
 * Value for value: a number by its value, since Python writes `accept` 90 where the phone holds 90.0. The record's
 * text is PyJson.dumps's, which the `canonical` area's vectors hold to Python's json.dumps. A missing vector fails.
 */
object SettingsReplay : AreaReplay {
    override val area = "settings"

    const val VECTOR = "sync/settings.jsonl"
    const val TAKES = "sync/settings_take.jsonl"

    override fun replay(misses: Misses) {
        withDb { db ->
            documents(db, misses)
            takes(db, misses)
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
            take(db, doc)
            val kept = db.kvGetJson(PhoneConfig.SETTINGS_KV) ?: JsonNull
            misses.check(same(kept, doc)) { "$case: phone:settings = $kept, the document $doc" }
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
            take(db, settings)
            val kept = db.kvGetJson(PhoneConfig.SETTINGS_KV) ?: JsonNull
            val wantKept = out["kept"] ?: JsonNull
            misses.check(same(kept, wantKept)) { "$case: phone:settings = $kept, Python's $wantKept" }
            val got = shape(PhoneConfig.read(db))
            val want = out["read"]
            misses.check(want != null && same(got, want)) { "$case: PhoneConfig.read = $got, Python's $want" }
        }
    }

    /** The agree stage's take of a state whose `settings` is [settings] (JsonNull: a state that gives none). */
    private fun take(db: Db, settings: JsonElement) = SyncEngine.takeSettings(db, PeerState.read(state(settings)))

    /** A state document as GET /api/peer/state answers one, with no unit and [settings] as its `settings`. */
    private fun state(settings: JsonElement): JsonObject = obj(
        "format" to JsonPrimitive(Units.FORMAT), "server" to JsonPrimitive("0123456789abcdef"),
        "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"),
        "now" to JsonPrimitive("2026-11-03T12:00:00Z"), "indexes" to JsonObject(emptyMap()),
        "units" to JsonObject(emptyMap()), "base" to JsonNull, "settings" to settings,
        "token" to JsonPrimitive("computer-token-1"),
    )

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
