package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.internal.writes.Place
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import java.math.BigInteger
import java.nio.file.Files
import java.nio.file.NoSuchFileException

/**
 * inbox.py's numbering: the N of a new kept file, the lowest number no file of the song holds, so that no file is ever
 * replaced. A number is taken by a name of the song's files: every kept one's, every one in its folder (put there by
 * hand, say), and every one another song keeps there (two songs whose names make one folder: [SharedFolder]), lost
 * or not. Names are read as inbox.py's patterns read them (Python's `\d`: a digit of any script, `int()` its value).
 */
object Numbering {
    /** inbox.guitar_number: a new `guitar-N.<ext>`'s N; any name that begins `guitar-N.`, in any case and of any
     * extension, takes N. */
    fun guitar(db: Db, lib: LibraryStore, song: SongRow): Int =
        lowestFree(namesTaken(db, lib, song).mapNotNull { PyRe.match(GUITAR, it)?.let(::number) })

    /** inbox.harmonica_number: a new `harmonica-N.txt`'s N (a harmonica tab, harptabs_fetch.py); the tab or its page
     * (`harmonica-N.html`, written beside it) takes N. */
    fun harmonica(db: Db, lib: LibraryStore, song: SongRow): Int =
        lowestFree(namesTaken(db, lib, song).mapNotNull {
            (PyRe.fullmatch(HARMONICA_FILE, it) ?: PyRe.fullmatch(HARMONICA_PAGE, it))?.let(::number)
        })

    /** inbox.gametab_number: a new `gametab-N.txt`'s N (a text tab of game music, gametabs_fetch.py). */
    fun gametab(db: Db, lib: LibraryStore, song: SongRow): Int =
        lowestFree(namesTaken(db, lib, song).mapNotNull { PyRe.fullmatch(GAMETAB_FILE, it)?.let(::number) })

    /** inbox.score_number: a new `score-N<ext>`'s N, the lowest no file of that extension holds ([ext] as `.pdf`,
     * compared with a name's extension in lower case): the formats of one score take one number. */
    fun score(db: Db, lib: LibraryStore, song: SongRow, ext: String): Int =
        lowestFree(namesTaken(db, lib, song).mapNotNull { name ->
            PyRe.fullmatch(SCORE_FILE, name)?.takeIf { Py.asciiLower(it.groupValues[2]) == ext }?.let(::number)
        })

    private val GUITAR = PyRegex.compile("""(?i)guitar-(\d+)\.""")
    private val HARMONICA_FILE = PyRegex.compile("""harmonica-(\d+)\.txt""")
    private val HARMONICA_PAGE = PyRegex.compile("""harmonica-(\d+)\.html""")
    private val GAMETAB_FILE = PyRegex.compile("""gametab-(\d+)\.txt""")
    private val SCORE_FILE = PyRegex.compile("""score-(\d+)(\.[A-Za-z0-9]+)""")

    /** int(group 1): its digits of any script; ValueError past Python's 4300 digits, an IllegalArgumentException. */
    private fun number(m: MatchResult): BigInteger = PyInt.parse(m.groupValues[1])
        ?: throw IllegalArgumentException("Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion")

    /** `next(n for n in itertools.count(1) if n not in taken)`. */
    private fun lowestFree(taken: List<BigInteger>): Int {
        val numbers = taken.toSet()
        var n = 1
        while (BigInteger.valueOf(n.toLong()) in numbers) n++
        return n
    }

    /** inbox._names_taken: the song's kept files' names, the names of the paths kept in its folder (by any song: the
     * folder's own path, then "/", up to "0", the character after "/"), and the names in its folder. */
    private fun namesTaken(db: Db, lib: LibraryStore, song: SongRow): Set<String> {
        val (rel, dir) = Place.folder(lib, song)
        val names = HashSet<String>()
        db.query("SELECT name FROM files WHERE song_id = ?", song.id) { names += it.text(0)!! }
        db.query("SELECT path FROM files WHERE path >= ? AND path < ?", "$rel/", "${rel}0") {
            names += it.text(0)!!.trimEnd('/').substringAfterLast('/')
        }
        try {
            Files.newDirectoryStream(dir).use { entries -> for (entry in entries) names += entry.fileName.toString() }
        } catch (_: NoSuchFileException) {
        }
        return names
    }
}
