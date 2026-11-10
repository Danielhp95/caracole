package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.SongFacts
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * What keeps the phone's caracole working while its job queue has a job to do (a sync, an add, a removal, a lookup):
 * the line its foreground service ([SyncService]) says ([line]), and that service started ([start]) as the line comes.
 *
 * [busy] is the queue's `onBusy`, told under the queue's lock: it only sets a flag. While the queue is busy, the jobs
 * ([jobs], the queue's snapshot) are read again every [tickMs], so a job asked for while another runs (a sync while
 * the index merges, which tells no busy edge) has its line too. An index import has none: its worker is in the
 * foreground already, its notification saying how far it is (IndexImports), and one notification for one job is
 * enough. The service stops itself once the line is gone. A lookup's line is the library page's: [facts] is what the
 * library knows of its song now (SongFacts.songOf, the app's database), so a song it has already is never said to be
 * added.
 */
internal class Working(
    private val jobs: () -> List<Job>,
    scope: CoroutineScope,
    private val start: () -> Unit,
    private val tickMs: Long = TICK_MS,
    private val facts: (Job) -> SongFacts? = { null },
) {
    private val busy = MutableStateFlow(false)
    private val said = MutableStateFlow<String?>(null)

    /** What the service's notification says now; null when nothing it keeps waits or runs. */
    val line: StateFlow<String?> = said

    /** How many times the jobs were read: a test's clock. */
    @Volatile var ticks = 0
        private set

    /** The queue's `onBusy`: never blocks. */
    fun busy(now: Boolean) {
        busy.value = now
    }

    init {
        scope.launch {
            busy.collectLatest { now ->
                if (!now) {
                    said.value = null
                    return@collectLatest
                }
                while (true) {
                    val was = said.value
                    val line = lineOf(jobs(), facts)
                    said.value = line
                    ticks++
                    if (line != null && was == null) start()
                    delay(tickMs)
                }
            }
        }
    }

    companion object {
        const val TICK_MS = 1_000L

        /** The kind of job whose worker shows its own notification. */
        private const val INDEX = "index"

        /** Whether [job] is a lookup (JobCommands.isLookup's commands: a song's, Get it and Fetch now; its versions
         * kept; a site's index read, an artist's page or LaCuerda's own search). */
        fun isLookup(job: Job): Boolean = job.spec.commands.any { JobCommands.isLookup(it.args) }

        /**
         * The line of [jobs] (a queue's snapshot): the job that runs, else the first to run, of those the service
         * keeps going (every kind but an index import), a sync named as sharing logs with its computer, a lookup by its
         * song (or the page it reads) and the line the library page shows for it ("Estopa - Tu calorro · Looking up
         * the lyrics…", JobViews.line with [facts], what the library knows of its song), and how many more wait
         * after it; null when none waits or runs.
         */
        fun lineOf(jobs: List<Job>, facts: (Job) -> SongFacts? = { null }): String? {
            val kept = jobs.filter { it.active && it.spec.kind != INDEX }.sortedBy { it.id }
            val job = kept.firstOrNull { it.state == Job.RUNNING } ?: kept.firstOrNull() ?: return null
            if (job.state != Job.RUNNING) return "Waiting · ${what(job)}"
            val doing = when {
                isLookup(job) -> "${job.display} · ${JobViews.line(job, facts = facts(job)).text}"
                job.spec.kind == "sync" -> "Sharing logs with ${job.display.removePrefix("Share with ")}…"
                job.spec.kind == "add" -> "Adding ${job.display}…"
                job.spec.kind == "remove" -> "Removing ${job.display}…"
                else -> "${job.display}…"
            }
            val more = kept.size - 1
            return if (more > 0) "$doing · $more waiting" else doing
        }

        /** A job named as a request: "Share with Daniel's library", "Add Estopa - Tu calorro", a lookup by its title
         * ("Fetch Estopa - Tu calorro", "Search LaCuerda for “corazón”"). */
        private fun what(job: Job): String = when {
            isLookup(job) -> job.spec.title
            job.spec.kind == "add" -> "Add ${job.display}"
            job.spec.kind == "remove" -> "Remove ${job.display}"
            else -> job.display
        }
    }
}
