package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import java.io.File

/** The phone's songs and their folder: songs.upsert_song's and removal.remove_song's rules (lane sync-take). Every
 * method that writes is called inside Database.write. */
class LibraryStore(val libraryDir: File) {
    fun add(db: Db, artist: String, title: String, album: String? = null, durationMs: Long? = null,
            variant: String? = null, now: String): SongRow = TODO("lane sync-take")

    /** removal.remove_song's rules on the phone. */
    fun remove(db: Db, key: String, now: String): RemovedRow? = TODO("lane sync-take")

    /** songs.ensure_current_keys: songs and tombstones re-keyed at a KEY_VERSION change. */
    fun ensureCurrentKeys(db: Db): Int = TODO("lane sync-take")

    /** libraryDir/<SafeName.songFolder>. */
    fun folderOf(song: SongRow): File = TODO("lane sync-take")

    /** A checked name under [folderOf], never through a link. */
    fun fileOf(song: SongRow, name: String): File = TODO("lane sync-take")
}
