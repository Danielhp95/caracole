package io.github.danielhp95.caracole.core.py

/** unicodedata.east_asian_width, from caracole/unicode/east_asian_width.txt (`start end width` runs, N left out;
 * tests/test_conformance_unicode.py writes it from Python's own answers), loaded on first use: PyUnicode.eastAsianWidth. */
internal object EastAsianWidth {
    private val NAMES = listOf("N", "Na", "W", "F", "H", "A")

    private val table = CodePointTable.ofRuns(UnicodeTables.read("east_asian_width.txt").flatMap { (a, b, name) ->
        val i = NAMES.indexOf(name)
        check(i > 0) { "east_asian_width.txt names a width caracole doesn't know: $name" }
        listOf(UnicodeTables.hex(a), UnicodeTables.hex(b), i)
    }.toIntArray())

    /** The width of [cp]: "N" beyond the code points too. */
    fun of(cp: Int): String = NAMES[table[cp]]
}
