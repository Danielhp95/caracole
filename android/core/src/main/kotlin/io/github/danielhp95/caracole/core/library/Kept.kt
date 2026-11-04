package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import java.nio.file.Path

/** library.py's kept files: written atomically (never mode 0600), recorded in `files` by their SHA-256. */
object Kept {
    fun keepFile(db: Db, lib: LibraryStore, song: SongRow, versionId: Long, name: String, data: ByteArray,
                 rank: Int, now: String): Boolean = TODO("lane library-writes")
    fun keptAlready(db: Db, songId: Long, sha256: String): Boolean = TODO("lane library-writes")
    fun holds(db: Db, lib: LibraryStore, song: SongRow, name: String, sha256: String): Boolean = TODO("lane library-writes")
    fun dropFile(db: Db, lib: LibraryStore, song: SongRow, name: String): Unit = TODO("lane library-writes")
    fun writeAtomic(path: Path, data: ByteArray): String = TODO("lane library-writes")
}
