package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.py.Py
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit

/** health.py's ProviderState: a provider's strikes, cooldown and last answers, kv `provider:<name>`. */
data class ProviderState(val provider: String, val strikes: Int = 0, val cooldownUntil: Instant? = null,
                         val lastOk: Instant? = null, val lastError: String? = null, val lastErrorAt: Instant? = null)

/**
 * health.py on the phone: a provider's cooldown after a block, 24 h × 2^(k−1) + 2 h after the k-th in a row, until a
 * lookup that met no block resets it; each caracole's own (the owner's choice of 2026-11-03: nothing of it crosses
 * at a sync). The state is kv `provider:<name>`, written as db.kv_set_json writes it (`{"strikes": 1,
 * "cooldown_until": "2026-10-19T05:30:00Z", "last_ok": null, "last_error": "403", "last_error_at": "…"}`, each time
 * [Strptime.format]'s) and read as `get_state` reads it: a record that is null, `0`, `false`, `""`, `[]` or `{}` none;
 * `strikes` as `int()` takes it (a number truncated, a text of digits, a boolean); a time a text `strptime` reads, or
 * none where it is empty, null, `0`, `false`, `[]` or `{}`; anything else what Python raises (an exception here too).
 * A `last_error` that isn't text reads as its JSON (Python keeps the value as it is).
 *
 * tests/conformance/vectors/health/ holds it to Python's (tests/test_conformance_health.py).
 */
object Health {
    private val BASE: Duration = Duration.ofHours(24)
    private val MARGIN: Duration = Duration.ofHours(2)
    private const val DAY_MICROS = 86_400_000_000L

    /** datetime.max, 9999-12-31T23:59:59.999999: a cooldown past it is Python's OverflowError. */
    private val LAST: Instant = Instant.parse("9999-12-31T23:59:59.999999Z")

    private fun key(provider: String) = "provider:$provider"

    /** get_state. */
    fun state(db: Db, provider: String): ProviderState {
        val raw = db.kvGet(key(provider))?.let { record(it) } ?: JsonObject(emptyMap())
        return ProviderState(
            provider = provider,
            strikes = raw["strikes"].let { if (it == null) 0 else pyInt(it) },
            cooldownUntil = time(raw["cooldown_until"]),
            lastOk = time(raw["last_ok"]),
            lastError = raw["last_error"].let { e ->
                when {
                    e == null || e is JsonNull -> null
                    e is JsonPrimitive && e.isString -> e.content
                    else -> e.toString()
                }
            },
            lastErrorAt = time(raw["last_error_at"]),
        )
    }

    /**
     * record_block: a cooldown for a lookup (or a job) that began at [now], 24 h × 2^(strikes − 1) + 2 h. One still
     * running at [now] stays as it is, with its strikes: one block is one strike.
     */
    fun recordBlock(db: Db, provider: String, now: Instant, message: String): ProviderState {
        val s = state(db, provider)
        if (s.cooldownUntil != null && now < s.cooldownUntil) return s
        val strikes = s.strikes + 1
        return save(db, s.copy(strikes = strikes, cooldownUntil = cooldownAfter(now, strikes), lastError = message,
                               lastErrorAt = now))
    }

    /** record_ok: a lookup that began at [now] met no block: no cooldown and no strike, unless one runs at [now]. */
    fun recordOk(db: Db, provider: String, now: Instant): ProviderState {
        val s = state(db, provider)
        if (s.cooldownUntil != null && now < s.cooldownUntil) return s
        return save(db, s.copy(strikes = 0, cooldownUntil = null, lastOk = now))
    }

    /** record_error: an error that is no block, remembered; it starts no cooldown. */
    fun recordError(db: Db, provider: String, now: Instant, message: String): ProviderState =
        save(db, state(db, provider).copy(lastError = message, lastErrorAt = now))

    fun isCooling(db: Db, provider: String, now: Instant): Boolean {
        val until = state(db, provider).cooldownUntil
        return until != null && now < until
    }

    /** Whether the run's requests to the provider got any answer: more requests than errors and blocks logged. */
    fun answeredAny(db: Db, runId: String, provider: String, requests: Int): Boolean {
        val failed = db.one(
            "SELECT COUNT(*) FROM events WHERE run = ? AND provider = ? AND decision IN ('error', 'blocked')",
            runId, provider,
        ) { it.long(0) } ?: 0L
        return requests > failed
    }

    private fun save(db: Db, s: ProviderState): ProviderState {
        fun stamp(t: Instant?): JsonElement = if (t == null) JsonNull else JsonPrimitive(Strptime.format(t))
        db.kvSetJson(key(s.provider), JsonObject(linkedMapOf(
            "strikes" to JsonPrimitive(s.strikes),
            "cooldown_until" to stamp(s.cooldownUntil),
            "last_ok" to stamp(s.lastOk),
            "last_error" to (s.lastError?.let { JsonPrimitive(it) } ?: JsonNull),
            "last_error_at" to stamp(s.lastErrorAt),
        )))
        return s
    }

