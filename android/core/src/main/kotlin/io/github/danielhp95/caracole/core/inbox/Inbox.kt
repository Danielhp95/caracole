package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Numbering
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.internal.writes.Place
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import kotlinx.serialization.json.JsonObject
import java.math.BigInteger
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path

/** What filing a file came to. */
sealed interface Filed {
    /** Kept for the song [songId] as [name] (its `guitar-N.<ext>`, `score-N.<ext>`). */
    data class Kept(val songId: Long, val name: String) : Filed

    /** A file caracole keeps that the library lost, written back in its place: [paths], each relative to the library
     * as `files.path` holds it (one a song: the copies of several songs the bytes are). */
    data class PutBack(val paths: List<String>) : Filed

    /** The library holds that very file already ([Inbox.held] names the copy). */
    data object Duplicate : Filed

    /** No song fits it, or its copy's place holds other bytes now (nothing is replaced): it waits. */
    data object Unmatched : Filed
}

/**
 * inbox.py's filing of one entry, for a file shared to the app: what `file_inbox` does with one file of `_inbox/`,
 * Python's answer to the byte (vectors/inbox/file.jsonl), the rows and the files it writes those of the computer after
 * the same filing, so the song's sync unit agrees.
 *
 * A Guitar Pro or Power Tab file ([GuitarFiles.EXTENSIONS]) or a score ([SCORE_EXTENSIONS]) is placed by its name,
 * "Artist - Title.gp5" (or the title alone, when one song has it), among every song that isn't ignored, and kept as
 * the song's `guitar-N.<ext>` or `score-N.<ext>` (Numbering: the lowest number no file holds, so none is ever
 * replaced) under the song's one `inbox` version of its kind. A file with the bytes of one caracole keeps is that file
 * again, when its name is no other song's: written back where the library lost it, a duplicate where the library
 * holds it, left waiting where its place holds other bytes now. MusicXML's header is never read on the phone: a score
 * is placed by its name alone (the plan's §11, Q12).
 */
object Inbox {
    /** inbox.SCORE_EXTENSIONS: what MuseScore downloads, its own format, MusicXML (compressed or not), PDF and MIDI. */
    val SCORE_EXTENSIONS: Set<String> = setOf(".mscz", ".mxl", ".musicxml", ".pdf", ".mid", ".midi")

    /** inbox.SCORE_KIND: a kept score's version's kind. */
    const val SCORE_KIND = "score"

    /** inbox.MATCH_CUTOFF: music.Names.score is exact from 82 up. */
    const val MATCH_CUTOFF = 90

    /** The provider of the files filed from the inbox: caracole can't tell where you got the file. */
    const val PROVIDER = "inbox"

    private val VERSION = PyRegex.compile("""(?i)\(\s*ver\.?\s*(\d+)[^)]*\)""")
    private val PARENS = PyRegex.compile("""\s*\([^)]*\)""")

    /** Whether inbox.py files anything of a name's extension (its suffix in lower case, str.lower's). */
    fun keeps(name: String): Boolean = extension(name).let { it in GuitarFiles.EXTENSIONS || it in SCORE_EXTENSIONS }

    /**
     * inbox.file_inbox for one file, [name] with [data]: kept for its song, put back where the library lost it, a
     * duplicate, or unmatched (see [Filed]). [now] is the time it is filed (a stored time: the inbox version's
     * `fetched_at`, the file's `created_at`). Called inside Database.write; library.SharedFolder and a write's
     * IOException propagate, as file_inbox's do.
     */
    fun file(db: Db, lib: LibraryStore, name: String, data: ByteArray, now: String): Filed {
        val ext = extension(name)
        if (ext !in GuitarFiles.EXTENSIONS && ext !in SCORE_EXTENSIONS) return Filed.Unmatched
        lib.ensureCurrentKeys(db)  // list_songs'
        val found = downloadSong(db, name)
        val copies = copies(db, Canonical.sha256Hex(data))
        if (copies.isNotEmpty() && (found == null || copies.any { it.songId == found.id })) {
            // A file caracole kept, by its bytes: the song's own when its name says so, else any song's.
            val mine = copies.filter { found == null || it.songId == found.id }
            val (putBack, held) = again(db, lib, mine, data, now)
            return when {
                putBack.isNotEmpty() -> Filed.PutBack(putBack)
                held -> Filed.Duplicate
                else -> Filed.Unmatched  // its place holds other bytes now: nothing is replaced, and the file waits
            }
        }
        if (found == null) return Filed.Unmatched
        val (versionId, kept, rank) = place(db, lib, ext, found, now)
        return if (Kept.keepFile(db, lib, found, versionId, kept, data, rank, now)) Filed.Kept(found.id, kept)
               else Filed.Duplicate
    }

