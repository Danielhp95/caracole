package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore

/** What filing a file came to. */
sealed interface Filed {
    /** Kept for the song [songId] as [name] (its `guitar-N.<ext>`, `score-N.<ext>`…). */
    data class Kept(val songId: Long, val name: String) : Filed

    /** Put back where it was staged, as `_inbox/` keeps a file until a song fits: [paths]. */
    data class PutBack(val paths: List<String>) : Filed

    /** The song keeps that very file already. */
    data object Duplicate : Filed

    /** No song fits it. */
    data object Unmatched : Filed
}

/** inbox.py's filing of one entry, for a file shared to the app (lane inbox-share). */
object Inbox {
    fun file(db: Db, lib: LibraryStore, name: String, data: ByteArray, now: String): Filed = TODO("lane inbox-share")
    /** `"Artist - Title (ver 2).gp5"` → ("Artist", "Title", 2). */
    fun parseDownloadName(name: String): Triple<String?, String, Int?> = TODO("lane inbox-share")
}
