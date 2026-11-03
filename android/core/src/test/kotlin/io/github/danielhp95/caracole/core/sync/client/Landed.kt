package io.github.danielhp95.caracole.core.sync.client

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Assume
import java.io.File
import java.nio.file.Files

/**
 * Phase A only (the plan's §7.0): whether the lanes this lane's tests stand on have landed. A test that needs them
 * calls [assume] first, and is skipped, not failed, while one of them still answers `TODO("lane …")`. Once sync-units
 * and sync-take have merged into main, this assumes nothing; delete it then, with its calls.
 */
object Landed {
    private val missing: String? by lazy {
        val dir = Files.createTempDirectory("landed").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Compare.ownId(db)
                    Units.libraryState(db)
                    Compare.order(Compare.compare(emptyMap(), emptyMap(), null))
                    Take.checkedName("sheet.txt")
                    LibraryStore(File(dir, "library")).ensureCurrentKeys(db)
                }
            }
            null
        } catch (e: NotImplementedError) {
            e.message
        } finally {
            dir.deleteRecursively()
        }
    }

    fun assume() = Assume.assumeTrue("waiting on: $missing", missing == null)
}
