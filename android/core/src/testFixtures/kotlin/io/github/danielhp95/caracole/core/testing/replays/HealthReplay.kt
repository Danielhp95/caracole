package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.Event
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
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.time.ZoneOffset
import java.util.Locale

/**
 * core.health's cooldowns and events (vectors/health/, tests/test_conformance_health.py): every record answered by
 * Health and EventLog as Python answered it, over a database of its own that holds the record's events and kv alone.
 */
object HealthReplay : AreaReplay {
    override val area = "health"

    override fun replay(misses: Misses) = PoliteDb.with { db ->
        state(db, misses)
        answered(db, misses)
        events(db, misses)
    }

    private fun state(db: Db, misses: Misses) {
        for (r in Corpus.records("health/state.jsonl")) {
            val provider = text(r.kw.getValue("provider"))
            val kv = r.kw.getValue("kv").let { if (it is JsonNull) null else text(it) }
            PoliteDb.fresh(db, JsonArray(emptyList()), kv?.let { mapOf("provider:$provider" to it) } ?: emptyMap())
            val steps = r.kw.getValue("steps").jsonArray
            val want = r.out!!.jsonArray
            val case = r.extra["case"]?.jsonPrimitive?.content
            for ((i, step) in steps.withIndex()) {
                val s = step.jsonArray
                val op = text(s[0])
                val now = s[1].let { if (it is JsonNull) null else Instant.parse(text(it)) }
                val expected = want.getOrNull(i)?.jsonObject ?: break
                val answer = try {
                    when (op) {
                        "block" -> stateJson(Health.recordBlock(db, provider, now!!, text(s[2])))
                        "ok" -> stateJson(Health.recordOk(db, provider, now!!))
                        "error" -> stateJson(Health.recordError(db, provider, now!!, text(s[2])))
                        "cooling" -> mapOf("cooling" to JsonPrimitive(Health.isCooling(db, provider, now!!)))
                        "state" -> stateJson(Health.state(db, provider))
                        else -> throw AssertionError("no step $op")
                    }
                } catch (e: AssertionError) {
                    throw e
                } catch (e: Exception) {
                    val raised = expected["err"]?.jsonPrimitive?.content
                    val stands = RAISES[raised]
                    misses.check(stands != null && stands.isInstance(e)) {
                        "$case: step $i ($op) threw $e, Python answered $expected"
                    }
                    break
                }
                val got = JsonObject(answer + ("kv" to (db.kvGet("provider:$provider")?.let { JsonPrimitive(it) } ?: JsonNull)))
                misses.check(got == shownAsKotlin(expected)) { "$case: step $i ($op at $now) = $got, Python's $expected" }
                if (expected["err"] != null) break
            }
        }
    }

    /** What stands on the phone for each exception Python raised (Health's KDoc): a Kotlin exception of another class
     * where Python raised is a miss, as is one where it raised nothing. */
    private val RAISES: Map<String, Class<out Exception>> = mapOf(
        "OverflowError" to ArithmeticException::class.java,
        "ValueError" to IllegalArgumentException::class.java,
        "TypeError" to IllegalArgumentException::class.java,
        "JSONDecodeError" to PyJson.DecodeError::class.java,
        "AttributeError" to IllegalStateException::class.java,
    )

    /** Python's answer as ProviderState holds it: a `last_error` that isn't text its JSON text (the kv keeps it as it
     * was, and is compared byte for byte). */
    private fun shownAsKotlin(expected: JsonObject): JsonObject {
        val state = expected["state"] as? JsonObject ?: return expected
        val error = state["last_error"] ?: return expected
        if (error is JsonNull || (error is JsonPrimitive && error.isString)) return expected
        return JsonObject(expected + ("state" to JsonObject(state + ("last_error" to JsonPrimitive(PyJson.dumps(error))))))
    }

