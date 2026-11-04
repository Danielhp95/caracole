package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * What keeps the phone's caracole working while its queue has a job ([Working]): the line its foreground service's
 * notification says, and when that service is started, against the phone's real job queue.
 */
class WorkingTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val queue = JobQueue(scope)

    @After fun stop() = scope.cancel()

    /** A job of [kind] that runs until [gate] opens. */
    private fun submit(kind: String, display: String, gate: CompletableDeferred<Unit>) = queue.submit(JobSpec(
        title = display, key = "$kind:$display", kind = kind, display = display, stages = listOf(kind to kind),
        run = { gate.await() },
    )).first

    private fun waitFor(what: String, condition: () -> Boolean) {
        val end = System.nanoTime() + 10_000_000_000L
        while (!condition()) {
            if (System.nanoTime() > end) throw AssertionError("waited 10 s for $what")
            Thread.sleep(5)
        }
    }

    private fun running(id: Int) = waitFor("request $id to run") { queue.job(id)?.state == "running" }

    @Test
    fun `the line names the job that runs, a sync as syncing with its computer, and those after it`() {
        val sync = CompletableDeferred<Unit>()
        val first = submit("sync", "Sync with Daniel's library", sync)
        running(first.id)
        assertEquals("Syncing with Daniel's library…", Working.lineOf(queue.snapshot()))
        val add = CompletableDeferred<Unit>()
        submit("add", "Estopa - Tu calorro", add)
        assertEquals("Syncing with Daniel's library… (1 more waiting)", Working.lineOf(queue.snapshot()))
        sync.complete(Unit)
        waitFor("the add to run") { queue.snapshot().any { it.spec.kind == "add" && it.state == "running" } }
        assertEquals("Adding Estopa - Tu calorro…", Working.lineOf(queue.snapshot()))
        add.complete(Unit)
        waitFor("the queue to empty") { queue.activeCount() == 0 }
        assertNull(Working.lineOf(queue.snapshot()), "nothing waits or runs")
    }

    @Test
    fun `a lookup is named by its song and the line the library page shows for it, and by its title while it waits`() {
        val lookup = CompletableDeferred<Unit>()
        val song = queue.submit(JobSpec(
            title = "Fetch Estopa - Tu calorro", key = "estopa/tu-calorro", kind = "song", display = "Estopa - Tu calorro",
            stages = listOf("song" to "Find the song", "lyrics" to "Lyrics from LRCLIB"),
            run = { context -> context.stage("lyrics", "running"); lookup.await() },
        )).first
        waitFor("the lookup's stage") { queue.job(song.id)?.stages?.any { it.state == "running" } == true }
        val line = JobViews.line(queue.job(song.id)!!).text
        assertEquals("Estopa - Tu calorro: $line", Working.lineOf(queue.snapshot()))
        val read = CompletableDeferred<Unit>()
        submit("lacuerda-artist", "Estopa on LaCuerda", read)
        val waiting = queue.submit(JobSpec(
            title = "Search LaCuerda for “corazones rotos”", key = "lacuerda-search:corazones-rotos",
            kind = "lacuerda-search", display = "“corazones rotos” on LaCuerda", stages = emptyList(), run = { },
        )).first
        assertEquals("Estopa - Tu calorro: $line (2 more waiting)", Working.lineOf(queue.snapshot()))
        lookup.complete(Unit)
        waitFor("the read to run") { queue.snapshot().any { it.spec.kind == "lacuerda-artist" && it.state == "running" } }
        read.complete(Unit)
        waitFor("the search to end") { queue.job(waiting.id)?.active == false }
        assertNull(Working.lineOf(queue.snapshot()))
        // waiting its turn behind an import, a lookup is named by its request's title
        val merge = CompletableDeferred<Unit>()
        running(submit("index", "The computer's index", merge).id)
        val asked = CompletableDeferred<Unit>()
        submit("song", "Fetch Estopa - Fuego", asked)
        assertEquals("Fetch Estopa - Fuego: waiting its turn", Working.lineOf(queue.snapshot()))
        merge.complete(Unit)
        asked.complete(Unit)
    }

    @Test
    fun `an index import alone needs no line, its worker showing its own, but a job waiting behind it does`() {
        val merge = CompletableDeferred<Unit>()
        val import = submit("index", "The computer's index", merge)
        running(import.id)
        assertNull(Working.lineOf(queue.snapshot()))
        val removal = CompletableDeferred<Unit>()
        submit("remove", "Estopa - Tu calorro", removal)
        assertEquals("Remove Estopa - Tu calorro: waiting its turn", Working.lineOf(queue.snapshot()))
        merge.complete(Unit)
        removal.complete(Unit)
    }

    @Test
    fun `the service is started as a job of its kind comes, and its line goes once the queue is idle`() {
        val starts = AtomicInteger()
        val working = Working(queue::snapshot, scope, start = { starts.incrementAndGet() }, tickMs = 5)
        queue.onBusy = working::busy

        val sync = CompletableDeferred<Unit>()
        submit("sync", "Sync with Daniel's library", sync)
        waitFor("the line") { working.line.value == "Syncing with Daniel's library…" }
        assertEquals(1, starts.get())
        sync.complete(Unit)
        waitFor("the line to go") { working.line.value == null }

        // An import alone: its worker is in the foreground already, and the service isn't started for it.
        val merge = CompletableDeferred<Unit>()
        running(submit("index", "The computer's index", merge).id)
        val seen = working.ticks
        waitFor("a few ticks") { working.ticks >= seen + 3 }
        assertNull(working.line.value)
        assertEquals(1, starts.get())

        // A sync asked for while it merges: no busy edge comes, and the service is started all the same.
        val after = CompletableDeferred<Unit>()
        submit("sync", "Sync with Daniel's library", after)
        waitFor("the waiting sync's line") { working.line.value == "Sync with Daniel's library: waiting its turn" }
        assertEquals(2, starts.get())
        merge.complete(Unit)
        waitFor("the sync to run") { working.line.value == "Syncing with Daniel's library…" }
        assertEquals(2, starts.get(), "started once for as long as it has a line")
        after.complete(Unit)
        waitFor("the line to go") { working.line.value == null }
    }
}
