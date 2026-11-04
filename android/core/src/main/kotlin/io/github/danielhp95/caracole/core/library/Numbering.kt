package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db

/** inbox.py's numbering: a kept file's lowest number no file of the song holds, in `files` or in its folder. */
object Numbering {
    fun guitar(db: Db, lib: LibraryStore, song: SongRow): Int = TODO("lane library-writes")
    fun harmonica(db: Db, lib: LibraryStore, song: SongRow): Int = TODO("lane library-writes")
    fun gametab(db: Db, lib: LibraryStore, song: SongRow): Int = TODO("lane library-writes")
    fun score(db: Db, lib: LibraryStore, song: SongRow, ext: String): Int = TODO("lane library-writes")
}
