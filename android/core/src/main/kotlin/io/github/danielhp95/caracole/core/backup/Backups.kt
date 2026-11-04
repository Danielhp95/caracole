package io.github.danielhp95.caracole.core.backup

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.OutputStream
import java.time.Instant

/** backup.Backup: a copy in the folder, its file, when it was made (by its name), its label and size. */
data class Backup(val file: File, val at: Instant, val label: String?, val size: Long)

/**
 * The phone's backups (lane alerts-backups): the library tables, as the take's before-sync backup makes them, and the
 * kept files by SHA-256 under `stateDir/backups/blobs/`, labels `by-hand`, `daily` and `before-sync`, three of each.
 * A restore keeps this side's own records through [restore]'s `keep` and `putBack`.
 */
object Backups {
    fun make(db: Db, lib: LibraryStore, stateDir: File, now: Instant, label: String): File? =
        TODO("lane alerts-backups")
    fun list(stateDir: File): List<Backup> = TODO("lane alerts-backups")
    fun restore(database: Database, lib: LibraryStore, file: File, keep: (Db) -> JsonObject,
                putBack: (Db, JsonObject) -> Unit): Unit = TODO("lane alerts-backups")
    fun exportTo(file: File, out: OutputStream): Unit = TODO("lane alerts-backups")
}
