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
import java.time.Duration
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

    /** A pass of [phone]'s, its monotonic clock [monotonic]. */
    private fun auto(phone: Phone, monotonic: () -> Double = { System.nanoTime() / 1e9 },
                     outdated: (Db, Instant) -> String? = { _, _ -> null }) =
        YouTubeAuto(phone.parts, { null }, { false }, outdated = outdated, monotonic = monotonic)

    private fun run(auto: YouTubeAuto): YouTubeAuto.Ended = runBlocking { withTimeout(60_000) { auto.pass() } }

    /** A monotonic clock at 0 for the pass's start and its first song, then past MOST_S: one job, then TIME. */
    private fun oneSongThenTimeUp(): () -> Double {
        var calls = 0
        return { if (calls++ < 2) 0.0 else YouTubeAuto.MOST_S }
    }

    /** [phone] synced with a computer just now: paired, its noted songs alone due. */
    private fun pair(phone: Phone) = phone.database.writeBlocking { db ->
        db.kvSet("sync:base:0f1e2d3c4b5a6978", """{"format": 3, "units": {"song/x": [null, "${Stamps.of(Instant.now())}"]}}""")
    }

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

    /** The hunter's case: a paired phone's noted songs, a pass that stops at 8 minutes after the first; the two it
     * didn't reach are left, and another pass goes 2 minutes on. */
    @Test fun aPassStoppedAtEightMinutesLeavesTheSongsItDidntReachAndAsksForAnotherSoon() {
        val phone = phone(listOf("One", "Two", "Three"), noted = setOf("One", "Two", "Three"))
        pair(phone)
        val auto = auto(phone, monotonic = oneSongThenTimeUp())
        val ended = run(auto)
        assertEquals(YouTubeAuto.Stop.TIME, ended.stopped)
        assertEquals(1, phone.asked.size)
        assertEquals(2, ended.left)
        assertEquals(YouTubeAuto.AGAIN_SOON, auto.again(ended))
    }

    /** A song noted while the pass awaits its last job (soon's KEEP enqueues nothing then: its work still runs) is
     * counted at the pass's end, so another pass takes it. */
    @Test fun aSongNotedWhileThePassAwaitsItsLastJobIsLeftForTheNextPass() {
        val phone = phone(listOf("One", "Two"), noted = setOf("One"), during = { db ->
            db.execute("INSERT OR IGNORE INTO kv (key, value) SELECT 'youtube-wanted:' || id, '\"2026-11-27T00:00:00Z\"' FROM songs")
        })
        pair(phone)
        val auto = auto(phone, monotonic = oneSongThenTimeUp())
        val ended = run(auto)
        assertEquals(listOf("Calla Lake - One" to true), phone.asked)
        assertEquals(1, ended.left)
        assertEquals(YouTubeAuto.AGAIN_SOON, auto.again(ended))
    }

    /** A song the pass tried is never left for another: its job's failure waits for the next lookup or the daily. */
    @Test fun aPassThatTriedEverySongAsksForNoOther() {
        val phone = phone(listOf("One"), noted = setOf("One"))
        pair(phone)
        val auto = auto(phone, monotonic = oneSongThenTimeUp())
        val ended = run(auto)
        assertEquals(YouTubeAuto.Stop.TIME, ended.stopped)
        assertEquals(0, ended.left)
        assertEquals(null, auto.again(ended))
        val all = auto(phone(listOf("One", "Two")))
        val done = run(all)
        assertEquals(YouTubeAuto.Stop.NOTHING_DUE, done.stopped)
        assertEquals(null, all.again(done))
    }

    /** A block's cooldown: another pass once it ends (the first strike's 26 hours), plus 2 minutes. */
    @Test fun aPassStoppedByACooldownAsksForAnotherOnceItEnds() {
        val phone = phone(listOf("One", "Two"), during = { db -> Health.recordBlock(db, "youtube", Instant.now(), "bot check") })
        val auto = auto(phone)
        val ended = run(auto)
        assertEquals(YouTubeAuto.Stop.COOLING, ended.stopped)
        assertEquals(1, ended.left)
        val again = auto.again(ended)!!
        assertTrue(again > Duration.ofHours(26) && again <= Duration.ofHours(26).plusMinutes(5), "$again")
    }

    /** Fewer than 2 runs left: another pass once two are free again, the oldest runs leaving the day. */
    @Test fun aPassStoppedByTheDaysRunsAsksForAnotherOnceTwoAreFree() {
        val phone = phone(listOf("One", "Two", "Three"))
        val budget = phone.parts.config().provider("youtube").budget.toInt()
        phone.database.writeBlocking { db ->
            repeat(budget - 2) {
                db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('s', ?, 'youtube', 'u', NULL, 'ok')",
                           Stamps.of(Instant.now().minus(Duration.ofHours(23))))
            }
        }
        val auto = auto(phone)
        val ended = run(auto)
        assertEquals(YouTubeAuto.Stop.FEW_RUNS, ended.stopped)
        assertEquals(1, phone.asked.size)
        assertEquals(2, ended.left)
        val again = auto.again(ended)!!
        assertTrue(again > Duration.ofMinutes(61) && again <= Duration.ofMinutes(63), "$again")
    }

    /** Out of date, switched off: no other pass, whatever is left (a new yt-dlp, the switch turned on, asks again). */
    @Test fun aPassStoppedForAReasonThatDoesntPassByItselfAsksForNoOther() {
        val outdated = phone(listOf("One"))
        val stale = auto(outdated, outdated = { _, _ -> "nsig extraction failed" })
        val ended = run(stale)
        assertEquals(YouTubeAuto.Stop.OUTDATED, ended.stopped)
        assertEquals(1, ended.left)
        assertEquals(null, stale.again(ended))
        val off = phone(listOf("One"))
        off.database.writeBlocking { db -> YouTubeAuto.set(db, false) }
        val switched = auto(off)
        val offEnded = run(switched)
        assertEquals(YouTubeAuto.Stop.SWITCHED_OFF, offEnded.stopped)
        assertEquals(null, switched.again(offEnded))
    }

    /** The switch turned back on asks for a pass only where a song a lookup noted is due. */
    @Test fun theSwitchTurnedBackOnAsksForAPassOnlyWhereANotedSongIsDue() {
        assertEquals(false, auto(phone(listOf("One"))).notedDue())
        assertEquals(true, auto(phone(listOf("One"), noted = setOf("One"))).notedDue())
    }
}
