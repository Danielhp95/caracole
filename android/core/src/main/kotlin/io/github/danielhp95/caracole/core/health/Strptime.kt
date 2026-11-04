package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
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
 *   (`str.isdecimal`, [PyUnicode.isDecimal]) and a bracket an ASCII one;
 * - each field's value `int()` of its digits ([PyInt]), and then `datetime`'s checks: a year of 1 to 9999, a day its
 *   month has, no second 60 or 61.
 *
 * Anything else is Python's ValueError, here an [IllegalArgumentException].
 */
internal object Strptime {
    /** strftime("%Y-%m-%dT%H:%M:%SZ") of [instant] in UTC, to the second, its fraction dropped: [Stamps.stamp]. */
    fun format(instant: Instant): String =
        Stamps.stamp((instant.epochSecond + EPOCH_SECONDS) * 1_000_000L + instant.nano / 1000)

    /** 1970-01-01T00:00:00Z in seconds after 0001-01-01T00:00:00, the start of [Stamps]' count. */
    private const val EPOCH_SECONDS = 62_135_596_800L

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

    // --- the regex, by hand -------------------------------------------------------------------------------------------

    /** One character of an alternative: a set of ASCII characters, or any decimal digit ([DIGIT]). */
    private class One(val chars: String?) {
        fun takes(cp: Int): Boolean = if (chars == null) PyUnicode.isDecimal(cp) else cp < 128 && cp.toChar() in chars
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

    /** int() of a field's text, a space before its digits ignored. */
    private fun value(cps: IntArray, from: Int, to: Int): Int =
        PyInt.parse(String(cps, from, to - from))!!.intValueExact()

    private fun daysIn(year: Int, month: Int): Int = when (month) {
        2 -> if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) 29 else 28
        4, 6, 9, 11 -> 30
        else -> 31
    }
}