    /**
     * `now + COOLDOWN_BASE * (2 ** (strikes - 1)) + COOLDOWN_MARGIN`: a power of two of days, or below one strike a
     * fraction of a day in microseconds rounded half to even (timedelta times a float); past timedelta's 999999999
     * days or datetime's year 9999 an [ArithmeticException], Python's OverflowError.
     */
    private fun cooldownAfter(now: Instant, strikes: Int): Instant {
        val e = strikes - 1
        val base = when {
            e >= 30 -> throw ArithmeticException("days=${BigInteger.ONE.shiftLeft(e)}; must have magnitude <= 999999999")
            e >= 0 -> BASE.multipliedBy(1L shl e)
            else -> Duration.of(halfEven(DAY_MICROS, -e.toLong()), ChronoUnit.MICROS)
        }
        val until = now.plus(base).plus(MARGIN)
        if (until > LAST) throw ArithmeticException("date value out of range")
        return until
    }

    /** [x] / 2^[k], rounded half to even. */
    private fun halfEven(x: Long, k: Long): Long {
        if (k >= 62) return 0
        val q = x shr k.toInt()
        val r = x - (q shl k.toInt())
        val half = 1L shl (k.toInt() - 1)
        return if (r > half || (r == half && q % 2 == 1L)) q + 1 else q
    }

    // --- reading the record as Python does --------------------------------------------------------------------------

    /** `kv_get_json(…) or {}`: the record, an object; a falsy value none; anything else Python's AttributeError. */
    private fun record(text: String): JsonObject? {
        val value = Json.parseToJsonElement(text)
        if (falsy(value)) return null
        return value as? JsonObject ?: throw IllegalStateException("${value::class.simpleName} has no attribute 'get'")
    }

    private fun falsy(v: JsonElement): Boolean = when (v) {
        is JsonNull -> true
        is JsonObject -> v.isEmpty()
        is JsonArray -> v.isEmpty()
        is JsonPrimitive -> if (v.isString) v.content.isEmpty() else v.content == "false" ||
            (v.content != "true" && v.content.toDouble() == 0.0)
    }

    /** `_parse(value)`: none for a falsy value, a text strptime reads, else Python's TypeError. */
    private fun time(v: JsonElement?): Instant? {
        if (v == null || falsy(v)) return null
        if (v is JsonPrimitive && v.isString) return Strptime.parse(v.content)
        throw IllegalArgumentException("strptime() argument 1 must be str, not $v")
    }

    /** `int(value)` of a JSON value: a boolean 1 or 0, a number truncated toward zero, a text of digits. */
    private fun pyInt(v: JsonElement): Int {
        if (v !is JsonPrimitive || v is JsonNull) throw IllegalArgumentException("int() argument must be a number, not $v")
        if (v.isString) return intOfText(v.content)
        return when (v.content) {
            "true" -> 1
            "false" -> 0
            else -> {
                val literal = v.content
                if (literal.none { it == '.' || it == 'e' || it == 'E' }) BigInteger(literal).intValueExact()
                else {
                    val x = literal.toDouble()
                    if (x.isNaN() || x.isInfinite()) throw ArithmeticException("cannot convert float $x to integer")
                    BigDecimal(x).setScale(0, RoundingMode.DOWN).intValueExact()
                }
            }
        }
    }

    /** int(text): spaces around, a sign, decimal digits of any script with an underscore between two. */
    private fun intOfText(text: String): Int {
        val cps = Py.codePoints(Py.strip(text))
        var i = 0
        var negative = false
        if (i < cps.size && (cps[i] == '+'.code || cps[i] == '-'.code)) negative = cps[i++] == '-'.code
        if (i == cps.size) throw IllegalArgumentException("invalid literal for int(): $text")
        var n = BigInteger.ZERO
        var previousDigit = false
        while (i < cps.size) {
            val cp = cps[i++]
            if (cp == '_'.code) {
                if (!previousDigit || i == cps.size) throw IllegalArgumentException("invalid literal for int(): $text")
                previousDigit = false
                continue
            }
            val d = Strptime.decimal(cp)
            if (d < 0) throw IllegalArgumentException("invalid literal for int(): $text")
            n = n.multiply(BigInteger.TEN).add(BigInteger.valueOf(d.toLong()))
            previousDigit = true
        }
        return (if (negative) n.negate() else n).intValueExact()
    }
}

/**
 * health.py's EventLog: each request's row of `events`, `(run, at, provider, url, status, decision, message)`, `at`
 * the clock's time to the second. It writes nothing else: kv `http:last_request:<provider>` is the lookup's client's,
 * as `_common.make_client` writes it beside its EventLog ([io.github.danielhp95.caracole.core.lookup.Clients]).
 */
class EventLog(val db: Db, val runId: String, val clock: () -> Instant) : (Event) -> Unit {
    override fun invoke(event: Event) {
        db.execute(
            "INSERT INTO events (run, at, provider, url, status, decision, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
            runId, Strptime.format(clock()), event.provider, event.url, event.status, event.decision, event.message,
        )
    }
}
