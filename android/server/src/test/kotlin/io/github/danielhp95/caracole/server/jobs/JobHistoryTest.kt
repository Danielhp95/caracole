package io.github.danielhp95.caracole.server.jobs

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** web/history.py on the phone, beside its vectors (QueueVectorsTest): the queue's requests kept across a restart in
 * `stateDir/requests.jsonl`, private, read back by the next queue, and a history that can't be written never stops a
 * request. */
@OptIn(ExperimentalCoroutinesApi::class)
class JobHistoryTest {
    @get:Rule val tmp = TemporaryFolder()

    private var now = Instant.parse("2026-11-03T12:00:00Z")
    private val clock = { now.also { now = now.plusSeconds(1) } }

    private fun lookup(artist: String, title: String) = JobSpec(
        title = "Get $artist - $title", key = "${artist.lowercase()}/${title.lowercase()}", kind = "song",
        stages = emptyList(), commands = JobCommands.lookupSteps(artist, title), fetching = true)

    @Test fun theNextQueueReadsTheRequestsBackWhatWaitedOrRanInterruptedTheIdsAfterTheirs() = runTest {
        val state = tmp.newFolder("state")
        val gate = CompletableDeferred<Unit>()
        val commands = Commands(mapOf("get" to CommandRunner { args, context ->
            context.stage("song", "running", "looking")
            context.say("get: ${args.last()}")
            if (args.last() == "Creep") gate.await()
        }))
        val scope = CoroutineScope(StandardTestDispatcher(testScheduler) + SupervisorJob())
        val first = JobQueue(scope, clock = clock, commands = commands, history = JobHistory.at(state))
        val done = first.submit(lookup("Muse", "Hysteria")).first
        runCurrent()
        val running = first.submit(lookup("Radiohead", "Creep")).first
        val waiting = first.submit(lookup("Blur", "Song 2")).first
        runCurrent()
        assertEquals(Job.RUNNING, first.job(running.id)!!.state)
        val file = File(state, JobHistory.FILE_NAME)
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(file.toPath())))
        // The process ends with no word (a kill): what the file says is what the next queue reads.
        scope.cancel()
        val next = JobQueue(backgroundScope, clock = clock, commands = commands, history = JobHistory.at(state))
        val read = next.snapshot().reversed()
        assertEquals(listOf(done.id to Job.DONE, running.id to Job.INTERRUPTED, waiting.id to Job.INTERRUPTED),
                     read.map { it.id to it.state })
        // As caracole serve's: saved as it started, never while it ran, its command and stages waiting then.
        assertEquals(listOf(Job.SKIPPED), read[1].steps.map { it.state })
        assertEquals(Job.SKIPPED to "", read[1].stages[0].let { it.state to it.detail })
        assertEquals(listOf("get: Hysteria"), read[0].steps[0].output)
        assertEquals("song", read[0].spec.kind)
        assertEquals(waiting.id + 1, next.submit(lookup("Oasis", "Wonderwall")).first.id)
        // Try again of one read back runs its commands.
        gate.complete(Unit)
        assertEquals(Job.DONE, next.await(next.again(running.id).id).state)
        // Written whole as it was read: its first line the next id.
        val head = Json.parseToJsonElement(file.readLines().first()).jsonObject
        assertEquals(waiting.id + 1, head.getValue("next").jsonPrimitive.content.toInt())
    }

    @Test fun aHistoryInAFolderOfItsOwnIsPrivateToo() = runTest {
        val state = File(tmp.root, "made/state")
        val queue = JobQueue(backgroundScope, clock = clock, history = JobHistory.at(state))
        queue.await(queue.submit(JobSpec("Add", "a/t", "add", listOf("add" to "Adding to the library")) {}).first.id)
        assertEquals("rwx------", PosixFilePermissions.toString(Files.getPosixFilePermissions(state.toPath())))
        assertTrue(File(state, JobHistory.FILE_NAME).isFile)
        assertTrue(state.listFiles()!!.none { it.name.endsWith(".tmp") })
    }

    @Test fun aHistoryThatCantBeWrittenNeverStopsARequest() = runTest {
        val blocked = tmp.newFile("not-a-folder")  // its folder is a file: nothing can be written there
        val queue = JobQueue(backgroundScope, clock = clock, history = JobHistory(File(blocked, JobHistory.FILE_NAME)))
        val job = queue.submit(JobSpec("Add", "a/t", "add", listOf("add" to "Adding to the library")) {
            it.stage("add", "done")
        }).first
        assertEquals(Job.DONE, queue.await(job.id).state)
        assertEquals(listOf(Job.DONE), queue.snapshot().map { it.state })
    }

    @Test fun aJobOfThePhonesOwnReadBackKeepsItsKindDoneLineAndWordsButCantBeRunAgain() = runTest {
        val state = tmp.newFolder("state")
        val commands = Commands(mapOf("get" to CommandRunner { _, _ -> }))
        val first = JobQueue(backgroundScope, clock = clock, commands = commands, history = JobHistory.at(state))
        val add = first.submit(JobSpec("Add Radiohead - Creep", "radiohead/creep", "add",
                                       listOf("add" to "Adding to the library"), display = "Radiohead - Creep",
                                       doneLine = "Added: the computer's next run fetches it.") {
            it.say("Added Radiohead - Creep to wanted.txt.")
            it.stage("add", "done")
        }).first
        val sync = first.submit(JobSpec("Sync", JobCommands.SYNCING + "http://computer:8737", "sync",
                                        listOf("compare" to "Comparing")) { it.stage("compare", "done") }).first
        val render = first.submit(JobSpec("Make the pages again", "render:b1", "render",
                                          listOf("render" to "Making the pages")) {
            it.say("Pages made again for 3 songs")
        }).first
        val lookup = first.submit(lookup("Muse", "Hysteria")).first
        runCurrent()
        assertEquals(Job.DONE, first.await(lookup.id).state)
        val lines = File(state, JobHistory.FILE_NAME).readLines()
        // What format 1 can't say, beside the line of a job of the phone's own; none beside one of commands.
        val records = lines.map { Json.parseToJsonElement(it).jsonObject }.filter { "id" in it }
        assertEquals(listOf(true, true, true, false), listOf(add.id, sync.id, render.id, lookup.id).map { id ->
            records.last { it.getValue("id").jsonPrimitive.content.toInt() == id }.containsKey("phone")
        })
        val next = JobQueue(backgroundScope, clock = clock, commands = commands, history = JobHistory.at(state))
        val read = next.job(add.id)!!
        assertEquals("add" to "Radiohead - Creep", read.spec.kind to read.display)
        assertEquals("Added: the computer's next run fetches it.", read.spec.doneLine)
        assertEquals(listOf("Added Radiohead - Creep to wanted.txt."), read.output)
        assertEquals(listOf("add" to Job.DONE), read.stages.map { it.name to it.state })
        assertEquals("sync", next.job(sync.id)!!.spec.kind)  // by its key, as caracole serve's
        assertEquals("render" to listOf("Pages made again for 3 songs"), next.job(render.id)!!.let { it.spec.kind to it.output })
        assertFailsWith<JobNotRepeatable> { next.again(add.id) }
        assertFailsWith<NoSuchElementException> { next.again(99) }
        assertEquals("song", next.job(lookup.id)!!.spec.kind)
        // Written whole again as the next queue read it, they keep it.
        val third = JobQueue(backgroundScope, clock = clock, history = JobHistory.at(state))
        assertEquals("render" to listOf("Pages made again for 3 songs"), third.job(render.id)!!.let { it.spec.kind to it.output })
    }

    @Test fun aKindOfThePhonesOwnIsToldByItsKeysPrefix() {
        val render = PhoneKinds.Kind("render", "render:", "render" to "Making the pages", "{done} of {total}",
                                     "Pages made again", "Not made: {why}")
        assertEquals("render", JobCommands.kindOf("render:b1", emptyList(), listOf("render"), listOf(render)))
        assertEquals("song", JobCommands.kindOf("render/song", emptyList(), emptyList(), listOf(render)))
        assertEquals("remove", JobCommands.kindOf("remove:a/t", emptyList(), emptyList(), listOf(render)))
    }

    @Test fun aTimeIsWrittenAsPythonsIsoformatInUtcAndReadAsFromisoformatReadsIt() {
        assertEquals("2026-11-03T09:30:00+00:00", JobHistory.iso(Instant.parse("2026-11-03T09:30:00Z")))
        assertEquals("2026-11-03T09:30:00.000001+00:00", JobHistory.iso(Instant.parse("2026-11-03T09:30:00.000001789Z")))
        for ((text, at) in listOf(
            "2026-11-03T09:30:00+00:00" to "2026-11-03T09:30:00Z", "2026-11-03T10:30:00+01:00" to "2026-11-03T09:30:00Z",
            "2026-11-03T09:30:00Z" to "2026-11-03T09:30:00Z", "2026-11-03T09:30" to "2026-11-03T09:30:00Z",
            "2026-11-03" to "2026-11-03T00:00:00Z", "20261103T093000" to "2026-11-03T09:30:00Z",
            "2026-11-03T09" to "2026-11-03T09:00:00Z", "2026-11-03T09:30:00.5" to "2026-11-03T09:30:00.500Z",
            "2026-11-03T09:30:00,1234567+0100" to "2026-11-03T08:30:00.123456Z", "2026-11-03 09:30:00" to "2026-11-03T09:30:00Z",
            "2026-11-03T24:00:00" to "2026-11-04T00:00:00Z", "2026-11-03T09:30:00-00:30:15" to "2026-11-03T10:00:15Z",
        )) {
            assertEquals(Instant.parse(at), JobHistory.parseIso(text), text)
        }
        for (text in listOf("garbage", "2026-13-01", "2026-02-30", "2026-11-03T25:00", "2026-11-03T09:60",
                            "2026-11-03T09:30:00+24:00", "2026-11-03T24:00:01", "2026-11-03T09:30:00.", "2026-11-03T9:30")) {
            assertFailsWith<IllegalArgumentException>(text) { JobHistory.parseIso(text) }
        }
    }
}
