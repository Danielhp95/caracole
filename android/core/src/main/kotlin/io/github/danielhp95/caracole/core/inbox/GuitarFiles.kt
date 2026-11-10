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
 * inbox.guitar_files, :core's, so every reader shares one port: the Guitar Pro page (guitar-alphatab, whose
 * declaration this was), a viewer's `guitar` (phone-render, which ported the query first, since every viewer of a song
 * that keeps a Guitar Pro file lists it), the library's cards (library-cards) and a set list's `guitar` mark
 * (songbook-entries).
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

    /** inbox.guitar_files: the files caracole keeps, `guitar-N.<ext>` recorded for a version of either kind, of the
     * song [songId] or every song's, or the one at [path]; by song, then N (Python's int, of any size), then name (in
     * code points). */
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
        val found = db.query(sql.toString(), *args.toTypedArray()) { row ->
            val name = row.text(1)!!
            val m = PyRe.fullmatch(KEPT, name) ?: return@query null
            if (PyText.lower(m.groupValues[2]) !in EXTENSIONS) return@query null
            val n = PyInt.parse(m.groupValues[1]) ?: return@query null
            n to GuitarFile(row.long(0)!!, name, row.text(2)!!, clamped(n))
        }.filterNotNull()
        return found.sortedWith(compareBy<Pair<BigInteger, GuitarFile>> { it.second.songId }.thenBy { it.first }
                                    .thenBy(Py.CODE_POINT_ORDER) { it.second.name })
            .map { it.second }
    }

    /** A file's N as an Int, its order kept by the whole number (Python's int has no bound). */
    private fun clamped(n: BigInteger): Int = if (n.bitLength() < 32) n.toInt() else Int.MAX_VALUE
}
