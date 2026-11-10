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
 * filed from the inbox or downloaded from gtptabs.com; [path] where it is, relative to the library. */
data class GuitarFile(val songId: Long, val name: String, val path: String, val number: Int) {
    /** inbox.GuitarFile.in_browser: whether the Guitar Pro page shows it ([GuitarFiles.BROWSER_EXTENSIONS]): not a
     * Power Tab file. */
    val inBrowser: Boolean get() = PyText.lower(PyPath.suffix(name)) in GuitarFiles.BROWSER_EXTENSIONS
}

/**
 * inbox.guitar_files, :core's, so every reader shares one port: the Guitar Pro page (guitar-alphatab, whose port this
 * file is), a viewer's `guitar` (phone-render), the library's cards (library-cards) and a set list's `guitar` mark
 * (songbook-entries). Held by vectors/web/guitar.jsonl's `caracole.inbox.guitar_files` records (GuitarReplay).
 */
object GuitarFiles {
    /** inbox.GUITAR_FILE_KINDS: the kinds of version a kept Guitar Pro or Power Tab file is recorded under. */
    val KINDS: List<String> = listOf("guitar-pro", "power")

    /** inbox.GP_EXTENSIONS: a Guitar Pro or Power Tab file's extensions, in lower case. */
    val EXTENSIONS: List<String> = listOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")

    /** inbox.BROWSER_EXTENSIONS: the files the Guitar Pro page draws. */
    val BROWSER_EXTENSIONS: Set<String> = setOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp")

    /** inbox._KEPT_GUITAR, as Python's re reads it (its `\d` a digit of any script). */
    private val KEPT by lazy { PyRegex.compile("""guitar-(\d+)(\.[A-Za-z0-9]+)""") }

    /**
     * inbox.guitar_files: the files caracole keeps, `guitar-N.<ext>` recorded for a version of either kind, of the
     * song [songId] or every song's, or the one at [path]; by song, then N, then name (in code points, as Python
     * compares str). N is `int()`'s of its digits, of any script (`guitar-٧.gp4` is 7); past Python's 4300 digits,
     * its ValueError, an IllegalArgumentException. Where Kotlin holds less than Python: a name whose N passes an Int,
     * which caracole never writes (it numbers from 1, the lowest free), is left out.
     */
    fun of(db: Db, songId: Long? = null, path: String? = null): List<GuitarFile> {
        val sql = StringBuilder("SELECT f.song_id, f.name, f.path FROM files f JOIN versions v ON v.id = f.version_id ")
            .append("WHERE v.kind IN (").append(KINDS.joinToString(", ") { "?" }).append(")")
        val args = ArrayList<Any?>(KINDS)
        if (songId != null) {
            sql.append(" AND f.song_id = ?")
            args.add(songId)
        }
        if (path != null) {
            sql.append(" AND f.path = ?")
            args.add(path)
        }
        val rows = db.query(sql.toString(), *args.toTypedArray()) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
        val found = ArrayList<GuitarFile>()
        for ((song, name, at) in rows) {
            val m = PyRe.fullmatch(KEPT, name) ?: continue
            if (PyText.lower(m.groupValues[2]) !in EXTENSIONS) continue
            val number = number(m.groupValues[1])
            if (number.bitLength() >= Int.SIZE_BITS) continue
            found.add(GuitarFile(song, name, at, number.toInt()))
        }
        return found.sortedWith(compareBy<GuitarFile> { it.songId }.thenBy { it.number }
                                    .then { a, b -> Py.CODE_POINT_ORDER.compare(a.name, b.name) })
    }

    /** int() of a name's digits, of any script; Python's ValueError past its 4300 digits. */
    private fun number(digits: String): BigInteger = PyInt.parse(digits) ?: throw IllegalArgumentException(
        "Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion: value has " +
            "${Py.len(digits)} digits; use sys.set_int_max_str_digits() to increase the limit")
}
