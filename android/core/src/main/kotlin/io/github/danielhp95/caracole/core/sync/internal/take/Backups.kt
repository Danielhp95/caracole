package io.github.danielhp95.caracole.core.sync.internal.take

import io.github.danielhp95.caracole.core.backup.internal.BackupTables
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import java.io.File
import io.github.danielhp95.caracole.core.backup.Backups as PhoneBackups

/**
 * The phone's copy of its library before a sync takes anything (the plan's §1 and §5.4): core.backup's backup
 * labelled `before-sync` ([PhoneBackups.BEFORE_SYNC]), `state/backups/before-sync-<UTC time>.sqlite`, the newest
 * [KEEP] kept, none made without free space of twice what it needs; with the library given, its kept files too, by
 * SHA-256. [restore] puts the library's tables' rows back, exactly, and nothing on disk (Take.restore says what that
 * leaves); core.backup's restore is the whole one.
 */
internal object Backups {
    const val KEEP = PhoneBackups.KEEP
    const val FOLDER = PhoneBackups.FOLDER

    /** The library's tables, parents first. */
    val TABLES: List<String> get() = BackupTables.TABLES

    /** The bytes free where a copy goes (a test gives less): core.backup's. */
    var freeSpace: (File) -> Long
        get() = PhoneBackups.freeSpace
        set(value) {
            PhoneBackups.freeSpace = value
        }

    fun make(db: Db, stateDir: File, now: String, store: LibraryStore? = null): File? =
        PhoneBackups.makeAt(db, store, stateDir, now, PhoneBackups.BEFORE_SYNC)

    fun restore(db: Db, backup: File) = BackupTables.restore(db, backup)
}
