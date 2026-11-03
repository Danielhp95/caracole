package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import java.io.File

/** What a take did: the units taken, those left (with why), the songs it wrote, the artists it respelled. */
data class Applied(val taken: List<String>, val left: List<Pair<String, String>>, val songs: List<Long>,
                   val respelled: List<String>, val songbooksChanged: Boolean)

/** peer_sync.apply_units on the phone (lane sync-take). applyUnits and restore are called inside Database.write. */
object Take {
    fun applyUnits(db: Db, store: LibraryStore, source: UnitSource, wanted: List<Pair<String, String?>>,
                   expectedHere: Map<String, String?>, now: String, onUnit: ((String, String) -> Unit)? = null): Applied =
        TODO("lane sync-take")

    /** A full openable database of the library tables, three kept. */
    fun backupBeforeSync(db: Db, stateDir: File, now: String): File? = TODO("lane sync-take")

    /** A backup's library tables back, in one savepoint. */
    fun restore(db: Db, backup: File): Unit = TODO("lane sync-take")

    /** _take_song's file-name rule, else UnitError. */
    fun checkedName(name: String): String = TODO("lane sync-take")
}
