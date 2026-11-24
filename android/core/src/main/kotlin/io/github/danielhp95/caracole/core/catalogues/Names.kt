package io.github.danielhp95.caracole.core.catalogues

import java.time.DateTimeException
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.Instant

/** A catalogue file's name read: the schema of the database it was exported from, and the minute it was made (UTC). */
data class Named(val schema: Int, val at: Instant)

/**
 * catalogues.py's `read_name`: `indexes-s<schema>-<yyyymmdd>T<hhmm>Z.sqlite.gz`, the schema one ASCII digit or more
 * with no leading zero, the stamp a real date (year 1 or later) and time in UTC; any other name (`indexes.json`, a
 * `.next`, `indexes2-…`, a 13th month, a 24:00) is none. Read by hand, ASCII alone: no regex's `\d`.
 */
object Names {
    private const val PREFIX = "indexes-s"
    private const val SUFFIX = "Z.sqlite.gz"

    fun read(name: String): Named? {
        if (!name.startsWith(PREFIX) || !name.endsWith(SUFFIX)) return null
        val middle = name.substring(PREFIX.length, name.length - SUFFIX.length) // "17-20261124T0312"
        val dash = middle.indexOf('-')
        if (dash < 0) return null
        val schemaText = middle.substring(0, dash)
        val stamp = middle.substring(dash + 1)
        if (schemaText.isEmpty() || schemaText.length > 9 || !schemaText.all(::ascii)) return null
        if (schemaText.length > 1 && schemaText[0] == '0') return null
        if (stamp.length != 13 || stamp[8] != 'T') return null
        val date = stamp.substring(0, 8)
        val time = stamp.substring(9)
        if (!date.all(::ascii) || !time.all(::ascii)) return null
        val year = date.substring(0, 4).toInt()
        if (year < 1) return null
        return try {
            val at = LocalDateTime.of(year, date.substring(4, 6).toInt(), date.substring(6, 8).toInt(),
                                      time.substring(0, 2).toInt(), time.substring(2, 4).toInt())
            Named(schemaText.toInt(), at.toInstant(ZoneOffset.UTC))
        } catch (e: DateTimeException) {
            null
        }
    }

    private fun ascii(c: Char) = c in '0'..'9'
}
