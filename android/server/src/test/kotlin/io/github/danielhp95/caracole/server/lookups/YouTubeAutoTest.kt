package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.Due
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.JobQueue
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
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The automatic YouTube pass (the design's §5.3) over the real queue, its jobs' runner a fake that records what it
 * was asked (and spends the runs a song costs, as `events` rows): which songs, how many, when it stops. */
class YouTubeAutoTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private class Phone(val parts: PhoneParts, val database: Database, val asked: List<Pair<String, Boolean>>)

    /** [songs] added, none settled on the sites but "not found", [noted] of them noted; each job spends [runs] runs. */
    private fun phone(songs: List<String>, noted: Set<String> = emptySet(), runs: Int = 2,
                      during: (Db) -> Unit = {}): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val asked = CopyOnWriteArrayList<Pair<String, Boolean>>()
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        runners["youtube"] = CommandRunner { args, context ->
            asked += args.last().removePrefix("--song=") to context.automatic
            database.writeBlocking { db ->
                repeat(runs) {
                    db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('t', ?, 'youtube', 'u', NULL, 'ok')",
                               Stamps.of(Instant.now()))
                }
                during(db)
            }
        }
        database.writeBlocking { db ->
            for ((i, name) in songs.withIndex()) {
                val song = parts.store.add(db, "Calla Lake", name, now = "2026-11-${10 + i}T00:00:00Z")
                Versions.updateSong(db, song.id, mapOf("match_decision" to "not_found"))
                if (name in noted) db.kvSet(Due.WANTED_PREFIX + song.id, "\"2026-11-27T00:00:00Z\"")
            }
        }
        return Phone(parts, database, asked)
    }

    private fun pass(phone: Phone, metered: () -> Boolean = { false }, problem: String? = null): YouTubeAuto.Ended =
        runBlocking { withTimeout(60_000) { YouTubeAuto(phone.parts, { problem }, metered).pass() } }

    @Test fun eachDueSongGetsOneAutomaticJobInTurnTheNotedFirst() {
        val phone = phone(listOf("One", "Two", "Three"), noted = setOf("One"))
        val ended = pass(phone)
        assertEquals(YouTubeAuto.Stop.NOTHING_DUE, ended.stopped)
        assertEquals(3, ended.jobs.size)
        assertEquals(listOf("Calla Lake - One" to true, "Calla Lake - Three" to true, "Calla Lake - Two" to true), phone.asked)
    }

    @Test fun threeSongsAndSixRunsLeftGiveThreeJobsAndAFourthWaits() {
        val phone = phone(listOf("One", "Two", "Three", "Four"))
        val budget = phone.parts.config().provider("youtube").budget.toInt()
        phone.database.writeBlocking { db ->
            repeat(budget - 6) {
                db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('s', ?, 'youtube', 'u', NULL, 'ok')",
                           Stamps.of(Instant.now().minusSeconds(3600)))
            }
        }
        val ended = pass(phone)
        assertEquals(YouTubeAuto.Stop.FEW_RUNS, ended.stopped)
        assertEquals(3, phone.asked.size)
    }

    @Test fun aBlockStopsThePass() {
        val phone = phone(listOf("One", "Two"), during = { db -> Health.recordBlock(db, "youtube", Instant.now(), "bot check") })
        assertEquals(YouTubeAuto.Stop.COOLING, pass(phone).stopped)
        assertEquals(1, phone.asked.size)
    }

    @Test fun onAPairedPhoneOnlyTheNotedSongsAreTaken() {
        val phone = phone(listOf("One", "Two"), noted = setOf("Two"))
        phone.database.writeBlocking { db ->
            db.kvSet("sync:base:0f1e2d3c4b5a6978", """{"format": 3, "units": {"song/x": [null, "${Stamps.of(Instant.now())}"]}}""")
            assertTrue(YouTubeAuto.paired(db, Instant.now()))
            assertTrue(!YouTubeAuto.paired(db, Instant.now().plusSeconds(15 * 86_400L)))
        }
        pass(phone)
        assertEquals(listOf("Calla Lake - Two" to true), phone.asked)
    }

    @Test fun nothingGoesSwitchedOffNotOfferedOrMetered() {
        val off = phone(listOf("One"))
        off.database.writeBlocking { db -> YouTubeAuto.set(db, false) }
        assertEquals(YouTubeAuto.Stop.SWITCHED_OFF, pass(off).stopped)
        val metered = phone(listOf("One"))
        assertEquals(YouTubeAuto.Stop.METERED, pass(metered, metered = { true }).stopped)
        val models = phone(listOf("One"))
        assertEquals(YouTubeAuto.Stop.NOT_OFFERED, pass(models, problem = "the chord models aren't downloaded").stopped)
        assertEquals(emptyList(), off.asked + metered.asked + models.asked)
    }

    @Test fun aPassWithNothingDueQueuesAndWritesNothing() {
        val phone = phone(emptyList())
        val before = phone.database.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } }
        val ended = pass(phone)
        assertEquals(YouTubeAuto.Ended(emptyList(), YouTubeAuto.Stop.NOTHING_DUE), ended)
        assertEquals(before, phone.database.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } })
        assertEquals(0, phone.parts.queue.snapshot().size)
    }

    /** Out of date (Outdated.state) stops the pass until a new yt-dlp or 7 days. */
    @Test fun outOfDateStopsThePass() {
        val phone = phone(listOf("One"))
        val ended = runBlocking { YouTubeAuto(phone.parts, { null }, { false }, outdated = { _, _ -> "nsig extraction failed" }).pass() }
        assertEquals(YouTubeAuto.Stop.OUTDATED, ended.stopped)
        assertEquals(emptyList(), phone.asked)
    }
}
