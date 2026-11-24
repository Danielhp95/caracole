package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.SongFacts
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Test
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

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
        val first = submit("sync", "Share with Daniel's library", sync)
        running(first.id)
        assertEquals("Sharing logs with Daniel's library…", Working.lineOf(queue.snapshot()))
        val add = CompletableDeferred<Unit>()
        submit("add", "Estopa - Tu calorro", add)
        assertEquals("Sharing logs with Daniel's library… · 1 waiting", Working.lineOf(queue.snapshot()))
        sync.complete(Unit)
        waitFor("the add to run") { queue.snapshot().any { it.spec.kind == "add" && it.state == "running" } }
        assertEquals("Adding Estopa - Tu calorro…", Working.lineOf(queue.snapshot()))
        add.complete(Unit)
        waitFor("the queue to empty") { queue.activeCount() == 0 }
        assertNull(Working.lineOf(queue.snapshot()), "nothing waits or runs")
    }

    @Test
    fun `a file's import is named as itself, never as sharing logs with a computer`() {
        // SyncFileRoutes' import: a job of kind "sync" displayed "Sync with a file from <name>".
        val gate = CompletableDeferred<Unit>()
        val job = submit("sync", "Sync with a file from Desk", gate)
        running(job.id)
        assertEquals("Sync with a file from Desk…", Working.lineOf(queue.snapshot()))
        gate.complete(Unit)
    }

    /** A job of [kind] whose run says [said] ((stage, state, detail) each) as it begins, then waits for [gate]. */
    private fun saying(kind: String, display: String, stages: List<Pair<String, String>>,
                       said: List<Triple<String, String, String>>, gate: CompletableDeferred<Unit>) =
        queue.submit(JobSpec(title = display, key = "$kind:$display", kind = kind, display = display, stages = stages,
                             run = { context ->
                                 for ((stage, state, detail) in said) context.stage(stage, state, detail)
                                 gate.await()
                             })).first

    private fun runningWith(id: Int, detail: String) =
        waitFor("request $id to say $detail") { queue.job(id)?.stages?.any { it.detail == detail } == true }

    @Test
    fun `a phone kind's line is its own, as the Journal says it, after its name`() {
        val kind = PhoneKinds.CATALOGUES
        val gate = CompletableDeferred<Unit>()
        val job = saying(kind.kind, kind.display, listOf(kind.stage),
                         listOf(Triple(kind.stage.first, "running", "Downloading · 31 of 52 MB")), gate)
        runningWith(job.id, "Downloading · 31 of 52 MB")
        assertEquals("The site catalogues · Downloading · 31 of 52 MB", Working.lineOf(queue.snapshot()))
        assertEquals(Working.Shown("The site catalogues · Downloading · 31 of 52 MB", 31.0 to 52.0),
                     Working.shownOf(queue.snapshot()))
        gate.complete(Unit)
    }

    @Test
    fun `a phone kind that has said nothing yet is named alone, and one of fixed words says them`() {
        val catalogues = PhoneKinds.CATALOGUES
        val first = CompletableDeferred<Unit>()
        val job = saying(catalogues.kind, catalogues.display, listOf(catalogues.stage),
                         listOf(Triple(catalogues.stage.first, "running", "")), first)
        waitFor("its stage to run") { queue.job(job.id)?.stages?.any { it.state == "running" } == true }
        assertEquals("The site catalogues…", Working.lineOf(queue.snapshot()), "never \"Catalogues…\" after its name")
        first.complete(Unit)
        waitFor("the queue to empty") { queue.activeCount() == 0 }

        val backup = PhoneKinds.BACKUP
        val second = CompletableDeferred<Unit>()
        val made = saying(backup.kind, "A backup (daily)", listOf(backup.stage),
                          listOf(Triple(backup.stage.first, "running", "")), second)
        running(made.id)
        assertEquals("A backup (daily) · Backing up the book…", Working.lineOf(queue.snapshot()))
        assertNull(Working.shownOf(queue.snapshot())!!.progress, "no count: no bar of its own")
        second.complete(Unit)
    }

    @Test
    fun `a sync names its running stage and what that stage says`() {
        val gate = CompletableDeferred<Unit>()
        val sync = saying("sync", "Share with Daniel's library", SyncEngine.STAGES, listOf(
            Triple(SyncEngine.COMPARE, "done", "3 changes"), Triple(SyncEngine.TAKE, "done", "2 of 2 changes"),
            Triple(SyncEngine.MIRROR, "running", "120 of 640 pages")), gate)
        runningWith(sync.id, "120 of 640 pages")
        assertEquals("Sharing logs with Daniel's library · Copying the computer's pages · 120 of 640 pages",
                     Working.lineOf(queue.snapshot()))
        assertEquals(120.0 to 640.0, Working.shownOf(queue.snapshot())!!.progress)
        assertEquals("Copying the computer's pages · 120 of 640 pages", Working.doing(queue.job(sync.id)!!))
        gate.complete(Unit)
        waitFor("the queue to empty") { queue.activeCount() == 0 }

        // A stage that says nothing yet: its label alone; a file's import by its own name and its own stages' labels.
        val file = CompletableDeferred<Unit>()
        val import = saying("sync", "Sync with a file from Desk", SyncEngine.FILE_STAGES,
                            listOf(Triple(SyncEngine.CHECK, "running", "")), file)
        waitFor("its stage to run") { queue.job(import.id)?.stages?.any { it.state == "running" } == true }
        assertEquals("Sync with a file from Desk · Reading the file…", Working.lineOf(queue.snapshot()))
        assertEquals("Reading the file", Working.doing(queue.job(import.id)!!))
        file.complete(Unit)
    }

    @Test
    fun `a count is read from what a job's stage says, never from a song's name`() {
        assertEquals(31.0 to 52.0, Working.counted("Downloading · 31 of 52 MB"))
        assertEquals(1.2 to 2.5, Working.counted("Downloading · 1.2 of 2.5 GB"))
        assertEquals(1204.0 to 10428.0, Working.counted("Remaking pages · 1,204 of 10,428"))
        assertEquals(3.0 to 10.0, Working.counted("Remaking pages · 3 of 10"))
        assertNull(Working.counted("Backing up the book…"))
        assertNull(Working.counted("Importing the catalogues…"))
        assertNull(Working.counted("12 of 10"), "more done than there is: no bar")
        assertNull(Working.counted("0 of 0"))
        // A lookup's line names its song: no count is read there ("Top 10 of 2020" is a title).
        val gate = CompletableDeferred<Unit>()
        val song = lookup("Fetch Estopa - Top 10 of 2020", "estopa/top-10-of-2020", "Estopa - Top 10 of 2020",
                          JobCommands.lookupSteps("Estopa", "Top 10 of 2020"), gate)
        waitFor("the lookup's song stage") { lookups.job(song.id)?.stages?.any { it.state == "running" } == true }
        assertNull(Working.shownOf(lookups.snapshot())!!.progress)
        gate.complete(Unit)
    }

    @Test
    fun `a service start that comes once the work is over stops at once, never left saying Working`() {
        val looking = Working.Shown("Estopa - Tu calorro · Looking up the lyrics…")
        assertEquals(looking to false, SyncService.atStart(looking, "Working…"))
        // The line went before the start was delivered: the watcher heard it under the earlier start, which this
        // one kept the service past; a start with no line must stop itself.
        assertEquals(Working.Shown("Working…") to true, SyncService.atStart(null, "Working…"))
    }

    @Test
    fun `the notification's bar is filled as far as the job counts, and moves where it doesn't`() {
        assertEquals(596, SyncService.bar(31.0 to 52.0))
        assertEquals(0, SyncService.bar(0.0 to 640.0))
        assertEquals(SyncService.BAR, SyncService.bar(640.0 to 640.0))
        assertNull(SyncService.bar(null))
    }

    /** A lookup's job of its real commands ([JobCommands]'s), run by [lookups]' runners, until its gate opens. */
    private fun lookup(title: String, key: String, display: String, commands: List<Command>,
                       gate: CompletableDeferred<Unit>): Job {
        gates[commands.single().args.drop(1).joinToString(" ")] = gate
        val kind = JobCommands.kindOf(key, commands.map { it.args }, emptyList())
        return lookups.submit(JobSpec(title = title, key = key, kind = kind, stages = emptyList(), display = display,
                                      commands = commands, fetching = true)).first
    }

    private val gates = ConcurrentHashMap<String, CompletableDeferred<Unit>>()

    /** A queue whose `get` runs its song stage until its gate opens, and whose site reads wait for theirs. */
    private val lookups = JobQueue(scope, commands = Commands(mapOf(
        "get" to CommandRunner { args, context ->
            context.stage("song", "running")
            gates.getValue(args.drop(1).joinToString(" ")).await()
        },
        "lacuerda" to CommandRunner { args, _ -> gates.getValue(args.drop(1).joinToString(" ")).await() },
    )))

    @Test
    fun `a lookup is named by its song and the line the library page shows for it, and by its title while it waits`() {
        val first = CompletableDeferred<Unit>()
        val song = lookup("Fetch Estopa - Tu calorro", "estopa/tu-calorro", "Estopa - Tu calorro",
                          JobCommands.lookupSteps("Estopa", "Tu calorro"), first)
        assertTrue(Working.isLookup(song))
        waitFor("the lookup's song stage") { lookups.job(song.id)?.stages?.any { it.state == "running" } == true }
        // the library page's line: a song new to the library is being added; one it has is being looked up
        assertEquals("Estopa - Tu calorro · Adding to the book…", Working.lineOf(lookups.snapshot()))
        val known = JobViews.line(lookups.job(song.id)!!, facts = SongFacts()).text
        assertNotEquals("Adding to the book…", known)
        assertEquals("Estopa - Tu calorro · $known", Working.lineOf(lookups.snapshot()) { SongFacts() })
        val read = CompletableDeferred<Unit>()
        val artist = lookup("Read the page of Estopa on LaCuerda", "${JobCommands.LACUERDA_ARTIST}estopa",
                            "Estopa on LaCuerda", JobCommands.lacuerdaArtistSteps("estopa", "Estopa"), read)
        assertTrue(Working.isLookup(artist))
        val search = CompletableDeferred<Unit>()
        val waiting = lookup("Search LaCuerda for “corazones rotos”", "${JobCommands.LACUERDA_SEARCH}corazones-rotos",
                             "“corazones rotos” on LaCuerda",
                             JobCommands.lacuerdaSearchSteps("corazones rotos", auto = true), search)
        assertEquals("Estopa - Tu calorro · $known · 2 waiting", Working.lineOf(lookups.snapshot()) { SongFacts() })
        first.complete(Unit)
        waitFor("the read to run") { lookups.job(artist.id)?.state == "running" }
        read.complete(Unit)
        search.complete(Unit)
        waitFor("the search to end") { lookups.job(waiting.id)?.active == false }
        assertNull(Working.lineOf(lookups.snapshot()))
        // waiting its turn behind an import, a lookup is named by its request's title
        val merge = CompletableDeferred<Unit>()
        val import = lookups.submit(JobSpec(title = "The computer's index", key = "index", kind = "index",
                                            display = "The computer's index", stages = listOf("index" to "index"),
                                            run = { merge.await() })).first
        waitFor("the import to run") { lookups.job(import.id)?.state == "running" }
        val asked = CompletableDeferred<Unit>()
        lookup("Fetch Estopa - Fuego", "estopa/fuego", "Estopa - Fuego", JobCommands.lookupSteps("Estopa", "Fuego"),
               asked)
        assertEquals("Waiting · Fetch Estopa - Fuego", Working.lineOf(lookups.snapshot()))
        merge.complete(Unit)
        asked.complete(Unit)
    }

    @Test
    fun `a job of the phone's own is no lookup, whatever its kind`() {
        val gate = CompletableDeferred<Unit>()
        val own = submit("song", "Estopa - Tu calorro", gate)
        running(own.id)
        assertFalse(Working.isLookup(queue.job(own.id)!!))
        assertEquals("Estopa - Tu calorro…", Working.lineOf(queue.snapshot()))
        gate.complete(Unit)
    }

    @Test
    fun `an index import alone needs no line, its worker showing its own, but a job waiting behind it does`() {
        val merge = CompletableDeferred<Unit>()
        val import = submit("index", "The computer's index", merge)
        running(import.id)
        assertNull(Working.lineOf(queue.snapshot()))
        val removal = CompletableDeferred<Unit>()
        submit("remove", "Estopa - Tu calorro", removal)
        assertEquals("Waiting · Remove Estopa - Tu calorro", Working.lineOf(queue.snapshot()))
        merge.complete(Unit)
        removal.complete(Unit)
    }

    @Test
    fun `the service is started as a job of its kind comes, and its line goes once the queue is idle`() {
        val starts = AtomicInteger()
        val working = Working(queue::snapshot, scope, start = { starts.incrementAndGet() }, tickMs = 5)
        queue.onBusy = working::busy

        val sync = CompletableDeferred<Unit>()
        submit("sync", "Share with Daniel's library", sync)
        waitFor("the line") { working.line.value?.text == "Sharing logs with Daniel's library…" }
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
        submit("sync", "Share with Daniel's library", after)
        waitFor("the waiting sync's line") { working.line.value?.text == "Waiting · Share with Daniel's library" }
        assertEquals(2, starts.get())
        merge.complete(Unit)
        waitFor("the sync to run") { working.line.value?.text == "Sharing logs with Daniel's library…" }
        assertEquals(2, starts.get(), "started once for as long as it has a line")
        after.complete(Unit)
        waitFor("the line to go") { working.line.value == null }
    }
}