    /**
     * The file caracole keeps that [name] with [data] is a duplicate of ([Filed.Duplicate]): the first of its copies
     * (by id) the library holds as recorded, of the song the name is of when that song keeps one, else of any song;
     * null when the library holds none. Only reads.
     */
    fun held(db: Db, lib: LibraryStore, name: String, data: ByteArray): KeptFile? {
        val found = downloadSong(db, name)
        val copies = copies(db, Canonical.sha256Hex(data))
        val mine = copies.filter { it.songId == found?.id }.ifEmpty { copies }
        return mine.firstOrNull { Kept.holds(Place.under(lib, it.path), it.sha256, data.size.toLong()) }
    }

    /**
     * Whether filing [name] with [data] would do anything now ([file] would answer other than [Filed.Unmatched]):
     * a song fits it, or it is a file caracole keeps that the library holds or lost. Only reads: the phone asks it of
     * the files that wait, after a sync or a lookup, before it queues their filing.
     */
    fun fits(db: Db, lib: LibraryStore, name: String, data: ByteArray): Boolean {
        if (!keeps(name)) return false
        val found = downloadSong(db, name)
        val copies = copies(db, Canonical.sha256Hex(data))
        if (copies.isNotEmpty() && (found == null || copies.any { it.songId == found.id })) {
            return copies.filter { found == null || it.songId == found.id }.any { copy ->
                Kept.holds(Place.under(lib, copy.path), copy.sha256, data.size.toLong()) ||
                    (!lexists(Place.under(lib, copy.path)) && !lexists(placeOf(db, lib, copy).second.second))
            }
        }
        return found != null
    }

    /**
     * inbox.parse_download_name: `"Artist - Title (ver 2).gp5"` → ("Artist", "Title", 2). Bracketed words go, the
     * version first, but not an original in another script ("Jay Chou (周杰倫)"); the version is Python's int of any
     * size (IllegalArgumentException, Python's ValueError, past int()'s 4300 digits).
     */
    fun parseDownloadName(name: String): Triple<String?, String, BigInteger?> {
        var stem = stem(name)
        val m = PyRe.search(VERSION, stem)
        val version = m?.let { number(it.groupValues[1]) }
        stem = PyRe.sub(VERSION, stem) { "" }
        stem = PyText.strip(PyRe.sub(PARENS, stem) { g -> if (Normalize.hasOtherScript(g.value)) g.value else "" })
        val at = stem.indexOf(" - ")
        if (at >= 0) {
            val artist = PyText.strip(stem.substring(0, at))
            val title = PyText.strip(stem.substring(at + 3))
            if (artist.isNotEmpty() && title.isNotEmpty()) return Triple(artist, title, version)
        }
        return Triple(null, stem, version)
    }

    /**
     * inbox._match: the song a download is of, among [songs] (list_songs' order): by identity, else the closest
     * (music.Names, at [MATCH_CUTOFF] or more), the first of the closest; a name without an artist is only trusted
     * when exactly one song fits.
     */
    fun match(artist: String?, title: String, songs: List<SongRow>): SongRow? {
        val named = !artist.isNullOrEmpty()
        if (named) {
            val key = Normalize.identityKey(artist!!, title)
            songs.firstOrNull { it.key == key }?.let { return it }
        }
        val own = MusicNames.of(artist ?: "", title)
        var best: SongRow? = null
        var bestScore = 0.0
        var fits = 0
        for (song in songs) {
            val other = MusicNames.of(song.artist, song.title)
            val score = if (named) own.score(other) else own.titleScore(other)
            if (score < MATCH_CUTOFF) continue
            fits++
            if (best == null || score > bestScore) {
                best = song
                bestScore = score
            }
        }
        if (best == null || (!named && fits > 1)) return null
        return best
    }

    /** inbox._download_song, by its name alone: the song the download [name] is of, among every song not ignored;
     * null when it is no song's. Only reads. */
    fun downloadSong(db: Db, name: String): SongRow? {
        val songs = Songs.list(db).filter { it.status != "ignored" }
        val (artist, title, _) = parseDownloadName(name)
        return match(artist, title, songs)
    }

