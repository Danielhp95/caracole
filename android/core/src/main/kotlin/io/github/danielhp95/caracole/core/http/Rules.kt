package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigInteger
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

/** http.py's constants, as tests/test_conformance_http.py wrote them: data/caracole/http/http.json. */
internal object HttpData {
    private val data: JsonObject by lazy { Json.parseToJsonElement(Database.resource("caracole/http/http.json")).jsonObject }

    val cachedStatuses: Set<Int> by lazy { data.getValue("cached_statuses").jsonArray.map { it.jsonPrimitive.int }.toSet() }
    val keptHeaders: List<String> by lazy { data.getValue("kept_headers").jsonArray.map { it.jsonPrimitive.content } }
    val challengeMarkers: List<ByteArray> by lazy {
        data.getValue("challenge_markers").jsonArray.map { it.jsonPrimitive.content.toByteArray(Charsets.US_ASCII) }
    }
    val challengeHead: Int by lazy { data.getValue("challenge_head").jsonPrimitive.int }
    val maxRedirects: Int by lazy { data.getValue("max_redirects").jsonPrimitive.int }
    val retryAfter503: Map<String, Double> by lazy {
        data.getValue("retry_after_503").jsonObject.mapValues { it.value.jsonPrimitive.double }
    }
    val retryJitter: Double by lazy { data.getValue("retry_jitter").jsonPrimitive.double }
}

/** http.py's robots rules (`ROBOTS_DISALLOW`), as data: data/caracole/http/robots.json. */
object Robots {
    const val NOT_A_URL = "not a valid URL"

    private class Rule(val text: String) {
        private val anchored = text.endsWith("$")
        private val parts = text.removeSuffix("$").split('*')

        /** `re.match` of the rule's pattern at the start of [target]: `*` any run, a trailing `$` the end. */
        fun matches(target: String): Boolean {
            if (parts.size == 1) return if (anchored) target == parts[0] else target.startsWith(parts[0])
            if (!target.startsWith(parts[0])) return false
            var at = parts[0].length
            for (i in 1 until parts.size - 1) {
                val found = target.indexOf(parts[i], at)
                if (found < 0) return false
                at = found + parts[i].length
            }
            val last = parts.last()
            return if (anchored) target.length - last.length >= at && target.endsWith(last) else target.indexOf(last, at) >= 0
        }
    }

    private val rules: Map<String, List<Rule>> by lazy {
        Json.parseToJsonElement(Database.resource("caracole/http/robots.json")).jsonObject.getValue("hosts").jsonObject
            .mapValues { (_, list) -> list.jsonArray.map { Rule(it.jsonPrimitive.content) } }
    }

    /** The rule that closes [url], or null for a URL caracole may ask for; [NOT_A_URL] for a string httpx can't take
     * as a URL, which can't be asked for either. */
    fun disallows(url: String): String? {
        val host: String
        val target: String
        try {
            val u = HttpxUrl.parse(url)
            host = u.decodedHost
            target = u.rawPath
        } catch (e: UrlError) {
            return NOT_A_URL
        }
        return rules[host]?.firstOrNull { it.matches(target) }?.text
    }
}

/** http.py's rules about an answer: stale, Retry-After, a challenge page, read once more past the cache. */
object HttpRules {
    /** A cached copy older than [maxAge] at [now], or of unknown age; a fresh answer never is. */
    fun stale(r: Response, now: Instant, maxAge: Duration): Boolean {
        if (!r.fromCache) return false
        val fetched = r.fetchedAt?.let { Stamp.parse(it) } ?: return true
        return Duration.between(fetched, Stamp.micros(now)) > maxAge
    }

    /** The seconds an answer's `Retry-After` asks to wait from [now]: whole seconds, or an HTTP date (one already past
     * 0); null for none, or one that is neither. */
    fun retryAfter(headers: Map<String, String>, now: Instant): Double? {
        val value = PyText.strip(header(headers, "retry-after") ?: "")
        if (value.isNotEmpty() && value.all { it in '0'..'9' }) return value.toDouble()
        val `when` = EmailDate.parse(value) ?: return null
        val micros = Duration.between(Stamp.micros(now), `when`).let { it.seconds * 1_000_000 + it.nano / 1000 }
        return maxOf(0.0, micros.toDouble() / 1e6)
    }

