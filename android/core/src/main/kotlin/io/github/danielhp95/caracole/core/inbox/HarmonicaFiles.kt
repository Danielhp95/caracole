package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import java.math.BigInteger

/** inbox.HarmonicaFile: a harmonica tab caracole keeps for a song (`harmonica-N.txt`, harptabs_fetch.py): its name,
 * where it is (relative to the library), its N, the key its page's Key chip names and the harp its harp chip names
 * ("Diatonic", "Chromatic"), each null where it names none. */
data class HarmonicaFile(val songId: Long, val name: String, val path: String, val number: Int,
                         val key: String? = null, val harp: String? = null) {
    /** Its page, written beside it at render time: "harmonica-1.html" (inbox.HarmonicaFile.page). */
    val page: String get() = HarmonicaFiles.page(name) ?: ""
}

/**
 * inbox.harmonica_files and harmonica_page, :core's, so every reader shares one port: the phone's render (a viewer's
 * `harmonicaTabs` and the tabs' pages: phone-render, whose port this file is), the library's cards (library-cards) and
 * a harmonica tab's readings (versions-harmonica).
 */
object HarmonicaFiles {
    /** inbox.HARMONICA_KIND: a kept tab's version's kind. */
    const val KIND = "harmonica"

    /** inbox.HARMONICA_FILE: a harmonica tab caracole kept (`\d` Python's: any decimal digit). */
    val FILE: Regex = PyRegex.compile("""harmonica-(\d+)\.txt""")

    /** inbox.HARMONICA_PAGE: its page, written beside it. */
    val PAGE: Regex = PyRegex.compile("""harmonica-(\d+)\.html""")

    /** A version's `raw` member [name] where json_extract gives text, as Python's `isinstance(…, str)` keeps it: a
     * JSON string's value, an object's or an array's JSON (a number or a boolean is no text, nor is null). */
    private fun text(name: String) =
        "CASE WHEN json_valid(v.raw) AND json_type(v.raw, '$.$name') IN ('text', 'object', 'array') " +
            "THEN json_extract(v.raw, '$.$name') END"

    /** inbox.harmonica_files: the harmonica tabs caracole keeps, of the song [songId] or every song's; by song, then
     * N (a stable sort, as Python's, of the files in SQLite's order). */
    fun of(db: Db, songId: Long? = null): List<HarmonicaFile> {
        val sql = StringBuilder("SELECT f.song_id, f.name, f.path, ${text("key")}, ${text("harp")} " +
                                    "FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?")
        val args = mutableListOf<Any?>(KIND)
        if (songId != null) {
            sql.append(" AND f.song_id = ?")
            args.add(songId)
        }
        val found = db.query(sql.toString(), *args.toTypedArray()) { row ->
            val name = row.text(1)!!
            val m = PyRe.fullmatch(FILE, name) ?: return@query null
            val n = PyInt.parse(m.groupValues[1]) ?: return@query null
            n to HarmonicaFile(row.long(0)!!, name, row.text(2)!!, clamped(n), row.text(3), row.text(4))
        }.filterNotNull()
        return found.sortedWith(compareBy<Pair<BigInteger, HarmonicaFile>> { it.second.songId }.thenBy { it.first })
            .map { it.second }
    }

    /** inbox.harmonica_page: the page of the harmonica tab [name] ("harmonica-1.txt" → "harmonica-1.html"), or null
     * for a name that is no kept tab's. The page keeps the tab's digits as written, as Python's f-string of its
     * group does. */
    fun page(name: String): String? = PyRe.fullmatch(FILE, name)?.let { "harmonica-${it.groupValues[1]}.html" }

    /** A tab's N as an Int, its order kept by the whole number (Python's int has no bound). */
    private fun clamped(n: BigInteger): Int = if (n.bitLength() < 32) n.toInt() else Int.MAX_VALUE
}
