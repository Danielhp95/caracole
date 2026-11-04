package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyInt
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

/**
 * health.py's ProviderState: a provider's strikes, cooldown and last answers, kv `provider:<name>`. [strikes] is
 * Python's int, of any size; [lastError] the text the record holds (one that isn't text, its JSON as json.dumps
 * writes it: Health writes it back as it was read).
 */
data class ProviderState(val provider: String, val strikes: BigInteger = BigInteger.ZERO,
                         val cooldownUntil: Instant? = null, val lastOk: Instant? = null,
                         val lastError: String? = null, val lastErrorAt: Instant? = null)

/**
 * health.py on the phone: a provider's cooldown after a block, 24 h × 2^(k−1) + 2 h after the k-th in a row, until a
 * lookup that met no block resets it; each caracole's own (the owner's choice of 2026-11-03: nothing of it crosses
 * at a sync). The state is kv `provider:<name>`, written as db.kv_set_json writes it (`{"strikes": 1,
 * "cooldown_until": "2026-10-19T05:30:00Z", "last_ok": null, "last_error": "403", "last_error_at": "…"}`, each time
 * [Strptime.format]'s) and read as `get_state` reads it ([PyJson.loads]): a record that is null, `0`, `false`, `""`,
 * `[]` or `{}` none; `strikes` as `int()` takes it (a number truncated, a text of digits, [PyInt]'s, a boolean); a
 * time a text `strptime` reads, or none where it is empty, null, `0`, `false`, `[]` or `{}`; `last_error` as it is,
 * kept for the next write. Anything else raises what stands for Python's exception: OverflowError an
 * [ArithmeticException], ValueError and TypeError an [IllegalArgumentException] (json.loads's JSONDecodeError its
 * [PyJson.DecodeError]), AttributeError an [IllegalStateException].
 *
 * tests/conformance/vectors/health/ holds it to Python's (tests/test_conformance_health.py).
 */
object Health {
    private val BASE: Duration = Duration.ofHours(24)
    private val MARGIN: Duration = Duration.ofHours(2)
    private const val DAY_MICROS = 86_400_000_000L

    /** datetime.max, 9999-12-31T23:59:59.999999: a cooldown past it is Python's OverflowError. */
    private val LAST: Instant = Instant.parse("9999-12-31T23:59:59.999999Z")

    /** A timedelta's most days, 999999999: 2^30 of them are past it. */
    private val MOST_DOUBLINGS: BigInteger = BigInteger.valueOf(30)

    private fun key(provider: String) = "provider:$provider"

    /** A state as read, with its `last_error` as the record holds it (JsonNull: none), which [save] writes back. */
    private class Read(val state: ProviderState, val lastError: JsonElement)

    /** get_state. */
    fun state(db: Db, provider: String): ProviderState = read(db, provider).state

    private fun read(db: Db, provider: String): Read {
        val raw = db.kvGet(key(provider))?.let { record(it) } ?: JsonObject(emptyMap())
        val lastError = raw["last_error"] ?: JsonNull
        return Read(ProviderState(
            provider = provider,
            strikes = raw["strikes"]?.let(::pyInt) ?: BigInteger.ZERO,
            cooldownUntil = time(raw["cooldown_until"]),
            lastOk = time(raw["last_ok"]),
            lastError = when {
                lastError is JsonNull -> null
                lastError is JsonPrimitive && lastError.isString -> lastError.content
                else -> PyJson.dumps(lastError)
            },
            lastErrorAt = time(raw["last_error_at"]),
        ), lastError)
    }

    /**
     * record_block: a cooldown for a lookup (or a job) that began at [now], 24 h × 2^(strikes − 1) + 2 h. One still
     * running at [now] stays as it is, with its strikes: one block is one strike.
     */
    fun recordBlock(db: Db, provider: String, now: Instant, message: String): ProviderState {
        val s = state(db, provider)
        if (s.cooldownUntil != null && now < s.cooldownUntil) return s
        val strikes = s.strikes + BigInteger.ONE
        return save(db, s.copy(strikes = strikes, cooldownUntil = cooldownAfter(now, strikes), lastError = message,
                               lastErrorAt = now), JsonPrimitive(message))
    }

    /** record_ok: a lookup that began at [now] met no block: no cooldown and no strike, unless one runs at [now]. */
    fun recordOk(db: Db, provider: String, now: Instant): ProviderState {
        val r = read(db, provider)
        val s = r.state
        if (s.cooldownUntil != null && now < s.cooldownUntil) return s
        return save(db, s.copy(strikes = BigInteger.ZERO, cooldownUntil = null, lastOk = now), r.lastError)
    }

    /** record_error: an error that is no block, remembered; it starts no cooldown. */
    fun recordError(db: Db, provider: String, now: Instant, message: String): ProviderState =
        save(db, state(db, provider).copy(lastError = message, lastErrorAt = now), JsonPrimitive(message))

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

    /** _save: [s] with [lastError], `last_error` as the record will hold it. */
    private fun save(db: Db, s: ProviderState, lastError: JsonElement): ProviderState {
        fun stamp(t: Instant?): JsonElement = if (t == null) JsonNull else JsonPrimitive(Strptime.format(t))
        db.kvSetJson(key(s.provider), JsonObject(linkedMapOf(
            "strikes" to JsonPrimitive(s.strikes),
            "cooldown_until" to stamp(s.cooldownUntil),
            "last_ok" to stamp(s.lastOk),
            "last_error" to lastError,
            "last_error_at" to stamp(s.lastErrorAt),
        )))
        return s
    }

