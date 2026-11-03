package io.github.danielhp95.caracole.core.lacuerda

/**
 * Whether stamps.parse reads a stored time, lacuerda_index.complete_at's one question of it: CPython 3.14's C
 * `datetime.fromisoformat` reduced to its yes or no, on the text's UTF-8 bytes as the C reader reads them (IsoTimeTest
 * pins Python's answers):
 *
 * - at least 7 characters; a lone surrogate at 7, 8 or 10 (the first there) read as `T`, and any other no time;
 * - the date: `YYYY-MM-DD`, `YYYYMMDD`, `YYYY-Www[-D]` or `YYYYWww[D]` in ASCII digits, a real day of years 1 to 9999
 *   (a week date by ISO's calendar);
 * - then any one character, where the date's shape puts it, and the time: `HH[:MM[:SS[.f…]]]` or `HHMM[SS[.f…]]`
 *   (`,` as `.`, digits past six skipped), then `Z` or an offset `±HH[:MM[:SS[.f…]]]` whose fields are unchecked but
 *   whose total is under a day, one stray character before it let by;
 * - `24:00` with nothing after it the next day's midnight, where that is a day.
 *
 * A time it reads whose UTC leaves years 1 to 9999 ("0001-01-01T00:00:00+01:00") raises Python's OverflowError, which
 * index_state doesn't catch; here it reads. core.index.Stamps (lane index-transfer) reads the same, the time itself
 * too: once both are on main, this one goes.
 */
internal object IsoTime {
    fun reads(text: String): Boolean {
        val points = text.codePoints().toArray()
        if (points.size < 7) return false
        for (pos in intArrayOf(7, 8, 10)) {
            if (pos >= points.size) break
            if (points[pos] in SURROGATES) {
                points[pos] = 'T'.code
                break
            }
        }
        if (points.any { it in SURROGATES }) return false // PyUnicode_AsUTF8AndSize refuses it
        val b = String(points, 0, points.size).toByteArray(Charsets.UTF_8)
        val n = b.size
        val separator = separator(b, n)
        if (separator < 0) return false
        val date = date(b, separator) ?: return false
        var (year, month, day) = date
        var clock = Clock(0, 0, 0, 0, 0)
        if (n > separator) clock = time(b, separator + utf8Length(at(b, separator)), n) ?: return false
        var hour = clock.hour
        if (hour == 24 && month in 1..12 && day <= daysIn(year, month)) {
            if (clock.minute != 0 || clock.second != 0 || clock.micro != 0) return false
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
        return year in 1..9999 && month in 1..12 && day in 1..daysIn(year, month) &&
            hour in 0..23 && clock.minute in 0..59 && clock.second in 0..59
    }

    private val SURROGATES = 0xD800..0xDFFF

    /** The byte at [i], or 0 past the end, the C string's terminator. */
    private fun at(b: ByteArray, i: Int): Int = if (i in b.indices) b[i].toInt() and 0xFF else 0

    private fun isDigit(c: Int) = c in 0x30..0x39

    private fun utf8Length(lead: Int): Int = when {
        lead < 0x80 -> 1
        lead < 0xE0 -> 2
        lead < 0xF0 -> 3
        else -> 4
    }

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

    /** _find_isoformat_datetime_separator: where the date ends; -1 for nowhere. */
    private fun separator(b: ByteArray, n: Int): Int {
        if (n == 7) return 7
        if (at(b, 4) == '-'.code) {
            if (at(b, 5) != 'W'.code) return 10
            if (n > 8 && at(b, 8) == '-'.code) {
                if (n == 9) return -1
                return if (n > 10 && isDigit(at(b, 10))) 8 else 10
            }
            return 8
        }
        if (at(b, 4) == 'W'.code) {
            var i = 7
            while (i < n && isDigit(at(b, i))) i++
            if (i < 9) return i
            return if (i % 2 == 0) 7 else 8
        }
        return 8
    }

    /** parse_isoformat_date over the first [length] bytes: year, month and day, a week date made one; null for none. */
    private fun date(b: ByteArray, length: Int): Triple<Int, Int, Int>? {
        var p = 0
        val year = digits(b, p, 4) ?: return null
        p += 4
        val dashes = at(b, p) == '-'.code
        if (dashes) p++
        if (at(b, p) == 'W'.code) {
            p++
            val week = digits(b, p, 2) ?: return null
            p += 2
            var weekday = 1
            if (p < length) {
                if (dashes && at(b, p++) != '-'.code) return null
                weekday = digits(b, p, 1) ?: return null
            }
            if (year !in 1..9999) return null
            if (week !in 1..52) {
                val first = weekdayOf(ordinal(year, 1, 1))
                if (week != 53 || !(first == 3 || (first == 2 && leap(year)))) return null
            }
            if (weekday !in 1..7) return null
            return ymd(year, week1Monday(year) + (week - 1) * 7L + weekday - 1)
        }
        val month = digits(b, p, 2) ?: return null
        p += 2
        if (dashes && at(b, p++) != '-'.code) return null
        val day = digits(b, p, 2) ?: return null
        return Triple(year, month, day)
    }

    /** What parse_hh_mm_ss_ff read: its code (1: something follows before the end; below 0: no time) and fields. */
    private class Clock(val code: Int, val hour: Int, val minute: Int, val second: Int, val micro: Int)

    private val CORRECTION = intArrayOf(100000, 10000, 1000, 100, 10)

    /** parse_hh_mm_ss_ff over [start, end). */
    private fun clock(b: ByteArray, start: Int, end: Int): Clock {
        val values = IntArray(3)
        var p = start
        var colons = true
        fun bad(code: Int) = Clock(code, values[0], values[1], values[2], 0)
        var i = 0
        while (i < 3) {
            values[i] = digits(b, p, 2) ?: return bad(-3)
            p += 2
            val c = at(b, p)
            p++
            if (i == 0) colons = c == ':'.code
            if (c == '.'.code || c == ','.code) {
                if (i < 2 || p >= end) return bad(-3)
                break
            }
            when {
                p >= end -> return Clock(if (c != 0) 1 else 0, values[0], values[1], values[2], 0)
                colons && c == ':'.code -> if (i == 2) return bad(-4)
                !colons -> p--
                else -> return bad(-4)
            }
            i++
        }
        val count = minOf(end - p, 6)
        var micro = digits(b, p, count) ?: return bad(-3)
        p += count
        if (count < 6) micro *= CORRECTION[count - 1]
        while (isDigit(at(b, p))) p++
        return Clock(if (at(b, p) != 0) 1 else 0, values[0], values[1], values[2], micro)
    }

    /** parse_isoformat_time over [start, end), its offset as timezone() takes it (under a day); null for no time. */
    private fun time(b: ByteArray, start: Int, end: Int): Clock? {
        var zone = start
        while (true) {
            val c = at(b, zone)
            if (c == 'Z'.code || c == '+'.code || c == '-'.code) break
            zone++
            if (zone >= end) break
        }
        val clock = clock(b, start, zone)
        if (clock.code < 0) return null
        if (zone == end) return clock.takeIf { it.code != 1 }
        if (at(b, zone) == 'Z'.code) return clock.takeIf { at(b, zone + 1) == 0 }
        val tz = clock(b, zone + 1, end)
        if (tz.code != 0) return null
        val offset = ((tz.hour * 3600L) + tz.minute * 60L + tz.second) * 1_000_000L + tz.micro
        return clock.takeIf { offset < 86_400_000_000L }
    }

    // --- the proleptic Gregorian calendar, as datetime counts it ----------------------------------------------------

    private val DAYS_BEFORE = intArrayOf(0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)

    private fun leap(year: Int) = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)

