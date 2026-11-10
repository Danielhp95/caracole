package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.page.MirrorPageData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A file shared to the app on the phone's queue: staged, filed by the inbox runner in PhoneKinds' words, its song's
 * pages made again; one no song fits waits in `stateDir/inbox/`, tried again after a sync, a lookup or an add (the
 * phone's afterJob, InboxRetry) and filed once a song fits, dropped after 30 days; a file caracole keeps nothing of
 * is never staged.
 */
class InboxRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private var now: Instant = Instant.parse("2026-11-10T12:00:00Z")
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val rendered = CopyOnWriteArrayList<List<Long>>()
    private val database: Database by lazy { TestDb.fresh(tmp.root) }
    private val queue by lazy { JobQueue(scope) }
    private val parts: PhoneParts by lazy {
        val state = File(tmp.root, "state").apply { mkdirs() }
        PhoneParts(database, LibraryStore(File(tmp.root, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                   MirrorPageData(null), { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport },
                                                   Pacing.REAL) },
                   SongPages { _, ids, _ -> rendered += ids.toList(); RenderStats(written = ids.size) },
                   SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }
    private val retry by lazy { InboxRetry(parts) { now } }

    @After fun stop() {
        scope.cancel()
        database.close()
    }

    /** The phone's afterJob, as Assembly wires it: the waiting files tried again after each job. */
    private fun wired() {
        queue.onEnd = retry::afterJob
    }

    private fun add(artist: String, title: String) =
        database.writeBlocking { db -> parts.store.add(db, artist, title, now = "2026-11-01T00:00:00Z") }

    private fun share(name: String?, data: ByteArray, type: String? = null) = InboxShare.share(parts, name, type, data, now)

    private fun await(job: Job): Job = runBlocking { withTimeout(10_000) { queue.await(job.id) } }

    private fun line(job: Job) = JobViews.line(await(job))

    private val folder get() = InboxShare.folder(parts)

    @Test fun aFileNamedForASongIsFiledForItAndItsPagesMadeAgain() {
        val song = add("Oasis", "Wonderwall")
        val shared = share("Oasis - Wonderwall.gp5", "GP-DATA".toByteArray())
        assertEquals("Oasis - Wonderwall.gp5", shared.name)
        val job = await(shared.job!!)
        assertEquals(Line("ready", "Filed as guitar-1.gp5 of Oasis - Wonderwall"), JobViews.line(job))
        assertEquals("inbox", job.spec.kind)
        assertEquals("inbox:Oasis - Wonderwall.gp5", job.key)
        assertEquals(song.id, job.songId)
        val kept = database.read { db -> Kept.keptFiles(db, song.id) }
        assertEquals(listOf("guitar-1.gp5"), kept.map { it.name })
        assertEquals("GP-DATA", File(parts.store.folderOf(song), "guitar-1.gp5").readText())
        assertEquals(listOf(listOf(song.id)), rendered)
        assertEquals(emptyList(), folder.waiting())  // filed: no longer waiting
    }

    @Test fun aFileNoSongFitsWaitsAndIsFiledAfterTheAddThatBringsItsSong() {
        wired()
        val shared = share("Blur - Song 2.pdf", "%PDF-score".toByteArray())
        assertEquals(Line("waiting", "Waiting for a song that fits: Blur - Song 2.pdf",
                          details = "#tab=requests&job=${shared.job!!.id}"), line(shared.job!!))
        assertEquals(listOf("Blur - Song 2.pdf"), folder.waiting())
        // A job of another kind tries nothing; an add, the song's, files it.
        await(queue.submit(JobSpec("Export", "export:1", "export", emptyList(), run = {})).first)
        assertEquals(1, queue.snapshot().count { it.spec.kind == "inbox" })
        await(queue.submit(JobSpec("Add Blur - Song 2", "blur/song-2", "add", emptyList(), run = {
            add("Blur", "Song 2")
        })).first)
        val again = waitFor { queue.snapshot().firstOrNull { it.spec.kind == "inbox" && it.id != shared.job!!.id } }
        assertEquals(Line("ready", "Filed as score-1.pdf of Blur - Song 2"), line(again))
        assertEquals(emptyList(), folder.waiting())
        // Nothing waits now: the next lookup queues nothing more.
        await(queue.submit(JobSpec("Look it up", "blur/song-2", "song", emptyList(), run = {})).first)
        assertEquals(2, queue.snapshot().count { it.spec.kind == "inbox" })
    }

    @Test fun aFileThatStillFitsNoSongIsNeverQueuedAgainAndIsDroppedAfterThirtyDays() {
        wired()
        val shared = share("Nobody - Nothing.gp5", "GP".toByteArray())
        await(shared.job!!)
        await(queue.submit(JobSpec("Sync", "sync", "sync", emptyList(), run = {})).first)
        assertEquals(1, queue.snapshot().count { it.spec.kind == "inbox" })
        assertEquals(listOf("Nobody - Nothing.gp5"), folder.waiting())
        now = now.plus(Duration.ofDays(30))
        await(queue.submit(JobSpec("Export", "export:2", "export", emptyList(), run = {})).first)
        assertEquals(emptyList(), folder.waiting())
    }

    @Test fun aFileTheLibraryKeepsAlreadyIsSaidFiledAndNoLongerWaits() {
        val song = add("Oasis", "Wonderwall")
        await(share("Oasis - Wonderwall.gp5", "GP-DATA".toByteArray()).job!!)
        val again = share("download.gp5", "GP-DATA".toByteArray())
        assertEquals(Line("ready", "Filed as guitar-1.gp5 of Oasis - Wonderwall"), line(again.job!!))
        assertEquals(listOf("guitar-1.gp5"), database.read { db -> Kept.keptFiles(db, song.id) }.map { it.name })
        assertEquals(emptyList(), folder.waiting())
        assertEquals(1, rendered.size)  // a duplicate changes no page
    }

    @Test fun aFileTheLibraryLostIsPutBack() {
        val song = add("Oasis", "Wonderwall")
        await(share("Oasis - Wonderwall.pdf", "%PDF".toByteArray()).job!!)
        val kept = File(parts.store.folderOf(song), "score-1.pdf")
        assertTrue(kept.delete())
        val again = share("download (3).pdf", "%PDF".toByteArray())
        assertEquals(Line("ready", "Filed as score-1.pdf of Oasis - Wonderwall"), line(again.job!!))
        assertEquals("%PDF", kept.readText())
        assertEquals(2, rendered.size)
    }

    @Test fun aFileOfAKindCaracoleKeepsNothingOfIsNeverStaged() {
        add("Oasis", "Wonderwall")
        val shared = share("Oasis - Wonderwall.txt", "lyrics".toByteArray(), type = "application/octet-stream")
        assertNull(shared.job)
        assertEquals("Not filed: caracole keeps Guitar Pro files and scores, and Oasis - Wonderwall.txt is neither",
                     shared.said)
        assertEquals(emptyList(), folder.waiting())
    }

    @Test fun aFileSharedWithNoExtensionIsNamedByItsBytes() {
        val song = add("Oasis", "Wonderwall")
        val gp5 = byteArrayOf(24) + "FICHIER GUITAR PRO v5.00".toByteArray() + ByteArray(10)
        val shared = share("Oasis - Wonderwall", gp5, type = "application/octet-stream")
        assertEquals("Oasis - Wonderwall.gp5", shared.name)
        assertEquals(Line("ready", "Filed as guitar-1.gp5 of Oasis - Wonderwall"), line(shared.job!!))
        assertEquals(listOf("guitar-1.gp5"), database.read { db -> Kept.keptFiles(db, song.id) }.map { it.name })
    }

    @Test fun twoFilesOfOneNameWaitApartAndAreFiledApart() {
        val song = add("Oasis", "Wonderwall")
        val one = share("Oasis - Wonderwall.gp5", "one".toByteArray())
        val two = share("Oasis - Wonderwall.gp5", "two".toByteArray())
        assertEquals("Oasis - Wonderwall (2).gp5", two.name)
        assertEquals(Line("ready", "Filed as guitar-1.gp5 of Oasis - Wonderwall"), line(one.job!!))
        assertEquals(Line("ready", "Filed as guitar-2.gp5 of Oasis - Wonderwall"), line(two.job!!))
        assertEquals(listOf("guitar-1.gp5", "guitar-2.gp5"),
                     database.read { db -> Kept.keptFiles(db, song.id) }.map { it.name })
    }

    @Test fun aFileGoneBeforeItsJobRunsFailsItInItsWords() {
        val job = queue.submit(InboxShare.spec(parts, "gone.gp5")).first
        val over = await(job)
        assertEquals(Job.FAILED, over.state)
        assertEquals("Not filed: gone.gp5 isn't waiting to be filed any more.", JobViews.line(over).text)
    }

    @Test fun anIgnoredSongGetsNoFile() {
        val song = add("Oasis", "Wonderwall")
        database.writeBlocking { db -> db.execute("UPDATE songs SET status = 'ignored' WHERE id = ?", song.id) }
        val shared = share("Oasis - Wonderwall.gp5", "GP".toByteArray())
        assertEquals("waiting", line(shared.job!!).tone)
        assertEquals("ignored", database.read { db -> Songs.byId(db, song.id)!!.status })
        assertEquals(listOf("Oasis - Wonderwall.gp5"), folder.waiting())
    }

    private fun <T : Any> waitFor(what: () -> T?): T {
        val until = System.nanoTime() + 10_000_000_000
        while (System.nanoTime() < until) {
            what()?.let { return it }
            Thread.sleep(20)
        }
        throw AssertionError("not in time")
    }
}