    private fun stateJson(s: ProviderState): Map<String, JsonElement> = mapOf("state" to JsonObject(mapOf(
        "provider" to JsonPrimitive(s.provider), "strikes" to JsonPrimitive(s.strikes),
        "cooldown_until" to PoliteDb.iso(s.cooldownUntil), "last_ok" to PoliteDb.iso(s.lastOk),
        "last_error" to (s.lastError?.let { JsonPrimitive(it) } ?: JsonNull), "last_error_at" to PoliteDb.iso(s.lastErrorAt),
    )))

    private fun answered(db: Db, misses: Misses) {
        for (r in Corpus.records("health/answered.jsonl")) {
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray)
            misses.expect(r) {
                Health.answeredAny(db, text(r.kw.getValue("run")), text(r.kw.getValue("provider")),
                                   r.kw.getValue("requests").jsonPrimitive.int)
            }
        }
    }

    private fun events(db: Db, misses: Misses) {
        for (r in Corpus.records("health/events.jsonl")) {
            PoliteDb.fresh(db, JsonArray(emptyList()))
            val times = r.kw.getValue("clock").jsonArray.map { Instant.parse(text(it)) }.iterator()
            val log = EventLog(db, text(r.kw.getValue("run"))) { times.next() }
            for (e in r.kw.getValue("events").jsonArray) {
                val f = e.jsonArray
                log(Event(text(f[0]), text(f[1]), f[2].intOrNull(), text(f[3]), f[4].let { if (it is JsonNull) null else text(it) }))
            }
            misses.expect(r) { PoliteDb.events(db) }
        }
    }
}

/** A replay's database (health/, pace/): one a vector, migrated once, holding a record's events and kv alone. */
internal object PoliteDb {
    fun with(block: (Db) -> Unit) {
        val dir: File = Files.createTempDirectory("caracole-politeness").toFile()
        try {
            TestDb.fresh(dir).use { database -> database.writeBlocking(block) }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** No event and no kv record of politeness but [events] (`[run, at, provider, url, status, decision, message]`,
     * an eighth element the row's count) and [kv]. */
    fun fresh(db: Db, events: JsonArray, kv: Map<String, String> = emptyMap()) {
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM kv WHERE key LIKE 'provider:%' OR key LIKE 'http:last_request:%'")
        for (e in events) {
            val f = e.jsonArray
            val times = if (f.size > 7) f[7].jsonPrimitive.int else 1
            repeat(times) {
                db.execute(
                    "INSERT INTO events (run, at, provider, url, status, decision, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    text(f[0]), text(f[1]), text(f[2]), f[3].let { if (it is JsonNull) null else text(it) },
                    f[4].intOrNull(), text(f[5]), f[6].let { if (it is JsonNull) null else text(it) },
                )
            }
        }
        for ((key, value) in kv) db.kvSet(key, value)
    }

    /** Every row of `events`, oldest first, as `[run, at, provider, url, status, decision, message]`. */
    fun events(db: Db): JsonArray = JsonArray(db.query(
        "SELECT run, at, provider, url, status, decision, message FROM events ORDER BY id",
    ) { row ->
        JsonArray(listOf(
            JsonPrimitive(row.text(0)), JsonPrimitive(row.text(1)), JsonPrimitive(row.text(2)),
            row.text(3)?.let { JsonPrimitive(it) } ?: JsonNull, row.long(4)?.let { JsonPrimitive(it) } ?: JsonNull,
            JsonPrimitive(row.text(5)), row.text(6)?.let { JsonPrimitive(it) } ?: JsonNull,
        ))
    })

    /** datetime.isoformat() of a UTC time: microseconds only when there are some. */
    fun iso(t: Instant?): JsonElement {
        if (t == null) return JsonNull
        val d = t.atOffset(ZoneOffset.UTC)
        val micros = d.nano / 1000
        val text = String.format(Locale.ROOT, "%04d-%02d-%02dT%02d:%02d:%02d", d.year, d.monthValue, d.dayOfMonth,
                                 d.hour, d.minute, d.second) +
            (if (micros != 0) String.format(Locale.ROOT, ".%06d", micros) else "") + "+00:00"
        return JsonPrimitive(text)
    }
}
