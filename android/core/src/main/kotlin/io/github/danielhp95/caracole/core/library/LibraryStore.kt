package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.library.internal.Removal
import io.github.danielhp95.caracole.core.library.internal.SongKv
import io.github.danielhp95.caracole.core.library.internal.Upsert
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Take
import java.io.File
import java.io.IOException

/**
 * The phone's songs and their folder (filesDir/library), by caracole's rules. The phone has no wanted.txt: the
 * `songs` table is its source of songs, and [add] is the one way a song is added (songs.upsert_song's rules, a song
 * of the phone as a wanted.txt line's on the computer: source "wanted", its identity key its source id), so a song
 * removed ([remove], removal.remove_song's rules) stays removed until it is asked for again, and then comes back new
 * (AGENTS.md's invariant "A removed song stays removed until you ask for it again"). [ensureCurrentKeys] is
 * songs.ensure_current_keys. Every method that writes is called inside Database.write (the plan's §5.5).
 */
class LibraryStore(val libraryDir: File) {
    /**
     * The song of [artist] and [title] (each stripped), new, or the one of its identity key found and given [album],
     * [durationMs] and the variant ([variant], else the one its title names). A new song's artist takes the
     * library's spelling when it differs in case alone, so the artist keeps one folder; a tombstone of its key goes.
     * [now] (a stored time) is when it is added. IllegalArgumentException for no artist, or a [now] that is no time.
     */
    fun add(db: Db, artist: String, title: String, album: String? = null, durationMs: Long? = null,
            variant: String? = null, now: String): SongRow {
        val stamp = Stamps.stampOf(now)
        val names = Py.strip(artist)
        require(names.isNotEmpty()) { "a song needs at least one artist" }
        val key = Normalize.identityKey(names, Py.strip(title))
        val added = Upsert.upsertSong(db, listOf(artist), title, album, durationMs, isrc = null, source = SongKv.WANTED,
                                      sourceId = key, addedAt = stamp, now = stamp, variant = variant)
        return Songs.byId(db, added.id) ?: error("song ${added.id} added and gone")
    }

    /**
     * removal.remove_song's rules on the phone: in one savepoint the song's tombstone (a tombstone of its key gaining
     * its source ids and the later time), its record deleted with its versions and files' rows, and the kv kept
     * under its id (songs._PER_SONG_KV) and its first-seen time; then the files caracole wrote in its folder, and the
     * folder, and its artist's, once empty. The tombstone, or null when the library has no song of [key].
     */
    fun remove(db: Db, key: String, now: String): RemovedRow? {
        Rekey.ensure(db, Stamps.now())
        val song = Songs.byKey(db, key) ?: return null
        val stamp = Stamps.stampOf(now) // as peer_sync._remove_song reads its time: only for a song to remove
        return Removal.remove(db, libraryDir, Removal.plan(db, libraryDir, song), stamp).tombstone
    }

    /** songs.ensure_current_keys: songs and tombstones re-keyed once at a KEY_VERSION change (kv songs:key_version);
     * how many songs were re-keyed or merged. */
    fun ensureCurrentKeys(db: Db): Int = Rekey.ensure(db, Stamps.now())

    /** libraryDir/<artist>/<title>, library.song_folder's names. */
    fun folderOf(song: SongRow): File {
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        return File(File(libraryDir, artist), title)
    }

    /** The file [name] of the song's folder: a name a folder can hold (Take.checkedName, else UnitError), under
     * [folderOf], never through a link: IOException when the artist's or the song's folder, or the file, is a
     * symbolic link or no folder. */
    fun fileOf(song: SongRow, name: String): File {
        Take.checkedName(name)
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        var at = libraryDir.toPath()
        for ((i, part) in listOf(artist, title, name).withIndex()) {
            at = at.resolve(part)
            val attrs = LibraryFiles.entry(at) ?: break
            if (attrs.isSymbolicLink || (i < 2 && !attrs.isDirectory)) {
                throw IOException("${listOf(artist, title, name).take(i + 1).joinToString("/")} is " +
                                  (if (attrs.isSymbolicLink) LibraryFiles.LINK else "not a folder"))
            }
        }
        return File(folderOf(song), name)
    }
}
