package io.github.danielhp95.caracole

import android.content.Context
import android.text.format.Formatter
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncEngine
import io.github.danielhp95.caracole.mirror.SyncError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runInterruptible
import java.util.concurrent.TimeUnit

/** Runs a sync and keeps its outcome; schedules them through WorkManager. */
object Syncs {
    private const val NOW = "caracole-sync-now"
    private const val WIFI = "caracole-sync-wifi"
    const val PROBE = "probe"

    /** Syncs now, in the background: the worker outlives the screen that asked. */
    fun now(context: Context) {
        Caracole.status.value = SyncState.Running(null)
        WorkManager.getInstance(context)
            .enqueueUniqueWork(NOW, ExistingWorkPolicy.KEEP, OneTimeWorkRequestBuilder<SyncWorker>().build())
    }

    /** Syncs every 6 hours on an unmetered network, when caracole answers ([on]), or never by itself. */
    fun onWifi(context: Context, on: Boolean) {
        val work = WorkManager.getInstance(context)
        if (!on) {
            work.cancelUniqueWork(WIFI)
            return
        }
        val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).build())
            .setInputData(workDataOf(PROBE to true))
            .build()
        work.enqueueUniquePeriodicWork(WIFI, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    /**
     * Syncs with the address in the settings, telling [Caracole.status] how far it is, and keeps the outcome.
     * With [probe] (the sync on Wi-Fi), a server that doesn't answer, or no address, does nothing and says
     * nothing. [stopped] is asked between two files.
     */
    fun run(context: Context, probe: Boolean, stopped: () -> Boolean = { false }): Outcome? {
        val settings = Settings(context)
        val status = Caracole.status
        status.value = SyncState.Running(null)
        val outcome = try {
            val address = ServerAddress.parse(settings.server)
            val engine = SyncEngine(Caracole.mirror(context), Caracole.http())
            // The list is asked for inside the sync, once it holds the lock: never one fetched before another
            // sync (on Wi-Fi, or Sync now) ended.
            val report = engine.sync(address, progress = { status.value = SyncState.Running(it) }, cancelled = stopped)
            Outcome(System.currentTimeMillis(), true, report.summary())
        } catch (e: Exception) {
            // Anything, the unexpected too (SyncError.Unexpected): a failed outcome, never "Syncing…" left up.
            val error = SyncError.of(e)
            if (probe && (error is SyncError.NoAnswer || error is SyncError.NoAddress || error is SyncError.BadAddress)) {
                status.value = SyncState.Idle
                return null
            }
            Outcome(System.currentTimeMillis(), false, error.message ?: error.javaClass.simpleName)
        }
        settings.lastOutcome = outcome
        status.value = SyncState.Ended(outcome)
        return outcome
    }

    /** "Synced 3 min ago: 12 files new, 2 removed", or "Sync failed 3 min ago: No answer from …". */
    fun describe(outcome: Outcome?, now: Long = System.currentTimeMillis()): String? {
        outcome ?: return null
        val ago = ago(now - outcome.at)
        return if (outcome.ok) "Synced $ago: ${outcome.text}" else "Sync failed $ago: ${outcome.text}"
    }

    private fun ago(ms: Long): String {
        val minutes = ms / 60_000
        return when {
            minutes < 1 -> "just now"
            minutes < 60 -> "$minutes min ago"
            minutes < 48 * 60 -> "${minutes / 60} h ago"
            else -> "${minutes / (24 * 60)} days ago"
        }
    }

    fun size(context: Context, bytes: Long): String = Formatter.formatShortFileSize(context, bytes)
}

/** A sync, by hand ("Sync now") or on Wi-Fi every 6 hours (input [Syncs.PROBE]). */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val probe = inputData.getBoolean(Syncs.PROBE, false)
        runInterruptible(Dispatchers.IO) { Syncs.run(applicationContext, probe) { isStopped } }
        // The outcome is kept and shown; a failed sync waits for the next one, by hand or in 6 hours.
        return Result.success()
    }
}