    /** Whether an answer is a bot challenge (which counts as a block): `cf-mitigated: challenge`, or one of
     * http.py's markers in the first bytes of the body. */
    fun isChallenge(headers: Map<String, String>, body: ByteArray): Boolean {
        if (PyUnicode.lower(header(headers, "cf-mitigated") ?: "None") == "challenge") return true
        val head = minOf(body.size, HttpData.challengeHead)
        return HttpData.challengeMarkers.any { contains(body, head, it) }
    }

    private fun contains(body: ByteArray, end: Int, marker: ByteArray): Boolean {
        outer@ for (i in 0..end - marker.size) {
            for (j in marker.indices) if (body[i + j] != marker[j]) continue@outer
            return true
        }
        return false
    }

    /**
     * `read(resp)`, where [resp] answered [url]; a cached answer [read] can't read ([unreadable] says so of what it
     * threw) is asked for once more, past the cache, with [params] and [accept], and read again. A fresh answer that
     * fails is an error, and so is one for a URL this pass fetched already ([fetched], which gains each URL fetched).
     */
    fun <T> readOnceMore(client: Client, resp: Response, url: String, unreadable: (Throwable) -> Boolean,
                         fetched: MutableSet<String>? = null, accept: Set<Int> = setOf(200),
                         params: List<Pair<String, String>>? = null, read: (Response) -> T): T {
        if (fetched != null && !resp.fromCache) fetched.add(url)
        try {
            return read(resp)
        } catch (e: Throwable) {
            if (!unreadable(e)) throw e
            if (!resp.fromCache || (fetched != null && url in fetched)) throw e
        }
        fetched?.add(url)
        return read(client.get(url, params = params, cache = false, accept = accept))
    }

    /** http.py's `_header`: the first value whose name is [name], whatever its case. */
    internal fun header(headers: Map<String, String>, name: String): String? =
        headers.entries.firstOrNull { PyUnicode.lower(it.key) == name }?.value
}

/** caracole's stamp, `%Y-%m-%dT%H:%M:%SZ` in UTC: a cached copy's `fetched_at`. */
internal object Stamp {
    private val SHAPE = Regex("""([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z""")

    private fun pad(n: Int, width: Int) = n.toString().padStart(width, '0')

    fun format(t: Instant): String {
        val d = LocalDateTime.ofEpochSecond(t.epochSecond, 0, ZoneOffset.UTC)
        return "${pad(d.year, 4)}-${pad(d.monthValue, 2)}-${pad(d.dayOfMonth, 2)}T${pad(d.hour, 2)}:${pad(d.minute, 2)}:" +
            "${pad(d.second, 2)}Z"
    }

    /** A stamp as an instant; an [IllegalArgumentException] for one that isn't, as strptime raises. */
    fun parse(s: String): Instant {
        val m = SHAPE.matchEntire(s) ?: throw IllegalArgumentException("time data '$s' does not match format '%Y-%m-%dT%H:%M:%SZ'")
        val (y, mo, d, h, mi, se) = m.destructured
        return LocalDateTime.of(y.toInt(), mo.toInt(), d.toInt(), h.toInt(), mi.toInt(), se.toInt()).toInstant(ZoneOffset.UTC)
    }

    /** [t] to the microsecond, as Python's datetime holds a time. */
    fun micros(t: Instant): Instant = t.minusNanos((t.nano % 1000).toLong())
}

/** email.utils.parsedate_to_datetime, as http.py's retry_after reads an HTTP date: the instant, or null where Python
 * raises (a naive date is UTC). */
internal object EmailDate {
    private val MONTHS = listOf("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                                "january", "february", "march", "april", "may", "june", "july", "august",
                                "september", "october", "november", "december")
    private val DAYS = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    private val ZONES = mapOf("UT" to 0, "UTC" to 0, "GMT" to 0, "Z" to 0, "AST" to -400, "ADT" to -300,
                              "EST" to -500, "EDT" to -400, "CST" to -600, "CDT" to -500, "MST" to -700,
                              "MDT" to -600, "PST" to -800, "PDT" to -700)

    private fun int(s: String): BigInteger? = PyIntText.parse(s)

