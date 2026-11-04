package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

/**
 * The times health.py and commands/_common.py write and read themselves, apart from stamps.py's: a UTC time
 * `strftime("%Y-%m-%dT%H:%M:%SZ")` ([format]: health.py's `_iso`, `_common.run_id_for`, `lookup_requests_used`'s hour
 * and `requests_today`'s midnight) and `datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")` ([parse]: health.py's
 * `_parse`, `_common._last_request`'s fallback), as CPython 3.14's `_strptime` reads it.
 *
 * `_strptime` matches the text with a regex, its fields' alternatives tried in order and backtracked into, case not
 * minded (`t` and `z` read as `T` and `Z`), then needs it read to its end:
 *
 * - `%Y` `\d\d\d\d`; `%m` `1[0-2]|0[1-9]|[1-9]`; `%d` `3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9]`; `%H`
 *   `2[0-3]|[0-1]\d|\d| \d`; `%M` `[0-5]\d|\d`; `%S` `6[0-1]|[0-5]\d|\d`, where `\d` is any decimal digit of any script
 *   (`str.isdecimal`) and a bracket an ASCII one;
 * - each field's value `int()` of its digits, and then `datetime`'s checks: a year of 1 to 9999, a day its month has,
 *   no second 60 or 61.
 *
 * Anything else is Python's ValueError, here an [IllegalArgumentException].
 */
internal object Strptime {
    /** strftime("%Y-%m-%dT%H:%M:%SZ") of [instant] in UTC: to the second, its fraction dropped. */
    fun format(instant: Instant): String {
        val t = instant.atOffset(ZoneOffset.UTC)
        return pad(t.year, 4) + "-" + pad(t.monthValue, 2) + "-" + pad(t.dayOfMonth, 2) + "T" + pad(t.hour, 2) + ":" +
            pad(t.minute, 2) + ":" + pad(t.second, 2) + "Z"
    }

    /** datetime.strptime([value], "%Y-%m-%dT%H:%M:%SZ") made UTC; [IllegalArgumentException] where it raises. */
    fun parse(value: String): Instant {
        val cps = Py.codePoints(value)
        val fields = IntArray(6)
        val end = match(cps, 0, 0, fields) ?: throw IllegalArgumentException("time data does not match format: $value")
        if (end != cps.size) throw IllegalArgumentException("unconverted data remains: $value")
        val year = fields[0]
        val month = fields[1]
        val day = fields[2]
        val second = fields[5]
        if (year !in 1..9999) throw IllegalArgumentException("year must be in 1..9999, not $year")
        if (day > daysIn(year, month)) throw IllegalArgumentException("day $day must be in range for month $month")
        if (second > 59) throw IllegalArgumentException("second must be in 0..59, not $second")
        return LocalDateTime.of(year, month, day, fields[3], fields[4], second).toInstant(ZoneOffset.UTC)
    }

    /** Py_UNICODE_TODECIMAL: a decimal digit's value (any script's: Unicode lays each script's out as 0 to 9 in a
     * row, so a digit's value is its place in the run of digits it is in, counted from that run's first), else -1. */
    fun decimal(cp: Int): Int {
        if (cp in '0'.code..'9'.code) return cp - '0'.code
        if (cp < 128 || !PyUnicode.isDecimal(cp)) return -1
        var first = cp
        while (first > 0 && PyUnicode.isDecimal(first - 1)) first--
        return (cp - first) % 10
    }

    // --- the regex, by hand -------------------------------------------------------------------------------------------

    /** One character of an alternative: a set of ASCII characters, or any decimal digit ([DIGIT]). */
    private class One(val chars: String?) {
        fun takes(cp: Int): Boolean = if (chars == null) decimal(cp) >= 0 else cp < 128 && cp.toChar() in chars
    }

    private val DIGIT = One(null)
    private fun of(chars: String) = One(chars)
    private fun range(from: Char, to: Char) = One((from..to).joinToString(""))

    /** A field's alternatives in the regex's order, or a literal (one alternative of one character). */
    private class Element(val alternatives: List<List<One>>, val field: Int)

    private fun field(index: Int, vararg alternatives: List<One>) = Element(alternatives.toList(), index)
    private fun literal(chars: String) = Element(listOf(listOf(of(chars))), -1)

    private val PATTERN: List<Element> = listOf(
        field(0, listOf(DIGIT, DIGIT, DIGIT, DIGIT)),
        literal("-"),
        field(1, listOf(of("1"), range('0', '2')), listOf(of("0"), range('1', '9')), listOf(range('1', '9'))),
        literal("-"),
        field(2, listOf(of("3"), range('0', '1')), listOf(range('1', '2'), DIGIT), listOf(of("0"), range('1', '9')),
              listOf(range('1', '9')), listOf(of(" "), range('1', '9'))),
        literal("Tt"),
        field(3, listOf(of("2"), range('0', '3')), listOf(range('0', '1'), DIGIT), listOf(DIGIT), listOf(of(" "), DIGIT)),
        literal(":"),
        field(4, listOf(range('0', '5'), DIGIT), listOf(DIGIT)),
        literal(":"),
        field(5, listOf(of("6"), range('0', '1')), listOf(range('0', '5'), DIGIT), listOf(DIGIT)),
        literal("Zz"),
    )

    /** Where the first match of [PATTERN] from its [element]th element at [pos] ends (re.match's backtracking:
     * alternatives in order), its fields' values in [fields]; null for none. */
    private fun match(cps: IntArray, pos: Int, element: Int, fields: IntArray): Int? {
        if (element == PATTERN.size) return pos
        val e = PATTERN[element]
        for (alternative in e.alternatives) {
            if (pos + alternative.size > cps.size) continue
            if (alternative.indices.any { !alternative[it].takes(cps[pos + it]) }) continue
            if (e.field >= 0) fields[e.field] = value(cps, pos, pos + alternative.size)
            match(cps, pos + alternative.size, element + 1, fields)?.let { return it }
        }
        return null
    }

    /** int() of a field's text: its digits' value, a space before them ignored. */
    private fun value(cps: IntArray, from: Int, to: Int): Int {
        var n = 0
        for (i in from until to) if (cps[i] != ' '.code) n = n * 10 + decimal(cps[i])
        return n
    }

    private fun daysIn(year: Int, month: Int): Int = when (month) {
        2 -> if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) 29 else 28
        4, 6, 9, 11 -> 30
        else -> 31
    }

    private fun pad(n: Int, width: Int): String = n.toString().padStart(width, '0')
}