    private fun daysIn(year: Int, month: Int): Int = when (month) {
        2 -> if (leap(year)) 29 else 28
        4, 6, 9, 11 -> 30
        else -> 31
    }

    /** _ymd2ord: day 1 is 0001-01-01. */
    private fun ordinal(year: Int, month: Int, day: Int): Long {
        val y = year - 1L
        return y * 365 + Math.floorDiv(y, 4L) - Math.floorDiv(y, 100L) + Math.floorDiv(y, 400L) +
            DAYS_BEFORE[month] + (if (month > 2 && leap(year)) 1 else 0) + day
    }

    /** Monday 0 to Sunday 6. */
    private fun weekdayOf(ordinal: Long): Int = Math.floorMod(ordinal + 6, 7L).toInt()

    /** _isoweek1monday. */
    private fun week1Monday(year: Int): Long {
        val first = ordinal(year, 1, 1)
        val weekday = weekdayOf(first)
        return first - weekday + (if (weekday > 3) 7 else 0)
    }

    /** _ord2ymd for a day of ISO year [isoYear]'s weeks, which is in that year or the one either side. */
    private fun ymd(isoYear: Int, ordinal: Long): Triple<Int, Int, Int> {
        val year = when {
            ordinal < ordinal(isoYear, 1, 1) -> isoYear - 1
            ordinal >= ordinal(isoYear + 1, 1, 1) -> isoYear + 1
            else -> isoYear
        }
        var month = 12
        while (month > 1 && ordinal(year, month, 1) > ordinal) month--
        return Triple(year, month, (ordinal - ordinal(year, month, 1) + 1).toInt())
    }
}
