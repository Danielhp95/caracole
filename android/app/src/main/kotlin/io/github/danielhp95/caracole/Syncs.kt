package io.github.danielhp95.caracole

import android.content.Context
import android.text.format.Formatter
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncError
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.util.concurrent.TimeUnit

/**
 * Sync on Wi-Fi by itself, and Settings' Test. The unattended sync ([run]) is the bar's sync without its sheet: every
 * 6 hours on an unmetered network ([onWifi]), once a caracole answers at the address Settings keeps (the probe: its
 * state read, nothing changed), the phone's own sync job of the three parts (SyncRoutes.alone: each one-sided change
 * taken or given, each conflict left as it is on both sides), awaited; then a notification only for the conflicts it
 * left ([conflictsLeft], "2 songs changed on both sides: tap to choose"), whose tap opens the sheet. No address,
 * nothing answering there, or something else answering (a Wi-Fi login page): it does nothing and says nothing.
 */
object Syncs {
    private const val WIFI = "caracole-sync-wifi"
    const val PROBE = "probe"

    /** The phone's caracole as the unattended sync asks it: [alone] queues its sync of an address (null: one with that
     * address waits or runs already), and [await] waits for a job's end. */
    class Unattended(val alone: (String) -> Job?, val await: suspend (Int) -> Job)

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
     * The unattended sync with the address in the settings ([probe]: Sync on Wi-Fi's, silent when no caracole answers;
     * without, as a test asks it, that said as a failed outcome), its outcome kept ([Settings.lastOutcome]) and told to
     * [Caracole.status]; the conflicts it left notified ([Notifications.conflictsLeft]). Null when it did nothing.
     */
    suspend fun run(context: Context, probe: Boolean): Outcome? {
        val app = context.applicationContext
        return run(Settings(app), probe, Caracole.http(), phone = {
            val phone = Caracole.phone(app)
            val sync = routes(phone)
            Unattended(alone = sync::alone, await = phone.queue::await)
        }) { count, songs -> Notifications.conflictsLeft(app, count, songs) }
    }

    /**
     * [run]'s own, over [settings]: the probe ([ask], the computer's state read through [http]; a [SyncError] or a
     * [PeerError] when no caracole answers), then the phone's sync ([phone], asked only once one does) queued and
     * awaited, and [notify] told how many conflicts it left and whether all are songs, when it left any.
     */
    internal suspend fun run(settings: Settings, probe: Boolean, http: Http,
                             ask: (ServerAddress) -> Unit = { PeerClient(it, http).state(null) },
                             phone: () -> Unattended, notify: (Int, Boolean) -> Unit): Outcome? {
        val status = Caracole.status
        val address = try {
            val server = ServerAddress.parse(settings.server)
            withContext(Dispatchers.IO) { ask(server) }
            SyncEngine.peerAddress(settings.server)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (probe && (e is SyncError || e is PeerError)) return null
            return ended(settings, Outcome(System.currentTimeMillis(), false, words(e)))
        }
        status.value = SyncState.Running(null)
        val outcome = try {
            val side = withContext(Dispatchers.IO) { phone() }
            val job = side.alone(address)
            if (job == null) {
                // A sync with that computer waits or runs already (one from the sheet, say): it is that one's.
                status.value = SyncState.Idle
                return null
            }
            val done = side.await(job.id)
            if (done.state == Job.DONE) {
                val (left, songs) = conflictsLeft(done.outcome)
                if (left > 0) notify(left, songs)
                Outcome(System.currentTimeMillis(), true, said(done.outcome))
            } else {
                Outcome(System.currentTimeMillis(), false, failure(done))
            }
        } catch (e: CancellationException) {
            status.value = SyncState.Idle
            throw e
        } catch (e: Exception) {
            // Anything, the unexpected too: a failed outcome, never "Syncing…" left up.
            Outcome(System.currentTimeMillis(), false, words(e))
        }
        return ended(settings, outcome)
    }

    private fun ended(settings: Settings, outcome: Outcome): Outcome {
        settings.lastOutcome = outcome
        Caracole.status.value = SyncState.Ended(outcome)
        return outcome
    }

    /**
     * The conflicts [outcome] (a sync job's: SyncJson.outcome) left: its `left` entries whose why is a conflict
     * unsettled ([SyncEngine.UNSETTLED]; never a unit left for another reason, such as one changed since the
     * comparison), and whether every one is a song's.
     */
    fun conflictsLeft(outcome: JsonObject?): Pair<Int, Boolean> {
        val left = (outcome?.get("left") as? JsonArray).orEmpty().mapNotNull { entry ->
            val pair = entry as? JsonArray ?: return@mapNotNull null
            val id = (pair.getOrNull(0) as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return@mapNotNull null
            val why = (pair.getOrNull(1) as? JsonPrimitive)?.takeIf { it.isString }?.content
            id.takeIf { why == SyncEngine.UNSETTLED }
        }
        return left.size to left.all { it.startsWith(SONG) }
    }

    /** What a sync did, in the bar's line's words: "1 taken, 2 given, 2 changed on both sides", or "nothing changed". */
    internal fun said(outcome: JsonObject?): String {
        fun count(name: String) = (outcome?.get(name) as? JsonArray)?.size ?: 0
        val left = conflictsLeft(outcome).first
        val parts = listOfNotNull(
            count("taken").takeIf { it > 0 }?.let { "$it taken" },
            count("given").takeIf { it > 0 }?.let { "$it given" },
            left.takeIf { it > 0 }?.let { "$it changed on both sides" },
        )
        return if (parts.isEmpty()) NOTHING else parts.joinToString(", ")
    }

    /** Why [job] failed, as the queue kept it: its last `error: …` line, else its failed stage's words. */
    private fun failure(job: Job): String =
        job.output.lastOrNull { it.startsWith(ERROR_LINE) }?.removePrefix(ERROR_LINE)?.trim()?.ifEmpty { null }
            ?: job.stages.firstOrNull { it.state == Job.FAILED }?.detail?.ifEmpty { null }
            ?: job.state

    private fun words(e: Exception): String = when (e) {
        is PeerError, is Refused -> e.message.orEmpty()
        else -> SyncError.of(e).let { it.message ?: it.javaClass.simpleName }
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
        val answer = routes(Caracole.phone(context)).tested(SyncEngine.peerAddress(typed))
        (answer["said"] as? JsonPrimitive)?.contentOrNull ?: answer.toString()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // Anything, the unexpected too: said on the screen, never a crash.
        words(e)
    }

    /** The phone's sync routes: SyncRoutes among the phone's route modules (waiting on sync-phone, whose Phone.sync
     * names it). */
    internal fun routes(phone: Phone): SyncRoutes = phone.modules.filterIsInstance<SyncRoutes>().single()

    private const val SONG = "song/"
    private const val NOTHING = "nothing changed"
    /** How the phone's queue says what a failed job threw: its last line of output (JobQueue). */
    private const val ERROR_LINE = "error: "
}

/** Sync on Wi-Fi by itself, every 6 hours (input [Syncs.PROBE]): [Syncs.run]. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val probe = inputData.getBoolean(Syncs.PROBE, true)
        Syncs.run(applicationContext, probe)
        // The outcome is kept and shown; a failed sync waits for the next one, in 6 hours or by hand.
        return Result.success()
    }
}
