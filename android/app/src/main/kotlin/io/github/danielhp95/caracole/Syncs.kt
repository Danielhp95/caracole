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
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.Outcomes
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
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
 * taken or given, each conflict left as it is on both sides), awaited, its line what it did ([said]: never "Up to date"
 * with a unit left, nor where its indexes were of another schema); then a notification only for the conflicts it
 * left ([conflictsLeft], "2 songs changed on both sides: tap to choose"), whose tap opens the sheet, and that
 * notification taken back by a sync that left none. No address, nothing answering there, or something else answering
 * (a Wi-Fi login page): it does nothing and says nothing.
 */
object Syncs {
    private const val WIFI = "caracole-sync-wifi"
    const val PROBE = "probe"

    /** The phone's caracole as the unattended sync asks it: [alone] queues its sync of an address (null: one with that
     * address waits or runs already), [await] waits for a job's end, and [job] reads it as it goes. */
    class Unattended(val alone: (String) -> Job?, val await: suspend (Int) -> Job, val job: (Int) -> Job? = { null })

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
     * [Caracole.status]; the conflicts it left notified ([Notifications.conflictsLeft]), or the last such notification
     * taken back when it left none ([Notifications.noConflictsLeft]). Null when it did nothing.
     */
    suspend fun run(context: Context, probe: Boolean): Outcome? {
        val app = context.applicationContext
        return run(Settings(app), probe, Caracole.http(), phone = {
            val phone = Caracole.phone(app)
            Unattended(alone = phone.sync::alone, await = phone.queue::await, job = phone.queue::job)
        }, cleared = { Notifications.noConflictsLeft(app) }) { count, songs -> Notifications.conflictsLeft(app, count, songs) }
    }

    /**
     * [run]'s own, over [settings]: the probe ([ask], the computer's state read through [http]; a [SyncError] or a
     * [PeerError] when no caracole answers), then the phone's sync ([phone], asked only once one does) queued and
     * awaited, and [notify] told how many conflicts it left and whether all are songs, when it left any, else
     * [cleared]. A sync whose job ended done with a stage failed (the copy of the computer's pages, say: the engine
     * goes on past it) is a failed outcome, in that stage's words. While it runs, [Caracole.status] says the stage it
     * is at and what that says (Working.doing), read every [followMs].
     */
    internal suspend fun run(settings: Settings, probe: Boolean, http: Http,
                             ask: (ServerAddress) -> Unit = { PeerClient(it, http).state(null) },
                             phone: () -> Unattended, cleared: () -> Unit = {}, followMs: Long = FOLLOW_MS,
                             notify: (Int, Boolean) -> Unit): Outcome? {
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
            val done = coroutineScope {
                val following = launch {
                    while (true) {
                        side.job(job.id)?.takeIf { it.active }?.let { status.value = SyncState.Running(Working.doing(it)) }
                        delay(followMs)
                    }
                }
                try {
                    side.await(job.id)
                } finally {
                    following.cancel()
                }
            }
            if (done.state == Job.DONE) {
                val (left, songs) = conflictsLeft(done.outcome)
                if (left > 0) notify(left, songs) else cleared()
                val failed = done.stages.firstOrNull { it.state == Job.FAILED }
                if (failed == null) Outcome(System.currentTimeMillis(), true,
                                            said(done.outcome, Outcomes.indexesSkipped(done.stages)))
                else Outcome(System.currentTimeMillis(), false, failedStage(failed.label, failed.detail, done.outcome))
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

    /**
     * What a sync did, in the bar's line's words: "Up to date" when nothing changed, "Up to date · 1 taken, 2 given";
     * with conflicts left, "1 taken, 2 changed on both sides: tap Sync to choose"; with units left for another reason
     * (a file that won't come, a unit changed since compared, one the computer's take left), "1 taken · 1 not synced:
     * tap Sync to see why" (the sheet's left section says why): never "Up to date" with anything left. [indexes], why
     * the index stage took and gave none (the computer's database of another schema, Outcomes.indexesSkipped), said
     * after the rest in place of "Up to date", and before what to do: the line ends with that.
     */
    internal fun said(outcome: JsonObject?, indexes: String? = null): String {
        val what = done(outcome)
        // What to do last, after what it did and why no index went.
        val ask = when {
            conflictsLeft(outcome).first > 0 -> TO_CHOOSE
            notSynced(outcome) > 0 -> TO_SEE_WHY
            else -> ""
        }
        val said = listOf(what, indexes.orEmpty()).filter { it.isNotEmpty() }.joinToString(" · ")
        return when {
            ask.isNotEmpty() -> "$said$ask"
            indexes != null -> said
            what.isEmpty() -> UP_TO_DATE
            else -> "$UP_TO_DATE · $what"
        }
    }

    /** The units [outcome] left for another reason than a conflict unsettled: every `left` entry but those
     * [conflictsLeft] counts. */
    private fun notSynced(outcome: JsonObject?): Int =
        ((outcome?.get("left") as? JsonArray)?.size ?: 0) - conflictsLeft(outcome).first

    /** "1 taken, 2 given, 2 changed on both sides · 1 not synced", or "" when it did nothing. */
    private fun done(outcome: JsonObject?): String {
        val other = notSynced(outcome)
        return listOf(what(outcome), if (other > 0) "$other not synced" else "").filter { it.isNotEmpty() }
            .joinToString(" · ")
    }

    /** "1 taken, 2 given, 2 changed on both sides", or "" when it did nothing. */
    private fun what(outcome: JsonObject?): String {
        fun count(name: String) = (outcome?.get(name) as? JsonArray)?.size ?: 0
        val left = conflictsLeft(outcome).first
        return listOfNotNull(
            count("taken").takeIf { it > 0 }?.let { "$it taken" },
            count("given").takeIf { it > 0 }?.let { "$it given" },
            left.takeIf { it > 0 }?.let { "$it changed on both sides" },
        ).joinToString(", ")
    }

    /** A sync that went on past a stage that failed: "Copying the computer's pages failed: No answer from … (1 taken)". */
    internal fun failedStage(label: String, detail: String, outcome: JsonObject?): String {
        val what = done(outcome)
        return "$label failed" + (if (detail.isEmpty()) "" else ": $detail") + (if (what.isEmpty()) "" else " ($what)")
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
        val answer = Caracole.phone(context).sync.tested(SyncEngine.peerAddress(typed))
        (answer["said"] as? JsonPrimitive)?.contentOrNull ?: answer.toString()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // Anything, the unexpected too: said on the screen, never a crash.
        words(e)
    } catch (e: VirtualMachineError) {
        throw e
    } catch (e: Throwable) {
        // An Error too: the phone's caracole that can't start (its SQLite's native library that won't load).
        why(e)
    }

    /** How often the screen's line reads the unattended sync's stage. */
    private const val FOLLOW_MS = 500L

    private const val SONG = "song/"
    private const val UP_TO_DATE = "Up to date"
    private const val TO_CHOOSE = ": tap Sync to choose"
    private const val TO_SEE_WHY = ": tap Sync to see why"
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