    /**
     * `now + COOLDOWN_BASE * (2 ** (strikes - 1)) + COOLDOWN_MARGIN`: a power of two of days, or below one strike a
     * fraction of a day in microseconds rounded half to even (timedelta times the float `2 ** e`, none below 2^-61 of
     * one); past timedelta's 999999999 days, datetime's year 9999 or a float's range an [ArithmeticException],
     * Python's OverflowError.
     */
    private fun cooldownAfter(now: Instant, strikes: BigInteger): Instant {
        val e = strikes - BigInteger.ONE
        val base = when {
            e >= MOST_DOUBLINGS -> throw ArithmeticException("days=2**$e; must have magnitude <= 999999999")
            e.signum() >= 0 -> BASE.multipliedBy(1L shl e.toInt())
            e.toDouble().isInfinite() -> throw ArithmeticException("int too large to convert to float")
            else -> Duration.of(halfEven(DAY_MICROS, e.negate()), ChronoUnit.MICROS)
        }
        val until = now.plus(base).plus(MARGIN)
        if (until > LAST) throw ArithmeticException("date value out of range")
        return until
    }

    /** [x] / 2^[k], rounded half to even. */
    private fun halfEven(x: Long, k: BigInteger): Long {
        if (k >= BigInteger.valueOf(62)) return 0
        val shift = k.toInt()
        val q = x shr shift
        val r = x - (q shl shift)
        val half = 1L shl (shift - 1)
        return if (r > half || (r == half && q % 2 == 1L)) q + 1 else q
    }

    // --- reading the record as Python does --------------------------------------------------------------------------

    /** `kv_get_json(…) or {}`: the record, an object; a falsy value none; anything else Python's AttributeError. */
    private fun record(text: String): JsonObject? {
        val value = PyJson.loads(text)
        if (falsy(value)) return null
        return value as? JsonObject ?: throw IllegalStateException("${kind(value)} object has no attribute 'get'")
    }

    /** `not value` of what json.loads gives: null, false, a zero, an empty text, list or object. */
    private fun falsy(v: JsonElement): Boolean = when (v) {
        is JsonNull -> true
        is JsonObject -> v.isEmpty()
        is JsonArray -> v.isEmpty()
        is JsonPrimitive -> when {
            v.isString -> v.content.isEmpty()
            v.content == "true" -> false
            v.content == "false" -> true
            isIntLiteral(v.content) -> v.content.removePrefix("-").all { it == '0' }
            else -> PyFloat.parse(v.content) == 0.0  // NaN and the infinities are true
        }
    }

    private fun kind(v: JsonElement): String = when {
        v is JsonArray -> "'list'"
        v is JsonPrimitive && v.isString -> "'str'"
        v is JsonPrimitive && (v.content == "true" || v.content == "false") -> "'bool'"
        v is JsonPrimitive && isIntLiteral(v.content) -> "'int'"
        else -> "'float'"
    }

    /** `_parse(value)`: none for a falsy value, a text strptime reads, else Python's TypeError. */
    private fun time(v: JsonElement?): Instant? {
        if (v == null || falsy(v)) return null
        if (v is JsonPrimitive && v.isString) return Strptime.parse(v.content)
        throw IllegalArgumentException("strptime() argument 1 must be str, not $v")
    }

    /** `int(value)` of a JSON value: a boolean 1 or 0, an int as it is, a float truncated toward zero (NaN Python's
     * ValueError, an infinity its OverflowError), a text as [PyInt] reads it; anything else Python's TypeError. */
    private fun pyInt(v: JsonElement): BigInteger {
        if (v !is JsonPrimitive || v is JsonNull) {
            throw IllegalArgumentException("int() argument must be a string or a real number, not $v")
        }
        if (v.isString) return PyInt.parse(v.content)
            ?: throw IllegalArgumentException("invalid literal for int() with base 10: ${v.content}")
        return when (v.content) {
            "true" -> BigInteger.ONE
            "false" -> BigInteger.ZERO
            else -> number(v.content)
        }
    }

    private fun isIntLiteral(literal: String): Boolean {
        val digits = literal.removePrefix("-")
        return digits.isNotEmpty() && digits.all { it in '0'..'9' }
    }

    /** A number json.loads gave, as `int()` takes it: an int's literal (PyJson.loads writes no other way) as it is, a
     * float's (PyJson.float's: `2.7`, `1e+16`, `NaN`, `Infinity`) truncated toward zero. */
    private fun number(literal: String): BigInteger {
        if (isIntLiteral(literal)) return BigInteger(literal)
        val x = PyFloat.parse(literal) ?: throw IllegalArgumentException("not a number: $literal")
        if (x.isNaN()) throw IllegalArgumentException("cannot convert float NaN to integer")
        if (x.isInfinite()) throw ArithmeticException("cannot convert float infinity to integer")
        return BigDecimal(x).setScale(0, RoundingMode.DOWN).toBigIntegerExact()
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
