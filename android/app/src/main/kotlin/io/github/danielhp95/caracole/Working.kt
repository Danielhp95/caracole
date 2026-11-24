package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.SongFacts
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * What keeps the phone's caracole working while its job queue has a job to do (a sync, an add, a removal, a lookup,
 * the site catalogues, the phone's pages, a backup): the line its foreground service ([SyncService]) says ([line]),
 * with how far it is where its job counts ([Shown.progress], the notification's bar), and that service started
 * ([start]) as the line comes.
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
    private val said = MutableStateFlow<Shown?>(null)

    /** What the service's notification says now; null when nothing it keeps waits or runs. */
    val line: StateFlow<Shown?> = said

    /** A line, and how far its job is ([progress]: done and in all, as its stage counts them), none where it doesn't
     * count. */
    data class Shown(val text: String, val progress: Pair<Double, Double>? = null)

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
                    val line = shownOf(jobs(), facts)
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

        /** How a sync with a computer is named (SyncRoutes'): "Share with <its name>". */
        private const val SHARE_WITH = "Share with "

        /** The kind of job whose worker shows its own notification. */
        private const val INDEX = "index"

        /** Whether [job] is a lookup (JobCommands.isLookup's commands: a song's, Fetch and Fetch again; its versions
         * kept; a site's index read, an artist's page or LaCuerda's own search). */
        fun isLookup(job: Job): Boolean = job.spec.commands.any { JobCommands.isLookup(it.args) }

        /** [shownOf]'s words alone. */
        fun lineOf(jobs: List<Job>, facts: (Job) -> SongFacts? = { null }): String? = shownOf(jobs, facts)?.text

        /**
         * The line of [jobs] (a queue's snapshot): the job that runs, else the first to run, of those the service
         * keeps going (every kind but an index import), and how many more wait after it; null when none waits or
         * runs. The job that runs is named, then what it is doing, so that the shade moves as it goes:
         * - a lookup by its song (or the page it reads) and the line the library page shows for it ("Estopa - Tu
         *   calorro · Looking up the lyrics…", JobViews.line with [facts], what the library knows of its song);
         * - one of the phone's own kinds (PhoneKinds: the site catalogues, the phone's pages, a backup…) by its name
         *   and the line the Journal and Settings say for it, its stage's words as it runs ("The site catalogues ·
         *   Downloading · 31 of 52 MB"), its name alone before it says any;
         * - a sync as sharing logs with its computer (a file's import by its own name), then its running stage and
         *   what that stage says ([doing]: "… · Copying the computer's pages · 120 of 640 pages").
         * [Shown.progress] is the count the job's own stage says ([counted]), never one read from a song's name.
         */
        fun shownOf(jobs: List<Job>, facts: (Job) -> SongFacts? = { null }): Shown? {
            val kept = jobs.filter { it.active && it.spec.kind != INDEX }.sortedBy { it.id }
            val job = kept.firstOrNull { it.state == Job.RUNNING } ?: kept.firstOrNull() ?: return null
            if (job.state != Job.RUNNING) return Shown("Waiting · ${what(job)}")
            val own = PhoneKinds.ALL[job.spec.kind]
            val (doing, counts) = when {
                isLookup(job) -> "${job.display} · ${JobViews.line(job, facts = facts(job)).text}" to null
                own != null -> {
                    val said = JobViews.line(job).text
                    when {
                        // Before its stage says anything, JobViews says its stage's label ("Catalogues…"): its name.
                        said == "${own.stage.second}…" -> "${job.display}…" to null
                        // A line that names it already ("Filing song.gp5…", the inbox's): the line alone.
                        job.display in said -> said to said
                        else -> "${job.display} · $said" to said
                    }
                }
                job.spec.kind == "sync" -> {
                    // a sync with a computer ("Share with <its name>"); a file's import says its own name
                    val named = if (job.display.startsWith(SHARE_WITH)) {
                        "Sharing logs with ${job.display.removePrefix(SHARE_WITH)}"
                    } else {
                        job.display
                    }
                    val stage = job.stages.firstOrNull { it.state == Job.RUNNING }
                    if (stage == null) "$named…" to null else "$named · ${doing(job)}" to stage.detail
                }
                job.spec.kind == "add" -> "Adding ${job.display}…" to null
                job.spec.kind == "remove" -> "Removing ${job.display}…" to null
                else -> "${job.display}…" to null
            }
            val more = kept.size - 1
            return Shown(if (more > 0) "$doing · $more waiting" else doing, counts?.let(::counted))
        }

        /** What a sync's running stage is doing: its label, and what it says ("Copying the computer's pages · 120 of
         * 640 pages"), or its label alone with "…" while it says nothing; none while no stage runs. The notification
         * and the library screen's line of an unattended sync say it alike. */
        fun doing(job: Job): String? {
            val stage = job.stages.firstOrNull { it.state == Job.RUNNING } ?: return null
            return if (stage.detail.isBlank()) "${stage.label}…" else "${stage.label} · ${stage.detail}"
        }

        /**
         * The count a stage's words say, its last "N of M" ("Downloading · 31 of 52 MB", "1,204 of 10,428", "1.2 of
         * 2.5 GB") where [COUNT] finds one, as done and in all; none for none, for nothing in all, or for more done
         * than there is.
         */
        fun counted(said: String): Pair<Double, Double>? {
            val last = COUNT.findAll(said).lastOrNull() ?: return null
            val done = last.groupValues[1].replace(",", "").toDoubleOrNull() ?: return null
            val all = last.groupValues[2].replace(",", "").toDoubleOrNull() ?: return null
            return if (all > 0 && done <= all) done to all else null
        }

        /** "N of M", each a number as the phone's lines write one (digits grouped by commas, tenths after a point), at
         * the start of what a stage says or right after its " · ", and words of their own after it (a space, a stop,
         * "…", "·", or the line's end): never the digits of a name it says ("Filing Top 10 of 2020 (2).gp5…",
         * "Filing Live 1 of 2 - Song.gp5…"). */
        private val COUNT = Regex("(?:^|· )([0-9][0-9,]*(?:[.][0-9]+)?) of ([0-9][0-9,]*(?:[.][0-9]+)?)" +
                                  "(?=$|[\\s…·),;:]|[.](?:$|\\s))")

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
