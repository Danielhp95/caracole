package io.github.danielhp95.caracole.core.songbooks

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow

/** songbook.SongbookError: songbooks.toml (phone_songbooks) can't be read, or a change to it can't be made; the
 * message says why, in songbook.py's words. */
class SongbookError(message: String) : Exception(message)

/** version.Setting: a songbook's setting for a song, its parts as songbook.check_setting keeps them. :core's, so the
 * songbooks and the viewer (viewer.version.Setting) share one type. */
data class Setting(val key: String? = null, val mode: String? = null, val capo: Int? = null,
                   val instrument: String? = null)

/** songbook.SongbookSong: a songbook's entry, its "Artist - Title" and the setting it carries, if any. */
data class SongbookSong(val text: String, val setting: Setting? = null)

/** songbook.Songbook: a songbook, its name and its songs in order. */
data class Songbook(val name: String, val songs: List<SongbookSong> = emptyList()) {
    /** Its songs' "Artist - Title", in order. */
    val texts: List<String> get() = songs.map { it.text }
}

/**
 * songbook.py's names, entries and writers on the phone, over phone_songbooks (SongbookStore): each writer is called
 * inside Database.write and refuses with songbook.py's words ([SongbookError]) (lane songbook-writers; [set]'s check
 * of a setting, lane songbook-entries).
 */
object Songbooks {
    fun checkName(name: String): String = TODO("lane songbook-writers")
    fun nameKey(name: String): String = TODO("lane songbook-writers")
    /** songbook._folder_key. */
    fun folderKey(name: String): String = TODO("lane songbook-writers")
    fun entryKeys(text: String): Set<String> = TODO("lane songbook-writers")
    fun sameEntry(a: String, b: String): Boolean = TODO("lane songbook-writers")
    /** The library's song an entry names, by its keys alone, never by a search. */
    fun findEntrySong(db: Db, text: String): SongRow? = TODO("lane songbook-writers")
    /** songbook.load_songbooks: every songbook, in its place. */
    fun all(db: Db): List<Songbook> = TODO("lane songbook-writers")
    /** songbook.find_songbook: the songbook of this name, in any case. */
    fun find(books: List<Songbook>, name: String): Songbook? = TODO("lane songbook-writers")
    fun make(db: Db, name: String, entries: List<String>): Songbook = TODO("lane songbook-writers")
    fun add(db: Db, name: String, entries: List<String>): List<String> = TODO("lane songbook-writers")
    fun remove(db: Db, name: String, entries: List<String>): List<String> = TODO("lane songbook-writers")
    fun move(db: Db, name: String, entry: String, position: Int): Int = TODO("lane songbook-writers")
    /** songbook.set_song_setting, its setting checked by [problem] (check_setting through the viewer's
     * Versions.settingProblem, which :core can't see). */
    fun set(db: Db, name: String, entry: String, setting: Setting?, problem: (Setting) -> String?): Unit =
        TODO("lane songbook-entries")
    /** songbook.songbooks_listing: the songbooks of [books] whose entries name [song], each found as
     * [findEntrySong] finds it, never by a search (get.py's songbooks stage; SongbookEntries' songs_to_get). */
    fun listing(db: Db, books: List<Songbook>, song: SongRow): List<Songbook> = TODO("lane songbook-entries")
    fun rename(db: Db, name: String, new: String): Songbook = TODO("lane songbook-writers")
    fun delete(db: Db, name: String): Songbook = TODO("lane songbook-writers")
}
