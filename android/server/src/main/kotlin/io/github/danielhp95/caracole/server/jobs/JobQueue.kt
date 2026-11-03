package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.stub
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.JsonObject

/** A job to queue: its stages (name, label) as the page shows them, and what it runs. */
data class JobSpec(val title: String, val key: String, val kind: String, val stages: List<Pair<String, String>>,
                   val display: String = "", val songId: Long? = null, val join: Boolean = true,
                   val run: suspend (JobContext) -> Unit)

/** What a running job tells its view. */
interface JobContext {
    fun stage(name: String, state: String, detail: String = "")
    fun say(line: String)
    fun outcome(value: JsonObject)
    val isCancelled: Boolean
}

/** A job queued, running or over. */
class Job internal constructor(val id: Int, val spec: JobSpec) {
    val state: String get() = TODO("lane jobs")
    fun asJson(): JsonObject = TODO("lane jobs")
}

/** web/jobs.py on the phone: one worker, one job at a time (lane jobs). */
class JobQueue(scope: CoroutineScope, val limit: Int = 20, val keep: Int = 100) {
    /** The job, and whether it is new (false: a waiting job of the same key that joins). */
    fun submit(spec: JobSpec): Pair<Job, Boolean> = TODO("lane jobs")
    fun job(id: Int): Job? = TODO("lane jobs")

    /** Every job the queue remembers (none until the lane lands). */
    fun snapshot(): List<Job> = stub("lane jobs") { emptyList() }
    fun cancel(id: Int): Job? = TODO("lane jobs")
    suspend fun await(id: Int): Job = TODO("lane jobs")

    /** Told true as the queue gets busy and false as it goes idle (the app's foreground service listens). */
    var onBusy: (Boolean) -> Unit = {}
}
