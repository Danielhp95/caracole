package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import java.math.BigInteger

/** inbox.GuitarFile: a Guitar Pro or Power Tab file caracole keeps for a song (`guitar-N.<ext>`, recorded in `files`),
 * filed from the inbox or downloaded from gtptabs.com; [path] where it is, relative to the library. [number] is N as
 * an Int, Int.MAX_VALUE past one (a name caracole never writes: it numbers from 1, the lowest free); [wholeNumber] is
 * Python's int of it, of any size, which the Guitar Pro page's label names. */
data class GuitarFile(val songId: Long, val name: String, val path: String, val number: Int) {
    /** inbox.GuitarFile.in_browser: whether the Guitar Pro page shows it ([GuitarFiles.BROWSER_EXTENSIONS]): not a
     * Power Tab file. */
    val inBrowser: Boolean get() = PyText.lower(PyPath.suffix(name)) in GuitarFiles.BROWSER_EXTENSIONS

    /** GuitarFile.number as Python holds it: `int()` of the name's digits, of any script, of any size. */
    val wholeNumber: BigInteger get() = GuitarFiles.wholeNumberOf(name) ?: number.toBigInteger()
}

/**
 * inbox.guitar_files, :core's, so every reader shares one port: the Guitar Pro page (guitar-alphatab, whose
 * declaration this was), a viewer's `guitar` (phone-render, which ported the query first, since every viewer of a song
 * that keeps a Guitar Pro file lists it), the library's cards (library-cards) and a set list's `guitar` mark
 * (songbook-entries). Held by vectors/web/guitar.jsonl's `caracole.inbox.guitar_files` records (GuitarReplay).
 */
object GuitarFiles {
    /** inbox.GUITAR_FILE_KINDS: the kinds of version a kept Guitar Pro or Power Tab file is recorded under. */
    val KINDS: List<String> = listOf("guitar-pro", "power")

    /** inbox.BROWSER_EXTENSIONS: the files the Guitar Pro page draws. */
    val BROWSER_EXTENSIONS: Set<String> = setOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp")

    /** inbox.GP_EXTENSIONS: a Guitar Pro file's, and a Power Tab file's. */
    val EXTENSIONS: Set<String> = setOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")

    /** inbox._KEPT_GUITAR: a kept file's name (`\d` Python's: any decimal digit). */
    private val KEPT: Regex = PyRegex.compile("""guitar-(\d+)(\.[A-Za-z0-9]+)""")

    /**
     * inbox.guitar_files: the files caracole keeps, `guitar-N.<ext>` recorded for a version of either kind, of the
     * song [songId] or every song's, or the one at [path]; by song, then N (Python's int, of any size), then name (in
     * code points). N is `int()`'s of its digits, of any script (`guitar-٧.gp4` is 7); past Python's 4300 digits, its
     * ValueError, an IllegalArgumentException.
     */
    fun of(db: Db, songId: Long? = null, path: String? = null): List<GuitarFile> {
        val sql = StringBuilder("SELECT f.song_id, f.name, f.path FROM files f JOIN versions v ON v.id = f.version_id " +
                                    "WHERE v.kind IN (${KINDS.joinToString(", ") { "?" }})")
        val args = mutableListOf<Any?>(*KINDS.toTypedArray())
        if (songId != null) {
            sql.append(" AND f.song_id = ?")
            args.add(songId)
        }
        if (path != null) {
            sql.append(" AND f.path = ?")
            args.add(path)
        }
        val rows = db.query(sql.toString(), *args.toTypedArray()) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
        val found = ArrayList<Pair<BigInteger, GuitarFile>>()
        for ((song, name, at) in rows) {
            val m = PyRe.fullmatch(KEPT, name) ?: continue
            if (PyText.lower(m.groupValues[2]) !in EXTENSIONS) continue
            val n = number(m.groupValues[1])
            found.add(n to GuitarFile(song, name, at, clamped(n)))
        }
        return found.sortedWith(compareBy<Pair<BigInteger, GuitarFile>> { it.second.songId }.thenBy { it.first }
                                    .thenBy(Py.CODE_POINT_ORDER) { it.second.name })
            .map { it.second }
    }

    /** The N of a kept file's [name], `guitar-N.<ext>`, as Python's int; null for a name of no such shape. */
    internal fun wholeNumberOf(name: String): BigInteger? {
        val m = PyRe.fullmatch(KEPT, name) ?: return null
        return PyInt.parse(m.groupValues[1])
    }

    /** int() of a name's digits, of any script; Python's ValueError past its 4300 digits. */
    private fun number(digits: String): BigInteger = PyInt.parse(digits) ?: throw IllegalArgumentException(
        "Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion: value has " +
            "${Py.len(digits)} digits; use sys.set_int_max_str_digits() to increase the limit")

    /** A file's N as an Int, its order kept by the whole number (Python's int has no bound). */
    private fun clamped(n: BigInteger): Int = if (n.bitLength() < 32) n.toInt() else Int.MAX_VALUE
}
