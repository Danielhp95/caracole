package io.github.danielhp95.caracole.core.library.internal

import java.time.Instant
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * stamps.py on the phone: how caracole stores a time ("2026-10-31T00:00:00Z", ISO 8601 UTC to the second) and reads
 * one back, [parse] being `stamps.parse`: `datetime.fromisoformat` (CPython 3.14's C reading, which is stricter than
 * `_pydatetime`'s: ASCII digits alone, a separator of any one character, an empty time after it refused), then the
 * time in UTC, a naive one being UTC already. A time that reads but leaves years 1–9999 once in UTC is no time here
 * (Python raises OverflowError there). vectors/library/stamps.jsonl holds Python's answers.
 */
internal object Stamps {
    /** A time in UTC, as Python's datetime holds it, to the microsecond. */
    data class Utc(val year: Int, val month: Int, val day: Int, val hour: Int, val minute: Int, val second: Int,
                   val micro: Int) {
        /** stamps.stamp: "2026-10-31T00:00:00Z". */
        val stamp: String get() = date() + "Z"

        /** datetime.isoformat() of the time in UTC: "2026-10-31T00:00:00.500000+00:00". */
        val iso: String get() = date() + (if (micro != 0) "." + pad(micro, 6) else "") + "+00:00"

        private fun date() =
            "${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}T${pad(hour, 2)}:${pad(minute, 2)}:${pad(second, 2)}"
    }

    /** stamps.parse: the stored time in UTC, or null when it is missing or unreadable. */
    fun parse(value: String?): Utc? {
        if (value.isNullOrEmpty()) return null
        return try {
            Reading(value).read()
        } catch (_: Unreadable) {
            null
        }
    }

    /** `now` as caracole stores a time, or IllegalArgumentException("not a time: …"), as peer_sync._when says it. */
    fun stampOf(now: String): String =
        parse(now)?.stamp ?: throw IllegalArgumentException("not a time: ${PyRepr.str(now)}")

    /** The clock now, as caracole stores a time (songs.utc_now_iso). */
    fun now(): String = Instant.now().truncatedTo(ChronoUnit.SECONDS).let {
        val t = it.atOffset(java.time.ZoneOffset.UTC)
        Utc(t.year, t.monthValue, t.dayOfMonth, t.hour, t.minute, t.second, 0).stamp
    }

    private fun pad(n: Int, width: Int): String {
        val digits = n.toString()
        return if (digits.length >= width) digits else "0".repeat(width - digits.length) + digits
    }

    private class Unreadable : Exception()

    /** datetime.fromisoformat's C reading, over code points, with a 0 after the last as C's NUL. */
    private class Reading(text: String) {
        private val s: IntArray = text.codePoints().toArray().let { it.copyOf(it.size + 1) }
        private val len = s.size - 1

        private fun at(i: Int): Int = if (i < s.size) s[i] else 0
        private fun digit(i: Int): Int? = at(i).let { if (it in '0'.code..'9'.code) it - '0'.code else null }
        private fun fail(): Nothing = throw Unreadable()

        /** [n] ASCII digits from [i], as a number. */
        private fun digits(i: Int, n: Int): Int {
            var v = 0
            for (k in 0 until n) v = v * 10 + (digit(i + k) ?: fail())
            return v
        }

        fun read(): Utc {
            if (len < 7) fail()
            if ((0 until len).any { s[it] in 0xD800..0xDFFF && it != 7 && it != 8 && it != 10 }) fail()
            val sep = separator()
            val date = date(sep)
            var hour = 0
            var minute = 0
            var second = 0
            var micro = 0
            var offset = 0L // microseconds east of UTC
            if (len > sep) {
                val t = time(sep + 1, len)
                hour = t[0]; minute = t[1]; second = t[2]; micro = t[3]
                offset = t[4].toLong() * 1_000_000 + t[5]
            }
            var (year, month, day) = date
            if (hour == 24 && month <= 12) {
                val days = daysIn(year, month)
                if (day <= days) {
                    if (minute != 0 || second != 0 || micro != 0) fail()
                    hour = 0
                    day += 1
                    if (day > days) {
                        day = 1
                        month += 1
                        if (month > 12) { month = 1; year += 1 }
                    }
                }
            }
            if (year !in 1..9999 || month !in 1..12 || day < 1 || day > daysIn(year, month)) fail()
            if (hour !in 0..23 || minute !in 0..59 || second !in 0..59 || micro !in 0..999_999) fail()
            if (offset == 0L) return Utc(year, month, day, hour, minute, second, micro)
            // In UTC: the local time less its offset.
            val local = LocalDate.of(year, month, day).toEpochDay() * 86_400_000_000L +
                ((hour * 60L + minute) * 60L + second) * 1_000_000L + micro
            val utc = local - offset
            val days = Math.floorDiv(utc, 86_400_000_000L)
            val rest = Math.floorMod(utc, 86_400_000_000L)
            val d = LocalDate.ofEpochDay(days)
            if (d.year !in 1..9999) fail()
            val seconds = rest / 1_000_000L
            return Utc(d.year, d.monthValue, d.dayOfMonth, (seconds / 3600).toInt(), (seconds / 60 % 60).toInt(),
                       (seconds % 60).toInt(), (rest % 1_000_000L).toInt())
        }

        /** _find_isoformat_datetime_separator. */
        private fun separator(): Int {
            if (len == 7) return 7
            if (at(4) == '-'.code) {
                if (at(5) == 'W'.code) {
                    if (len < 8) fail()
                    if (len > 8 && at(8) == '-'.code) {
                        if (len == 9) fail()
                        if (len > 10 && digit(10) != null) return 8
                        return 10
                    }
                    return 8
                }
                return 10
            }
            if (at(4) == 'W'.code) {
                var idx = 7
                while (idx < len && digit(idx) != null) idx++
                if (idx < 9) return idx
                return if (idx % 2 == 0) 7 else 8
            }
            return 8
        }

        /** parse_isoformat_date over the first [end] code points: year, month, day. */
        private fun date(end: Int): Triple<Int, Int, Int> {
            var p = 0
            val year = digits(p, 4)
            p += 4
            val dashes = at(p) == '-'.code
            if (dashes) p++
            if (at(p) == 'W'.code) {
                p++
                val week = digits(p, 2)
                p += 2
                var weekday = 1
                if (p < end) {
                    if (dashes && at(p++) != '-'.code) fail()
                    weekday = digits(p, 1)
                }
                return isoWeek(year, week, weekday)
            }
            val month = digits(p, 2)
            p += 2
            if (dashes && at(p++) != '-'.code) fail()
            val day = digits(p, 2)
            return Triple(year, month, day)
        }

        private fun isoWeek(year: Int, week: Int, weekday: Int): Triple<Int, Int, Int> {
            if (year !in 1..9999) fail()
            if (week !in 1..52) {
                val first = LocalDate.of(year, 1, 1).dayOfWeek.value // Monday 1 … Sunday 7
                val leap = LocalDate.of(year, 1, 1).isLeapYear
                if (!(week == 53 && (first == 4 || (first == 3 && leap)))) fail()
            }
            if (weekday !in 1..7) fail()
            val jan4 = LocalDate.of(year, 1, 4)
            val monday = jan4.minusDays((jan4.dayOfWeek.value - 1).toLong())
            val d = monday.plusDays(((week - 1) * 7 + (weekday - 1)).toLong())
            return Triple(d.year, d.monthValue, d.dayOfMonth)
        }

        /** parse_isoformat_time over [from, end): hour, minute, second, microsecond, the offset's seconds and its
         * microseconds (signed alike). */
        private fun time(from: Int, end: Int): IntArray {
            var tz = from
            while (tz < end && at(tz) != 'Z'.code && at(tz) != '+'.code && at(tz) != '-'.code) tz++
            val (clock, trailing) = hhmmssff(from, tz)
            if (tz >= end) {
                if (trailing) fail() // no zone, so nothing may follow the time
                return intArrayOf(clock[0], clock[1], clock[2], clock[3], 0, 0)
            }
            if (at(tz) == 'Z'.code) {
                if (at(tz + 1) != 0) fail()
                return intArrayOf(clock[0], clock[1], clock[2], clock[3], 0, 0)
            }
            val sign = if (at(tz) == '-'.code) -1 else 1
            val (off, rest) = hhmmssff(tz + 1, end)
            if (rest) fail()
            // Its fields aren't checked one by one: the offset, whole, is less than a day either way (timezone's).
            val seconds = off[0] * 3600 + off[1] * 60 + off[2]
            if (seconds * 1_000_000L + off[3] >= 86_400_000_000L) fail()
            return intArrayOf(clock[0], clock[1], clock[2], clock[3], sign * seconds, sign * off[3])
        }

        /**
         * parse_hh_mm_ss_ff over [from, end): HH[:?MM[:?SS[{.,}f…]]] as hour, minute, second and microsecond, and
         * whether C's reading saw more before [end] (its return of 1): a component's two digits, then one character
         * more taken, the end coming right after it ending the time (one character before a zone is let be, a
         * decimal mark there is no time), and after six digits of a fraction, the rest let be up to a zone.
         */
        private fun hhmmssff(from: Int, end: Int): Pair<IntArray, Boolean> {
            val out = IntArray(4)
            var p = from
            var colons = true
            var i = 0
            var fraction = false
            while (i < 3) {
                if (p + 2 > end) fail()
                out[i] = digits(p, 2)
                p += 2
                val c = at(p)
                p++
                if (i == 0) colons = c == ':'.code
                if (p >= end) {
                    if (c == '.'.code || c == ','.code) fail()
                    return out to (c != 0)
                }
                if (colons && c == ':'.code) {
                    if (i == 2) fail()
                    i++
                    continue
                }
                if (c == '.'.code || c == ','.code) {
                    if (i < 2) fail()
                    fraction = true
                    break
                }
                if (colons) fail()
                p-- // no separators: the character is the next component's
                i++
            }
            check(fraction || i == 3)
            val count = minOf(6, end - p)
            if (count <= 0) fail()
            var micro = digits(p, count)
            for (k in count until 6) micro *= 10
            p += count
            while (digit(p) != null) p++
            out[3] = micro
            return out to (at(p) != 0)
        }

        private fun daysIn(year: Int, month: Int): Int =
            if (month !in 1..12) 31 else LocalDate.of(if (year in 1..9999) year else 2000, month, 1).lengthOfMonth()
    }
}
