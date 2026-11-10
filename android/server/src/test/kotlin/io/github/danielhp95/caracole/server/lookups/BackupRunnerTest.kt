package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.testing.TestParts
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
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole backup` on the phone: a backup made, or one restored, as the queued jobs of PhoneKinds' backup and
 * restore kinds, their lines PhoneKinds' words, never run beside another job's write. */
class BackupRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()
    private var now: Instant = Instant.parse("2026-11-03T12:00:00Z")

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val runners: HashMap<String, CommandRunner>,
                        val runner: BackupRunner)

    private fun phone(): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        database.writeBlocking { Fixtures.load(it, "sync/fixtures/rich.jsonl", File(dir, "library")) }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        val runner = BackupRunner(parts, clock = { now }, zone = ZoneOffset.UTC)
        runners["backup"] = runner
        return Phone(parts, queue, runners, runner)
    }

    private fun run(phone: Phone, spec: JobSpec): Job = runBlocking {
        val job = phone.queue.submit(spec).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    @Test fun aBackupByHandIsAQueuedJobOfItsKindSaidInItsWords() {
        val phone = phone()
        val spec = phone.runner.backup(Backups.BY_HAND)
        assertEquals(listOf("Back up the library", "backup:by-hand", "backup", "A backup (by-hand)"),
                     listOf(spec.title, spec.key, spec.kind, spec.display))
        assertEquals(emptyList(), spec.commands, "a job of the phone's own, its run the runner's")
        assertEquals(listOf(PhoneKinds.BACKUP.stage), spec.stages)
        val job = run(phone, spec)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(Line("ready", "Backed up (by-hand)"), JobViews.line(job))
        val made = Backups.list(phone.parts.stateDir).single()
        assertEquals(Backups.BY_HAND, made.label)
        assertEquals(now, made.at)
    }

    @Test fun aBackupThatCantBeMadeFailsSayingWhy() {
        val phone = phone()
        val refused = run(phone, phone.runner.backup("weekly"))
        assertEquals(Job.FAILED, refused.state)
        assertTrue(JobViews.line(refused).text.startsWith("Not backed up: no backup is labelled weekly"),
                   JobViews.line(refused).text)
        val room = Backups.freeSpace
        try {
            Backups.freeSpace = { 1024L }
            val full = run(phone, phone.runner.backup(Backups.DAILY))
            assertEquals(Job.FAILED, full.state)
            assertEquals("Not backed up: there isn't room for it on the phone.", JobViews.line(full).text)
        } finally {
            Backups.freeSpace = room
        }
        assertEquals(emptyList(), Backups.list(phone.parts.stateDir))
    }

    @Test fun aRestoreIsAQueuedJobThatKeepsThisSidesCooldownsAndOwesThePagesAgain() {
        val phone = phone()
        assertEquals(Job.DONE, run(phone, phone.runner.backup(Backups.BY_HAND)).state)
        val backup = Backups.list(phone.parts.stateDir).single()
        val creep = phone.parts.database.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        phone.parts.database.writeBlocking { db ->
            db.execute("UPDATE songs SET title = 'Changed since' WHERE id = ?", creep.id)
            Health.recordBlock(db, "ug", now, "403")
            db.kvSet("render:${creep.id}:phone", "{\"unit\": \"x\", \"build\": \"b\"}")
            db.kvSet("phone:render-build", "b")
        }
        val spec = phone.runner.restore(backup)
        assertEquals(listOf("Restore the library of 2026-11-03 12:00", "restore:${backup.file.name}", "restore",
                            "The library of 2026-11-03 12:00"), listOf(spec.title, spec.key, spec.kind, spec.display))
        val job = run(phone, spec)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(Line("ready", "Restored the library of 2026-11-03 12:00"), JobViews.line(job))
        phone.parts.database.read { db ->
            assertEquals("Creep", Songs.byId(db, creep.id)!!.title)
            assertTrue(Health.isCooling(db, "ug", now), "the cooldown met since is kept")
            assertNull(db.kvGet("render:${creep.id}:phone"), "the phone's pages owed again")
            assertNull(db.kvGet("phone:render-build"))
        }
    }

    @Test fun aRestoreOfNoBackupFailsAndChangesNothing() {
        val phone = phone()
        assertEquals(Job.DONE, run(phone, phone.runner.backup(Backups.BY_HAND)).state)
        val before = phone.parts.database.read { db -> Songs.list(db) }
        for (name in listOf("nope.sqlite", "../caracole.sqlite", "by-hand-2026-11-04T120000Z.sqlite", ".hidden")) {
            val job = run(phone, phone.runner.restore(name, "2026-11-03 12:00"))
            assertEquals(Job.FAILED, job.state, name)
            assertTrue(JobViews.line(job).text.startsWith("Not restored: "), JobViews.line(job).text)
        }
        assertEquals(before, phone.parts.database.read { db -> Songs.list(db) })
    }

    @Test fun aBackupNeverRunsBesideAnotherJobsWrite() {
        val phone = phone()
        val inside = CountDownLatch(1)
        val release = CountDownLatch(1)
        val room = Backups.freeSpace
        val order = mutableListOf<String>()
        phone.runners["get"] = CommandRunner { _, _ -> synchronized(order) { order += "lookup" } }
        try {
            Backups.freeSpace = {
                inside.countDown()
                release.await(30, TimeUnit.SECONDS)
                synchronized(order) { order += "backup" }
                Long.MAX_VALUE
            }
            val backup = phone.queue.submit(phone.runner.backup(Backups.BY_HAND)).first
            assertTrue(inside.await(30, TimeUnit.SECONDS))
            val lookup = phone.queue.submit(JobSpec("Fetch it", "radiohead/creep", "song", emptyList(),
                                                    commands = listOf(Command(
                                                        "Looking it up", listOf("get", "--", "Radiohead", "Creep"))))).first
            Thread.sleep(200)
            assertEquals(Job.QUEUED, phone.queue.job(lookup.id)!!.state, "the lookup waits for the backup")
            release.countDown()
            runBlocking { withTimeout(60_000) { phone.queue.await(lookup.id) } }
            assertEquals(Job.DONE, phone.queue.job(backup.id)!!.state)
            assertEquals(listOf("backup", "lookup"), order)
        } finally {
            release.countDown()
            Backups.freeSpace = room
        }
    }
}
