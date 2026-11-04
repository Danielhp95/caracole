package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.internal.Stamps
import io.github.danielhp95.caracole.core.library.internal.writes.Place
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path

/** library.KeptFile: a row of `files`, a file caracole keeps for a song ([path] relative to the library). */
data class KeptFile(val id: Long, val versionId: Long, val songId: Long, val name: String, val path: String,
                    val sha256: String, val keptRank: Int)

/**
 * library.py's kept files, as the computer keeps them: each written into the song's folder atomically (never mode
 * 0600) and recorded in `files` by its SHA-256, so a song's sync unit (its kept files' hashes) is the computer's after
 * the same writes (vectors/library/writes.jsonl). Every method that writes is called inside Database.write.
 */
object Kept {
    /** library.kept_files: the song's kept files, by name (SQLite's BINARY order). */
    fun keptFiles(db: Db, songId: Long): List<KeptFile> =
        db.query("SELECT id, version_id, song_id, name, path, sha256, kept_rank FROM files WHERE song_id = ? " +
                     "ORDER BY name", songId) {
            KeptFile(it.long(0)!!, it.long(1)!!, it.long(2)!!, it.text(3)!!, it.text(4)!!, it.text(5)!!,
                     it.long(6)!!.toInt())
        }

    /**
     * library.kept_already: whether this version's [data] is the song's kept [name] already, so the files table says,
     * and so the file in the library still is ([holds]): then it needn't be written again, as each rewrite is one
     * more sync on every device.
     */
    fun keptAlready(db: Db, lib: LibraryStore, song: SongRow, versionId: Long, name: String, data: ByteArray): Boolean {
        val sha = Place.sha256(data)
        return keptFiles(db, song.id).any {
            it.name == name && it.versionId == versionId && it.sha256 == sha &&
                holds(Place.under(lib, it.path), sha, data.size.toLong())
        }
    }

    /** library.holds: whether the regular file at [path] holds the bytes whose SHA-256 is [sha256] (not deleted, not
     * cut short, not replaced by a link or anything else); with [size], a file of another length fails unread. */
    fun holds(path: Path, sha256: String, size: Long? = null): Boolean = Place.holds(path, sha256, size)

    /** Whether the file the song keeps as [name] (its `files` row's path) holds the bytes of [sha256]; false when the
     * song keeps no such file. */
    fun holds(db: Db, lib: LibraryStore, song: SongRow, name: String, sha256: String): Boolean {
        val rel = db.one("SELECT path FROM files WHERE song_id = ? AND name = ?", song.id, name) { it.text(0) }
            ?: return false
        return holds(Place.under(lib, rel), sha256)
    }

    /** library.keeper_of: the other song that keeps a file where [name] goes in the song's folder, if any (two songs
     * whose names make one folder: [SharedFolder]). */
    fun keeperOf(db: Db, lib: LibraryStore, song: SongRow, name: String): SongRow? {
        val (rel, _) = Place.file(lib, song, name)
        val other = db.one("SELECT song_id FROM files WHERE path = ? AND song_id != ?", rel, song.id) { it.long(0) }
            ?: return null
        return Songs.byId(db, other) ?: error("song $other keeps $rel and is gone")
    }

    /**
     * library.keep_file: [data] written into the song's folder as `safe_name(name)` and recorded under [name], kept
     * by the version [versionId] at [rank], `created_at` [now] (a stored time, as SQLite's clock stamps Python's);
     * false, with nothing written, when identical bytes are kept already under another name of the song (a
     * duplicate). A file of the same name is replaced. A file another song keeps at that place ([keeperOf]) is never
     * replaced: [SharedFolder], with nothing written. IllegalArgumentException for a [now] that is no time.
     */
    fun keepFile(db: Db, lib: LibraryStore, song: SongRow, versionId: Long, name: String, data: ByteArray,
                 rank: Int, now: String): Boolean {
        val stamp = Stamps.stampOf(now)
        val sha = Place.sha256(data)
        val dup = db.one("SELECT 1 FROM files WHERE song_id = ? AND sha256 = ? AND name != ?", song.id, sha, name) {
            true
        }
        if (dup != null) return false
        keeperOf(db, lib, song, name)?.let { throw SharedFolder(song, it, name) }
        val (rel, path) = Place.file(lib, song, name)
        Place.writeAtomic(path, data)
        db.execute(
            "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                "VALUES (?, ?, ?, ?, ?, ?, ?) " +
                "ON CONFLICT(song_id, name) DO UPDATE SET version_id = excluded.version_id, path = excluded.path, " +
                "sha256 = excluded.sha256, kept_rank = excluded.kept_rank, created_at = excluded.created_at",
            versionId, song.id, name, rel, sha, rank, stamp,
        )
        return true
    }

    /** library.drop_file: the kept file forgotten and deleted from the library (a link in its place is deleted, never
     * followed); nothing for a name the song doesn't keep. */
    fun dropFile(db: Db, lib: LibraryStore, song: SongRow, name: String) {
        val rel = db.one("SELECT path FROM files WHERE song_id = ? AND name = ?", song.id, name) { it.text(0) } ?: return
        val path = Place.under(lib, rel)
        if (Place.entry(path)?.isDirectory == true) throw IOException("$rel: is a folder") // Path.unlink's refusal
        Files.deleteIfExists(path)
        db.execute("DELETE FROM files WHERE song_id = ? AND name = ?", song.id, name)
    }

    /** library.write_atomic: [data] at [path] through a temporary file of a random name, created exclusively and
     * renamed over it, the file and its folder synced (never mode 0600, which would hide it from Syncthing); the
     * bytes' SHA-256. */
    fun writeAtomic(path: Path, data: ByteArray): String = Place.writeAtomic(path, data)
}
