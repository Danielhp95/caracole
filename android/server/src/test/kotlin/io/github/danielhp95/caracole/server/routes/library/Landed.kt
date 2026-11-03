package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.JobQueue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import org.junit.Assume
import java.io.File
import java.nio.file.Files

/**
 * Phase A only (the plan's §7.0): whether the lanes these routes stand on have landed (sync-units, sync-take, jobs,
 * song-names). A test that needs them calls [assume] first, and is skipped, not failed, while one of them still
 * answers `TODO("lane …")`. Once they have all merged into main, this assumes nothing; delete it then, with its calls.
 */
object Landed {
    private val missing: String? by lazy {
        val dir = Files.createTempDirectory("landed").toFile()
        val scope = CoroutineScope(Job())
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Compare.ownId(db)
                    Units.libraryState(db)
                    Take.checkedName("sheet.txt")
                    LibraryStore(File(dir, "library")).ensureCurrentKeys(db)
                }
            }
            JobQueue(scope).job(1)
            SongNames.clean("Soda Stereo - De Música Ligera")
            null
        } catch (e: NotImplementedError) {
            e.message
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
    }

    fun assume() = Assume.assumeTrue("waiting on: $missing", missing == null)
}