    fun parse(text: String): Instant? {
        if (text.isEmpty()) return null
        var data = Py.split(text).toMutableList()
        if (data.isEmpty()) return null
        if (data[0].endsWith(",") || PyUnicode.lower(data[0]) in DAYS) {
            data.removeAt(0)
        } else {
            val i = data[0].lastIndexOf(',')
            if (i >= 0) data[0] = data[0].substring(i + 1)
        }
        if (data.size == 3) {
            val stuff = data[0].split('-')
            if (stuff.size == 3) data = (stuff + data.subList(1, data.size)).toMutableList()
        }
        if (data.size == 4) {
            val s = data[3]
            var i = s.indexOf('+')
            if (i == -1) i = s.indexOf('-')
            if (i > 0) {
                data.removeAt(3)
                data.add(s.substring(0, i))
                data.add(s.substring(i))
            } else {
                data.add("")
            }
        }
        if (data.size < 5) return null
        var (dd, mm, yy, tm, tz) = data.subList(0, 5)
        if (dd.isEmpty() || mm.isEmpty() || yy.isEmpty()) return null
        mm = PyUnicode.lower(mm)
        if (mm !in MONTHS) {
            val swapped = dd
            dd = mm
            mm = PyUnicode.lower(swapped)
            if (mm !in MONTHS) return null
        }
        var month = MONTHS.indexOf(mm) + 1
        if (month > 12) month -= 12
        if (dd.endsWith(",")) dd = dd.dropLast(1)
        val colon = yy.indexOf(':')
        if (colon > 0) {
            val t = yy
            yy = tm
            tm = t
        }
        if (yy.endsWith(",")) {
            yy = yy.dropLast(1)
            if (yy.isEmpty()) return null
        }
        if (yy.isEmpty()) return null
        if (!PyUnicode.isDigit(yy.codePointAt(0))) {
            val t = yy
            yy = tz
            tz = t
        }
        if (tm.isEmpty()) return null
        if (tm.endsWith(",")) tm = tm.dropLast(1)
        var parts = tm.split(':')
        val thh: String
        val tmm: String
        val tss: String
        when {
            parts.size == 2 -> { thh = parts[0]; tmm = parts[1]; tss = "0" }
            parts.size == 3 -> { thh = parts[0]; tmm = parts[1]; tss = parts[2] }
            parts.size == 1 && '.' in parts[0] -> {
                parts = parts[0].split('.')
                when (parts.size) {
                    2 -> { thh = parts[0]; tmm = parts[1]; tss = "0" }
                    3 -> { thh = parts[0]; tmm = parts[1]; tss = parts[2] }
                    else -> return null
                }
            }
            else -> return null
        }
        var year = int(yy) ?: return null
        val day = int(dd) ?: return null
        val hour = int(thh) ?: return null
        val minute = int(tmm) ?: return null
        val second = int(tss) ?: return null
        if (year < BigInteger.valueOf(100)) year += BigInteger.valueOf(if (year > BigInteger.valueOf(68)) 1900 else 2000)
        var offset: BigInteger? = null
        val zone = PyUnicode.upper(tz)
        if (zone in ZONES) {
            offset = BigInteger.valueOf(ZONES.getValue(zone).toLong())
        } else {
            offset = int(zone)
            if (offset != null && offset.signum() == 0 && zone.startsWith("-")) offset = null
        }
        if (offset != null && offset.signum() != 0) {
            val sign = offset.signum()
            val abs = offset.abs()
            val hundred = BigInteger.valueOf(100)
            offset = BigInteger.valueOf(sign.toLong()) * (abs / hundred * BigInteger.valueOf(3600) +
                abs.mod(hundred) * BigInteger.valueOf(60))
        }
        // datetime(*dtuple[:6], tzinfo=timezone(timedelta(seconds=tz))): ValueError (or OverflowError) out of range
        fun inRange(x: BigInteger, lo: Int, hi: Int) = x >= BigInteger.valueOf(lo.toLong()) && x <= BigInteger.valueOf(hi.toLong())
        if (!inRange(year, 1, 9999) || !inRange(hour, 0, 23) || !inRange(minute, 0, 59) || !inRange(second, 0, 59)) return null
        val y = year.toInt()
        val length = java.time.YearMonth.of(y, month).lengthOfMonth()
        if (!inRange(day, 1, length)) return null
        val seconds = offset ?: BigInteger.ZERO
        if (offset != null && !(seconds > BigInteger.valueOf(-86400) && seconds < BigInteger.valueOf(86400))) return null
        val local = LocalDateTime.of(y, month, day.toInt(), hour.toInt(), minute.toInt(), second.toInt())
        return local.toInstant(ZoneOffset.UTC).minusSeconds(seconds.toLong())
    }
}
