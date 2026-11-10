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
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncEngine
import io.github.danielhp95.caracole.mirror.SyncError
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runInterruptible
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
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
     * With [probe] (the sync on Wi-Fi), no caracole at the address ([SyncError.noCaracole]: no address, nothing
     * answering, or something else answering, such as a Wi-Fi login page) does nothing, says nothing, and keeps
     * the last outcome; Sync now says it. [stopped] is asked between two files and between two chunks of one.
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
            // The library page's search answers your songs with the copy's cards: none of a list gone.
            Caracole.started()?.search?.invalidate()
            Outcome(System.currentTimeMillis(), true, report.summary())
        } catch (e: Exception) {
            // Anything, the unexpected too (SyncError.Unexpected): a failed outcome, never "Syncing…" left up.
            val error = SyncError.of(e)
            if (probe && error.noCaracole) {
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

    /** "just now", "3 min ago", "2 h ago", "4 days ago". */
    internal fun ago(ms: Long): String {
        val minutes = ms / 60_000
        return when {
            minutes < 1 -> "just now"
            minutes < 60 -> "$minutes min ago"
            minutes < 48 * 60 -> "${minutes / 60} h ago"
            else -> "${minutes / (24 * 60)} days ago"
        }
    }

    fun size(context: Context, bytes: Long): String = Formatter.formatShortFileSize(context, bytes)

    /**
     * Settings' Test: the computer at [typed] (the address as typed) asked what it holds, changing nothing
     * (SyncRoutes.tested, `POST /sync/test`'s answer), said in its words ("studio answered: 96 songs, 3 songbooks,
     * its indexes read 02/11/26"); or why it can't be, in the words the sheet says it (no address, not an address,
     * nothing answering, this very phone). Blocks: called off the main thread.
     */
    fun tested(context: Context, typed: String): String = try {
        if (typed.isBlank()) throw SyncError.NoAddress()
        val answer = routes(Caracole.phone(context)).tested(io.github.danielhp95.caracole.core.sync.SyncEngine.peerAddress(typed))
        (answer["said"] as? JsonPrimitive)?.contentOrNull ?: answer.toString()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Refused) {
        e.message.orEmpty()
    } catch (e: PeerError) {
        e.message.orEmpty()
    } catch (e: Exception) {
        // Anything, the unexpected too: said on the screen, never a crash.
        SyncError.of(e).let { it.message ?: it.javaClass.simpleName }
    }

    /** The phone's sync routes: SyncRoutes among the phone's route modules (waiting on sync-phone, whose Phone.sync
     * names it). */
    internal fun routes(phone: Phone): SyncRoutes = phone.modules.filterIsInstance<SyncRoutes>().single()
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
