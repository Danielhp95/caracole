package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.library.internal.PyRepr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * stamps.py on the phone, its one port: how caracole reads a stored time (`stamps.parse`: `datetime.fromisoformat`,
 * then the time in UTC, a naive one being UTC already), as a merge compares two, a take reads its `now` and LaCuerda's
 * index asks whether its listings were read whole; and how caracole writes one (`stamps.stamp`:
 * "2026-10-18T03:30:00Z"). vectors/index/stamps.jsonl and vectors/library/stamps.jsonl hold Python's answers.
 *
 * A time is its instant, in microseconds since 0001-01-01T00:00:00 UTC, so that two compare as Python's aware
 * datetimes do. [parse] reads what CPython 3.14's C `datetime.fromisoformat` reads (tests/conformance/vectors/index/
 * stamps.jsonl), its edges included:
 *
 * - the date: `YYYY-MM-DD`, `YYYYMMDD`, `YYYY-Www[-D]`, `YYYYWww[D]` in ASCII digits, a week date by ISO's calendar;
 * - the separator: any one character, where the date's shape puts it, a non-ASCII one skipped whole (a lone surrogate
 *   at 7, 8 or 10, the first there, read as `T`);
 * - the time, read on its UTF-8 bytes: `HH[:MM[:SS[.f…]]]` or `HHMMSS[.f…]`, a fraction's first six digits (`,` or
 *   `.`), then `Z` or an offset `±HH[:MM[:SS[.f…]]]` whose fields aren't range-checked (`+05:60` is 06:00) but whose
 *   total is under a day; one stray character between the seconds and the offset, and any after six fraction digits,
 *   as the C parser lets them by;
 * - `24:00` with nothing after it the next day's midnight, where the date is one.
 *
 * Anything else is no time (null). A time whose UTC falls outside years 1 to 9999 is an [ArithmeticException], as
 * `astimezone` raises Python's OverflowError, which a merge never catches either. [fromisoformat] is the same reader
 * for a caller that keeps the time as read (web/history.py's `_time`, JobHistory), and [isoformat] the writer of one.
 */
object Stamps {
    private const val DAY_US = 86_400_000_000L
    private const val SECOND_US = 1_000_000L

    /** 0001-01-01T00:00:00 and the microsecond after 9999-12-31T23:59:59.999999, as instants. */
    private const val MIN_US = 0L
    private val END_US: Long by lazy { (ordinal(10000, 1, 1) - 1) * DAY_US }

    /** 1970-01-01T00:00:00 UTC, java.time's epoch, as a time here. */
    private val UNIX_US: Long by lazy { (ordinal(1970, 1, 1) - 1) * DAY_US }

    /** stamps.parse(value) for a string: null when [value] is null, empty or no time. */
    fun parse(value: String?): Long? {
        if (value.isNullOrEmpty()) return null
        val read = read(value) ?: return null
        val utc = read.local - (read.offset ?: 0L)
        if (utc < MIN_US || utc >= END_US) throw ArithmeticException("date value out of range: $value")
        return utc
    }

    /**
     * `datetime.fromisoformat(value)` itself, as the aware time it names, a naive one UTC: its instant here, whatever
     * year its UTC falls in (history.py's `_time` keeps the datetime as read, never converting it, so
     * `0001-01-01T00:00:00+01:00` is a time there); [IllegalArgumentException] where Python raises ValueError.
     */
    fun fromisoformat(value: String): Long {
        val read = read(value) ?: throw IllegalArgumentException("Invalid isoformat string: ${PyRepr.str(value)}")
        return read.local - (read.offset ?: 0L)
    }

    /**
     * stamps.parse of a value a record holds, as Python passes it on: a string read; a falsy value (null, false, 0,
     * 0.0, "", [] or {}) none; anything else Python's TypeError, here an IllegalArgumentException (a merge never
     * catches it either).
     */
    fun parse(value: JsonElement?): Long? = when {
        value == null || value is JsonNull -> null
        value is JsonPrimitive && value.isString -> parse(value.content)
        value is JsonPrimitive && value.content == "false" -> null
        value is JsonPrimitive && value.content == "true" -> throw IllegalArgumentException("fromisoformat: a bool")
        value is JsonPrimitive && zero(value.content) -> null
        value is JsonArray && value.isEmpty() -> null
        value is JsonObject && value.isEmpty() -> null
        else -> throw IllegalArgumentException("fromisoformat: argument must be str")
    }

    /** stamps.stamp of a time the clock gave: [at] in UTC to the second, "2026-10-18T03:30:00Z". */
    fun of(at: Instant): String = stamp(micros(at))

    /** The clock now, as caracole stores a time (songs.utc_now_iso). */
    fun now(): String = of(Instant.now())

    /** peer_sync._when, then stamps.stamp: [now] as caracole stores a time, or IllegalArgumentException("not a time:
     * 'soon'") for one stamps.parse reads as none. */
    fun stampOf(now: String): String =
        parse(now)?.let(::stamp) ?: throw IllegalArgumentException("not a time: ${PyRepr.str(now)}")

    /** [at] as a time here: microseconds since 0001-01-01T00:00:00 UTC (a fraction of a microsecond dropped). */
    fun micros(at: Instant): Long =
        UNIX_US + Math.multiplyExact(at.epochSecond, SECOND_US) + Math.floorDiv(at.nano, 1000)

    /** A time here as java.time's instant. */
    fun instant(micros: Long): Instant {
        val sinceUnix = micros - UNIX_US
        return Instant.ofEpochSecond(Math.floorDiv(sinceUnix, SECOND_US), Math.floorMod(sinceUnix, SECOND_US) * 1000)
    }

    /** stamps.stamp: [instant] in UTC to the second, "2026-10-18T03:30:00Z". */
    fun stamp(instant: Long): String {
        val days = Math.floorDiv(instant, DAY_US)
        val (year, month, day) = ymd(days + 1)
        val inDay = Math.floorMod(instant, DAY_US) / SECOND_US
        return pad(year, 4) + "-" + pad(month, 2) + "-" + pad(day, 2) + "T" + pad((inDay / 3600).toInt(), 2) + ":" +
            pad((inDay / 60 % 60).toInt(), 2) + ":" + pad((inDay % 60).toInt(), 2) + "Z"
    }

    /** [instant] as Python's `isoformat()` writes the UTC datetime: microseconds only when there are some. */
    fun isoformat(instant: Long): String {
        val text = stamp(instant).dropLast(1)
        val micros = Math.floorMod(instant, SECOND_US)
        return text + (if (micros != 0L) "." + pad(micros.toInt(), 6) else "") + "+00:00"
    }

    private fun pad(n: Int, width: Int): String = n.toString().padStart(width, '0')

    /** Whether a JSON number literal is a zero as json.loads reads it: an integer of zeros, a float that is 0.0
     * (`1e-400` too, which underflows); NaN and the infinities are truthy. */
    private fun zero(literal: String): Boolean {
        val digits = literal.removePrefix("-")
        if (digits.isEmpty() || digits.first() !in '0'..'9') return false
        if (digits.all { it in '0'..'9' }) return digits.all { it == '0' }
        return literal.toDouble() == 0.0
    }

    // --- datetime.fromisoformat ------------------------------------------------------------------------------------

    /** A time read: its wall clock's instant as if it were UTC, and its offset (null for a naive time). */
    private class Read(val local: Long, val offset: Long?)

    private class Bad : Exception() {
        override fun fillInStackTrace(): Throwable = this
    }

    private fun read(value: String): Read? = try {
        readIso(value)
    } catch (_: Bad) {
        null
    }

    private fun isSurrogate(c: Char) = c in '\uD800'..'\uDFFF'

    private fun readIso(value: String): Read {
        // _sanitize_isoformat_str: at least 7 characters; a surrogate at 7, 8 or 10 (the first) read as 'T'.
        val points = value.codePoints().toArray()
        if (points.size < 7) throw Bad()
        for (pos in intArrayOf(7, 8, 10)) {
            if (pos > points.size) break
            if (pos < points.size && points[pos] in 0xD800..0xDFFF) {
                points[pos] = 'T'.code
                break
            }
        }
        // PyUnicode_AsUTF8AndSize: a lone surrogate left is no time.
        val text = String(points, 0, points.size)
        if (text.any(::isSurrogate) && hasLoneSurrogate(text)) throw Bad()
        val b = text.toByteArray(Charsets.UTF_8)
        val n = b.size
        val separator = separator(b, n)
        if (separator < 0) throw Bad()
        val date = date(b, separator)
        var hour = 0
        var minute = 0
        var second = 0
        var micro = 0
        var offset: Long? = null
        if (n > separator) {
            val start = separator + utf8Length(b[separator].toInt() and 0xFF)
            val time = time(b, start, n)
            hour = time.hour
            minute = time.minute
            second = time.second
            micro = time.micro
            offset = time.offset
        }
        var (year, month, day) = date
        if (hour == 24 && month in 1..12 && day <= daysIn(year, month)) {
            if (minute != 0 || second != 0 || micro != 0) throw Bad()
            hour = 0
            day += 1
            if (day > daysIn(year, month)) {
                day = 1
                month += 1
                if (month > 12) {
                    month = 1
                    year += 1
                }
            }
        }
        if (year !in 1..9999 || month !in 1..12 || day !in 1..daysIn(year, month)) throw Bad()
        if (hour !in 0..23 || minute !in 0..59 || second !in 0..59) throw Bad()
        val local = (ordinal(year, month, day) - 1) * DAY_US +
            ((hour * 60L + minute) * 60L + second) * SECOND_US + micro
        return Read(local, offset)
    }

    private fun hasLoneSurrogate(s: String): Boolean {
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (Character.isHighSurrogate(c) && i + 1 < s.length && Character.isLowSurrogate(s[i + 1])) {
                i += 2
                continue
            }
            if (isSurrogate(c)) return true
            i++
        }
        return false
    }

    private fun utf8Length(lead: Int): Int = when {
        lead < 0x80 -> 1
        lead < 0xE0 -> 2
        lead < 0xF0 -> 3
        else -> 4
    }

    /** The byte at [i], or 0 past the end (the C string's terminator). */
    private fun at(b: ByteArray, i: Int): Int = if (i in b.indices) b[i].toInt() and 0xFF else 0

    private fun isDigit(c: Int) = c in 0x30..0x39

    /** parse_digits: [count] ASCII digits at [p], or null. */
    private fun digits(b: ByteArray, p: Int, count: Int): Int? {
        var value = 0
        for (k in 0 until count) {
            val c = at(b, p + k)
            if (!isDigit(c)) return null
            value = value * 10 + (c - 0x30)
        }
        return value
    }

    /** _find_isoformat_datetime_separator, on the UTF-8 bytes: where the date ends; -1 for none. */
    private fun separator(b: ByteArray, n: Int): Int {
        if (n == 7) return 7
        if (at(b, 4) == '-'.code) {
            if (at(b, 5) == 'W'.code) {
                if (n > 8 && at(b, 8) == '-'.code) {
                    if (n == 9) return -1
                    if (n > 10 && isDigit(at(b, 10))) return 8
                    return 10
                }
                return 8
            }
            return 10
        }
        if (at(b, 4) == 'W'.code) {
            var i = 7
            while (i < n && isDigit(at(b, i))) i++
            if (i < 9) return i
            return if (i % 2 == 0) 7 else 8
        }
        return 8
    }

    /** parse_isoformat_date: year, month and day, a week date made one. */
    private fun date(b: ByteArray, length: Int): Triple<Int, Int, Int> {
        var p = 0
        val year = digits(b, p, 4) ?: throw Bad()
        p += 4
        val dashes = at(b, p) == '-'.code
        if (dashes) p++
        if (at(b, p) == 'W'.code) {
            p++
            val week = digits(b, p, 2) ?: throw Bad()
            p += 2
            var weekday = 1
            if (p < length) {
                if (dashes && at(b, p++) != '-'.code) throw Bad()
                weekday = digits(b, p, 1) ?: throw Bad()
                p++
            }
            if (year !in 1..9999) throw Bad()
            if (week <= 0 || week >= 53) {
                var inRange = false
                if (week == 53) {
                    val first = Math.floorMod(ordinal(year, 1, 1) + 6, 7L).toInt()
                    inRange = first == 3 || (first == 2 && leap(year))
                }
                if (!inRange) throw Bad()
            }
            if (weekday <= 0 || weekday >= 8) throw Bad()
            return ymd(week1Monday(year) + (week - 1) * 7L + weekday - 1)
        }
        val month = digits(b, p, 2) ?: throw Bad()
        p += 2
        if (dashes && at(b, p++) != '-'.code) throw Bad()
        val day = digits(b, p, 2) ?: throw Bad()
        return Triple(year, month, day)
    }

    private class Clock(val code: Int, val hour: Int, val minute: Int, val second: Int, val micro: Int)

    private val CORRECTION = intArrayOf(100000, 10000, 1000, 100, 10)

    /** parse_hh_mm_ss_ff over [start, end): its code (1: something follows before the end; below 0: no time). */
    private fun clock(b: ByteArray, start: Int, end: Int): Clock {
        val values = IntArray(3)
        var p = start
        var colons = true
        var i = 0
        var micro = 0
        fun bad(code: Int) = Clock(code, values[0], values[1], values[2], 0)
        loop@ while (i < 3) {
            values[i] = digits(b, p, 2) ?: return bad(-3)
            p += 2
            val c = at(b, p)
            p++
            if (i == 0) colons = c == ':'.code
            if (c == '.'.code || c == ','.code) {
                if (i < 2 || p >= end) return bad(-3)
                break@loop
            }
            when {
                p >= end -> return Clock(if (c != 0) 1 else 0, values[0], values[1], values[2], 0)
                colons && c == ':'.code -> {
                    if (i == 2) return bad(-4)
                }
                !colons -> p--
                else -> return bad(-4)
            }
            i++
        }
        val count = minOf(end - p, 6)
        micro = digits(b, p, count) ?: return bad(-3)
        p += count
        if (count < 6) micro *= CORRECTION[count - 1]
        while (isDigit(at(b, p))) p++
        return Clock(if (at(b, p) != 0) 1 else 0, values[0], values[1], values[2], micro)
    }

    private class Time(val hour: Int, val minute: Int, val second: Int, val micro: Int, val offset: Long?)

    /** parse_isoformat_time over [start, end), then its offset as timezone() takes it (under a day). */
    private fun time(b: ByteArray, start: Int, end: Int): Time {
        var zone = start
        while (true) {
            val c = at(b, zone)
            if (c == 'Z'.code || c == '+'.code || c == '-'.code) break
            zone++
            if (zone >= end) break
        }
        val clock = clock(b, start, zone)
        if (clock.code < 0) throw Bad()
        if (zone == end) {
            if (clock.code == 1) throw Bad()
            return Time(clock.hour, clock.minute, clock.second, clock.micro, null)
        }
        if (at(b, zone) == 'Z'.code) {
            if (at(b, zone + 1) != 0) throw Bad()
            return Time(clock.hour, clock.minute, clock.second, clock.micro, 0L)
        }
        val sign = if (at(b, zone) == '-'.code) -1L else 1L
        val tz = clock(b, zone + 1, end)
        if (tz.code != 0) throw Bad()
        val offset = sign * (((tz.hour * 3600L) + tz.minute * 60L + tz.second) * SECOND_US + tz.micro)
        if (offset <= -DAY_US || offset >= DAY_US) throw Bad()
        return Time(clock.hour, clock.minute, clock.second, clock.micro, offset)
    }

    // --- the proleptic Gregorian calendar, as datetime counts it ----------------------------------------------------

    private val DAYS_IN = intArrayOf(0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    private val DAYS_BEFORE = intArrayOf(0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)

    private fun leap(year: Int) = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)

    private fun daysIn(year: Int, month: Int): Int = if (month == 2 && leap(year)) 29 else DAYS_IN[month]

    private fun daysBeforeYear(year: Int): Long {
        val y = year - 1L
        return y * 365 + Math.floorDiv(y, 4L) - Math.floorDiv(y, 100L) + Math.floorDiv(y, 400L)
    }

    /** _ymd2ord: 0001-01-01 is day 1. */
    private fun ordinal(year: Int, month: Int, day: Int): Long =
        daysBeforeYear(year) + DAYS_BEFORE[month] + (if (month > 2 && leap(year)) 1 else 0) + day

    private val D400 = daysBeforeYear(401)
    private val D100 = daysBeforeYear(101)
    private val D4 = daysBeforeYear(5)

    /** _ord2ymd, for any ordinal (a year past 9999 is the caller's to refuse). */
    private fun ymd(ordinal: Long): Triple<Int, Int, Int> {
        var n = ordinal - 1
        val n400 = Math.floorDiv(n, D400)
        n = Math.floorMod(n, D400)
        var year = n400 * 400 + 1
        val n100 = n / D100
        n %= D100
        val n4 = n / D4
        n %= D4
        val n1 = n / 365
        n %= 365
        year += n100 * 100 + n4 * 4 + n1
        if (n1 == 4L || n100 == 4L) return Triple((year - 1).toInt(), 12, 31)
        val isLeap = n1 == 3L && (n4 != 24L || n100 == 3L)
        var month = ((n + 50) shr 5).toInt()
        var preceding = DAYS_BEFORE[month] + if (month > 2 && isLeap) 1 else 0
        if (preceding > n) {
            month -= 1
            preceding -= DAYS_IN[month] + if (month == 2 && isLeap) 1 else 0
        }
        return Triple(year.toInt(), month, (n - preceding + 1).toInt())
    }

    /** _isoweek1monday: the ordinal of the Monday of the year's first ISO week. */
    private fun week1Monday(year: Int): Long {
        val first = ordinal(year, 1, 1)
        val weekday = Math.floorMod(first + 6, 7L)
        var monday = first - weekday
        if (weekday > 3) monday += 7
        return monday
    }
}