    // --- placing it ---------------------------------------------------------------------------------------------

    /** inbox._inbox_version: the song's one version of [kind] for the files filed from the inbox (`score`,
     * `guitar-pro` or `power`). */
    private fun inboxVersion(db: Db, song: SongRow, kind: String, now: String): Long = Versions.upsert(
        db, PROVIDER, kind, song.id, "guitar", kind, rating = 0.0, votes = 0, version = 1, label = null, url = "",
        raw = JsonObject(emptyMap()), now = now,
    )

    /** inbox._place: the version a download of the song is kept for, its name in the song's folder and its rank (its
     * number). */
    private fun place(db: Db, lib: LibraryStore, ext: String, song: SongRow, now: String): Triple<Long, String, Int> {
        if (ext in SCORE_EXTENSIONS) {
            val n = Numbering.score(db, lib, song, ext)
            return Triple(inboxVersion(db, song, SCORE_KIND, now), "score-$n$ext", n)
        }
        val n = Numbering.guitar(db, lib, song)
        return Triple(inboxVersion(db, song, if (ext == ".ptb") "power" else "guitar-pro", now), "guitar-$n$ext", n)
    }

    /** inbox._copies: the files caracole keeps whose recorded bytes are these, whether or not the library still
     * holds them, by id. */
    private fun copies(db: Db, sha: String): List<KeptFile> =
        db.query("SELECT id, version_id, song_id, name, path, sha256, kept_rank FROM files WHERE sha256 = ? ORDER BY id",
                 sha) {
            KeptFile(it.long(0)!!, it.long(1)!!, it.long(2)!!, it.text(3)!!, it.text(4)!!, it.text(5)!!,
                     it.long(6)!!.toInt())
        }

    /**
     * inbox._again: a download that is a file caracole kept: each of [copies] the library lost (nothing at its place
     * now) written back there, and listed (relative to the library); and whether the library still holds one as
     * recorded. A copy whose place holds other bytes (yours, since) is left alone.
     */
    private fun again(db: Db, lib: LibraryStore, copies: List<KeptFile>, data: ByteArray,
                      now: String): Pair<List<String>, Boolean> {
        val putBack = ArrayList<String>()
        var held = false
        for (copy in copies) {
            val (song, place) = placeOf(db, lib, copy)
            val at = Place.under(lib, copy.path)
            if (Kept.holds(at, copy.sha256, data.size.toLong())) {
                held = true
            } else if (!lexists(at) && !lexists(place.second)) {
                if (Kept.keepFile(db, lib, song, copy.versionId, copy.name, data, copy.keptRank, now)) {
                    putBack += place.first
                }
            }
        }
        return putBack to held
    }

    /** The song of a kept file, and where its name goes in the song's folder now (`song_dir / safe_name(name)`). */
    private fun placeOf(db: Db, lib: LibraryStore, copy: KeptFile): Pair<SongRow, Pair<String, Path>> {
        val song = Songs.byId(db, copy.songId) ?: throw NoSuchElementException("no song ${copy.songId}")
        return song to Place.file(lib, song, copy.name)
    }

    /** os.path.lexists: anything at [path], a link too (a dangling one among them). */
    private fun lexists(path: Path): Boolean = Files.exists(path, LinkOption.NOFOLLOW_LINKS)

    // --- names, as pathlib reads them ---------------------------------------------------------------------------

    /** `Path(name).suffix.lower()`: a name's extension, str.lower's. */
    fun extension(name: String): String = PyText.lower(PyPath.suffix(name))

    /** PurePosixPath(name).stem, Python 3.14's: its name less its last suffix, unless what is left is dots alone. */
    fun stem(name: String): String {
        val last = name.split('/').lastOrNull { it.isNotEmpty() && it != "." } ?: ""
        val dot = last.lastIndexOf('.')
        if (dot >= 0) {
            val stem = last.substring(0, dot)
            if (stem.trimStart('.').isNotEmpty()) return stem
        }
        return last
    }

    /** int(digits): any decimal digit of any script, Python's int of any size; past its 4300 digits, its ValueError
     * in its words. */
    private fun number(digits: String): BigInteger = PyInt.parse(digits) ?: throw IllegalArgumentException(
        "Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion: value has " +
            "${digits.codePointCount(0, digits.length)} digits; use sys.set_int_max_str_digits() to increase the limit")
}
