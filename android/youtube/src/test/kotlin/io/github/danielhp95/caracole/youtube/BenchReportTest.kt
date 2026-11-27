package io.github.danielhp95.caracole.youtube

import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files
import java.time.Duration
import java.time.Instant
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The YouTube bench on the JVM: [BenchReport]'s numbers from stamped synthetic lines and fixed timings (the challenge,
 * the requests after a block, each gate's numbers, idle), and [BenchRun]'s terms over fakes and a real database
 * ([DbLedger]): the day's six counted from the bench's own record and `events`, the 7th run refused, a block that
 * stops the session and is recorded once, the pause after the phone's last run, a public host's query refused under
 * loopback before any run.
 */
class BenchReportTest {
    private val dir: File = Files.createTempDirectory("caracole-ytbench-").toFile()
    private val db = TestDb.fresh(dir)

    @AfterTest
    fun clean() {
        db.close()
        dir.deleteRecursively()
    }

    private fun run(song: String = "A - T", kind: String = "download", cache: String? = "cold", seconds: Double = 10.0,
                    lines: List<Stamped> = emptyList(), outcome: String = "ok",
                    hosts: Map<String, HostGate.HostUse> = emptyMap(), python: Long = 900,
                    decoded: JsonObject? = null, file: JsonObject? = null, pss: Map<String, Double> = emptyMap()) =
        BenchRunRecord(song, kind, cache, "2026-11-26T20:00:00Z", 100, python, seconds, 4.0, lines, outcome, null, hosts,
                       1000, pss, file, decoded)

    private fun report(runs: List<BenchRunRecord>, idle: BenchIdle = BenchIdle(5, 5, 2, 2, false, false)) =
        BenchReport.of(JsonObject(mapOf("device" to JsonPrimitive("x"))), JsonObject(emptyMap()), "enforce",
                       "NETWORK", "2026-11-26T20:00:00Z", idle, 0 to runs.size, 6, runs,
                       JsonObject(mapOf("run" to JsonPrimitive(true), "left" to kotlinx.serialization.json.JsonArray(emptyList()))),
                       JsonObject(emptyMap()), null)

    @Test
    fun `the challenge's time comes from its stamped lines`() {
        val lines = listOf(
            Stamped(1_000, "[youtube] aaaaaaaaaaa: Downloading tv client config"),
            Stamped(2_000, "[youtube] aaaaaaaaaaa: Downloading tv player API JSON"),
            Stamped(4_500, "[youtube] [jsc:quickjs] Solving JS challenges using quickjs"),
            Stamped(4_600, "[debug] [youtube] [jsc:quickjs] Running QuickJS: …"),
            Stamped(9_750, "[info] aaaaaaaaaaa: Downloading 1 format(s): 140"),
            Stamped(10_000, "[download] Sleeping 3.21 seconds ..."),
        )
        val c = BenchReport.challenge(lines)!!
        assertEquals(5.25, c.getValue("seconds").jsonPrimitive.double, 1e-9)
        assertEquals("quickjs", c.getValue("runtime").jsonPrimitive.content)
        assertEquals(3.21, BenchReport.sleeps(lines), 1e-9)
        assertEquals(listOf("tv"), BenchReport.clients(lines))
        assertNull(BenchReport.challenge(lines.take(2)))
    }

    @Test
    fun `the requests after a block are the gates' connects of every later run`() {
        val use = { n: Int -> mapOf("www.youtube.com" to HostGate.HostUse(connects = n)) }
        val runs = listOf(run(kind = "search", hosts = use(2)), run(outcome = "blocked", hosts = use(3)),
                          run(song = "B - U", kind = "search", hosts = use(4)))
        assertEquals(4, BenchReport.afterBlockRequests(runs))
        assertEquals(0, BenchReport.afterBlockRequests(runs.take(2)))
        assertEquals(4, report(runs).getValue("summary").jsonObject.getValue("B").jsonObject
            .getValue("after_block_requests").jsonPrimitive.int)
    }

    @Test
    fun `the gates' numbers from fixed timings`() {
        val challenge = listOf(Stamped(1_000, "Solving JS challenges using quickjs"), Stamped(13_000, "[info] next"),
                               Stamped(14_000, "[download] Sleeping 2.0 seconds ..."))
        val runs = listOf(
            run(song = "A - T", kind = "search", cache = null, seconds = 5.0, python = 3_000),
            run(song = "A - T", cache = "cold", seconds = 20.0, lines = challenge, python = 1_200,
                hosts = mapOf("rr1.googlevideo.com" to HostGate.HostUse(1, 100, 900)),
                file = JsonObject(mapOf("duration" to JsonPrimitive(240.0))),
                decoded = JsonObject(mapOf("rate" to JsonPrimitive(44_100), "frames" to JsonPrimitive(44_100 * 240 + 22_050))),
                pss = mapOf("youtube" to 120.0, "qjs" to 200.0)),
            run(song = "B - U", cache = "warm", seconds = 9.0, python = 1_000),
        )
        val s = report(runs).getValue("summary").jsonObject
        assertEquals(12.0, s["T"]!!.jsonObject["cold_challenge_s"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(23.0, s["T"]!!.jsonObject["cold_whole_s_less_sleeps"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(listOf(9.0), s["T"]!!.jsonObject["warm_downloads_s"]!!.jsonArray.map { it.jsonPrimitive.double })
        assertEquals(0.5, s["F"]!!.jsonObject["decoded_vs_duration_s"]!!.jsonArray.single().jsonPrimitive.double, 1e-9)
        assertEquals(320.0, s["M"]!!.jsonObject["pss_peak_mb"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(3_000.0, s["C"]!!.jsonObject["first_python_ready_ms"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(1_000.0, s["C"]!!.jsonObject["least_later_python_ready_ms"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(listOf("rr1.googlevideo.com"), s["H"]!!.jsonObject["hosts"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals(2, s["W"]!!.jsonObject["songs"]!!.jsonPrimitive.int)
        assertEquals(2, s["W"]!!.jsonObject["downloads_ok"]!!.jsonPrimitive.int)
    }

    @Test
    fun `idle is false once the server served a request during the session`() {
        assertTrue(report(emptyList()).getValue("idle").jsonPrimitive.boolean)
        assertFalse(report(emptyList(), BenchIdle(5, 6, 2, 2, false, false)).getValue("idle").jsonPrimitive.boolean)
        assertFalse(report(emptyList(), BenchIdle(5, 5, 2, 3, false, false)).getValue("idle").jsonPrimitive.boolean)
        assertFalse(report(emptyList(), BenchIdle(5, 5, 2, 2, false, true)).getValue("idle").jsonPrimitive.boolean)
    }

    @Test
    fun `no gate-shaped address and no debug line is kept`() {
        val proxy = "http://${"a".repeat(32)}:${"b".repeat(32)}@127.0.0.1:4000"
        val lines = listOf(Stamped(1, "[debug] Proxy map: {'all': '$proxy'}"), Stamped(2, "WARNING: via $proxy"),
                           Stamped(3, "ERROR: [youtube] x: Sign in to confirm you're not a bot"))
        val text = report(listOf(run(lines = lines, outcome = "blocked"))).toString()
        assertFalse("a".repeat(32) in text || "b".repeat(32) in text, text)
        assertFalse("Proxy map" in text, text)
        assertTrue("Sign in to confirm" in text, text)
    }

    // -- BenchRun's terms, over fakes and the database ------------------------------------------------------------

    private var now = Instant.parse("2026-11-26T20:00:00Z")
    private var monotonic = 1_000.0
    private val slept = mutableListOf<Double>()
    private val clock = BenchRun.Clock({ now }, { now.epochSecond.toDouble() }, { monotonic },
                                       { s -> slept += s; monotonic += s; now = now.plusMillis((s * 1000).toLong()) },
                                       Draws { low, _ -> low })
    private val opened = mutableListOf<String>()
    private var stderr: (List<String>) -> String = { "" }
    private var exit = 0
    private val ran = mutableListOf<List<String>>()

    /** What the fakes do wrong, a test at a time: the run's own exception, the gate's log or close, the record. */
    private var runThrows: (() -> Exception)? = null
    private var logThrows = false
    private var closeThrows = false
    private var recordThrows = false
    private var gateLog: Map<String, HostGate.HostUse> = emptyMap()
    private val killed = mutableListOf<List<String>>()
    private val loopbackGates = mutableListOf<String>()
    /** The day's runs as the ledger counted them while each run went. */
    private val countedDuring = mutableListOf<Int>()

    private val ledger = object : BenchRun.Ledger {
        override fun state() = db.read { DbLedger.state(it, now, 0, 0, false) }
        override fun reserve(first: Boolean) =
            db.writeBlocking { DbLedger.reserve(it, now, first, Draws { low, _ -> low }) { now.epochSecond.toDouble() } }
        override fun release(stamp: String) = db.writeBlocking { DbLedger.release(it, stamp) }
        override fun record(entry: BenchRun.Entry, sessionStart: Instant) {
            if (recordThrows) throw java.io.IOException("the bench's ledger didn't answer")
            db.writeBlocking { DbLedger.record(it, entry, now, now.epochSecond.toDouble(), sessionStart) }
        }
    }

    private fun runs(): Int = db.read { DbLedger.runs(it, now) }

    private fun events(): Long = db.read { d -> d.one("SELECT COUNT(*) FROM events WHERE provider = 'youtube'") { it.long(0) }!! }

    private fun bench(mode: HostGate.Mode = HostGate.Mode.NETWORK): BenchRun {
        val runner = object : BenchRun.Runner {
            override fun run(argv: List<String>, folders: RunFolders, timeoutS: Double, verbose: Boolean): BenchRan {
                ran += argv
                countedDuring += runs()
                monotonic += 2.0
                now = now.plusSeconds(2)
                runThrows?.let { throw it() }
                val search = argv.last().startsWith("ytsearch")
                // A search finds the song it asked for: its title and its artist's channel.
                val parts = argv.last().substringAfter(":").split(" - ")
                val (artist, title) = parts.first() to parts.last()
                val out = if (search) """{"entries": [{"id": "aaaaaaaaaaa", "title": "$title", "channel": "$artist", "duration": 200}]}"""
                          else ""
                return BenchRan(Ran(exit, out, stderr(argv), false, false, 100, 900), stderr(argv).lines()
                    .filter { it.isNotEmpty() }.map { Stamped(1, it) })
            }

            override fun cancel() {}
        }
        val killRunner = object : BenchRun.Runner {
            override fun run(argv: List<String>, folders: RunFolders, timeoutS: Double, verbose: Boolean): BenchRan {
                killed += argv
                return BenchRan(Ran(if ("--version" in argv) 0 else -1, "", "", "--version" !in argv, false, 1, 1),
                                emptyList())
            }

            override fun cancel() {}
        }
        val gates = object : BenchRun.Gates {
            override val mode = mode
            override fun open(observe: Boolean): BenchRun.Gate {
                opened += if (observe) "observe" else "enforce"
                return gate()
            }

            override fun openLoopback(): BenchRun.Gate {
                loopbackGates += "loopback"
                return gate()
            }

            private fun gate() = object : BenchRun.Gate {
                override val proxyArg = "http://${"a".repeat(32)}:${"b".repeat(32)}@127.0.0.1:4000"
                override fun log(): Map<String, HostGate.HostUse> {
                    if (logThrows) throw java.io.IOException("the gate's service didn't answer")
                    return gateLog
                }
                override fun close() {
                    if (closeThrows) throw java.io.IOException("the gate's service didn't answer")
                }
            }
        }
        val probe = object : BenchRun.Probe {
            override fun device() = JsonObject(emptyMap())
            override fun network() = JsonObject(emptyMap())
            override fun uidBytes(): Long? = null
            override fun sample(): () -> Map<String, Double> = { emptyMap() }
            override fun decode(file: File): JsonObject? = null
            override fun pythonExtracted() = true
            override fun leftover() = emptyList<String>()
        }
        return BenchRun(runner, killRunner, gates, ledger, probe, clock, BenchRun.Folders(File(dir, "bench")), "/qjs")
    }

    /** [n] runs of provider youtube in `events`, as a product job would have sent them, [ago] before now. */
    private fun sentBefore(n: Int, ago: Duration = Duration.ofHours(1)) = db.writeBlocking { d ->
        repeat(n) {
            d.execute("INSERT INTO events (run, at, provider, url, status, decision, message) VALUES " +
                      "('youtube-sheet:x', ?, 'youtube', 'u', NULL, 'ok', NULL)",
                      utc(now.minus(ago)))
        }
    }

    @Test
    fun `a session that would pass the day's six is refused, and says how many runs are left`() {
        sentBefore(5)
        val e = assertFailsWith<BenchRun.Refused> { bench().session(listOf("A - T"), false) }
        assertEquals(BenchRun.budgetWords(2, 1, 6), e.words)
        assertTrue(ran.isEmpty() && opened.isEmpty())
        // Runs older than 24 hours count no more.
        db.writeBlocking { it.execute("DELETE FROM events") }
        sentBefore(5, Duration.ofHours(25))
        bench().session(listOf("A - T"), false)
        assertEquals(2, ran.size)
    }

    @Test
    fun `six reservations then a seventh refused across two sessions, the bench's own and the phone's runs together`() {
        val s1 = bench().session(listOf("A - T", "B - U", "C - V"), false)
        assertEquals(6, s1.runs.size)
        assertEquals(6, s1.budgetAfter)
        assertEquals(6, runs())
        val e = assertFailsWith<BenchRun.Refused> { bench().session(listOf("aaaaaaaaaaa"), false) }
        assertEquals(BenchRun.budgetWords(1, 0, 6), e.words)
        assertEquals(6, ran.size)
        // The bench's own record counts its runs even where events lost them: still none left.
        db.writeBlocking { it.execute("DELETE FROM events") }
        assertEquals(6, runs())
        assertEquals(BenchRun.budgetWords(1, 0, 6), db.writeBlocking {
            DbLedger.reserve(it, now, false, Draws { low, _ -> low }) { 0.0 }
        }.refused)
    }

    @Test
    fun `a run is counted from its reservation, before it starts, whatever ends it`() {
        val cases = listOf<Pair<String, () -> Unit>>(
            "the process dying mid-run" to { runThrows = { IllegalStateException("killed") } },
            "the client's stop" to { runThrows = { YtDlpStopped("yt-dlp stopped") } },
            "an IOException of the run's" to { runThrows = { java.io.IOException("a socket") } },
            "the gate's log throwing" to { logThrows = true },
            "the gate's close throwing" to { closeThrows = true },
            "the record failing" to { recordThrows = true },
        )
        for ((what, fail) in cases) {
            db.writeBlocking { it.execute("DELETE FROM events"); it.execute("DELETE FROM kv WHERE key = ?", DbLedger.RUNS) }
            runThrows = null; logThrows = false; closeThrows = false; recordThrows = false
            countedDuring.clear()
            fail()
            runCatching { bench().session(listOf("aaaaaaaaaaa"), false) }
            assertEquals(listOf(1), countedDuring, "$what: counted while it ran")
            assertEquals(1, runs(), "$what: counted after")
            if (!recordThrows) assertEquals(1L, events(), "$what: its events row")
        }
    }

    @Test
    fun `a run that never started gives its slot back`() {
        for (thrown in listOf<() -> Exception>({ YtDlpNotStarted("no bind") }, { Refused("the glue's words") })) {
            runThrows = thrown
            val s = bench().session(listOf("aaaaaaaaaaa"), false)
            assertEquals(1, countedDuring.last(), "reserved while it went")
            assertEquals(0, runs())
            assertEquals(0L, events())
            assertEquals("error", s.runs.single().outcome)
        }
    }

    @Test
    fun `the gate's stopped bucket is an error in the data's words, never a block`() {
        val data = YouTubeData.read()
        gateLog = mapOf(data.text("stopped", data.gate) to HostGate.HostUse())
        val s = bench().session(listOf("aaaaaaaaaaa"), false)
        assertEquals("error", s.runs.single().outcome)
        assertEquals(data.text("stopped_said", data.gate), s.runs.single().reason)
        assertFalse(db.read { Health.isCooling(it, "youtube", now) })
    }

    @Test
    fun `the kill check runs on the network too, on a loopback gate, spending none of the six`() {
        val kill = bench().killCheck()
        assertTrue(kill.getValue("run").jsonPrimitive.boolean, kill.toString())
        assertTrue(kill.getValue("killed").jsonPrimitive.boolean)
        assertTrue(kill.getValue("next_run_ok").jsonPrimitive.boolean)
        assertEquals(listOf("loopback"), loopbackGates)
        assertTrue(opened.isEmpty())
        assertEquals(0, runs())
        assertTrue("--exec" in killed[0] && killed[0].last().startsWith("http://127.0.0.1:"), killed[0].toString())
        assertEquals("--version", killed[1].last())
    }

    @Test
    fun `an intent starts a session under loopback alone, never from Recents`() {
        assertTrue(BenchRun.startsByIntent(HostGate.Mode.LOOPBACK, go = true, fromHistory = false))
        assertFalse(BenchRun.startsByIntent(HostGate.Mode.NETWORK, go = true, fromHistory = false))
        assertFalse(BenchRun.startsByIntent(HostGate.Mode.LOOPBACK, go = true, fromHistory = true))
        assertFalse(BenchRun.startsByIntent(HostGate.Mode.LOOPBACK, go = false, fromHistory = false))
    }

    @Test
    fun `a query with a slash is a query, an address is not`() {
        val songs = bench().plan(listOf("AC/DC - Back in Black", "Sigur Rós - Hoppípolla", "aaaaaaaaaaa"), false)
        assertEquals(listOf(true, true, false), songs.map { it.search != null })
        for (q in listOf("https://www.youtube.com/watch?v=aaaaaaaaaaa", "youtube.com/watch?v=x", "ytsearch8:x",
                         "www.youtube.com")) {
            assertFailsWith<BenchRun.Refused>(q) { bench().plan(listOf(q), false) }
        }
    }

    @Test
    fun `nothing of a session's download stays but its report`() {
        bench().session(listOf("aaaaaaaaaaa"), false)
        assertEquals(emptyList(), File(dir, "bench").listFiles().orEmpty().filter { it.name.startsWith("into-") || it.name == "kill" })
    }

    /** A run whose gate's log, close or record throws out of it still leaves no download folder behind. */
    @Test
    fun `a download's folder goes even when an exception escapes its run`() {
        val into = { File(dir, "bench").listFiles().orEmpty().filter { it.name.startsWith("into-") } }
        for (fail in listOf<() -> Unit>({ logThrows = true }, { closeThrows = true }, { recordThrows = true })) {
            logThrows = false; closeThrows = false; recordThrows = false
            db.writeBlocking { it.execute("DELETE FROM events"); it.execute("DELETE FROM kv WHERE key = ?", DbLedger.RUNS) }
            fail()
            assertFailsWith<java.io.IOException> { bench().session(listOf("aaaaaaaaaaa"), false) }
            assertEquals(emptyList(), into())
        }
    }

    @Test
    fun `a run refused mid-session when another job spent the day's runs meanwhile`() {
        sentBefore(4)
        var once = true
        stderr = { if (once) { once = false; sentBefore(1) }; "" }
        val s = bench().session(listOf("A - T"), false)
        assertEquals(1, ran.size)
        assertEquals(1, s.runs.size)
        assertEquals(BenchRun.budgetWords(1, 0, 6), s.stopped)
    }

    @Test
    fun `a block stops the session, is recorded once, and no session starts while it cools`() {
        exit = 1
        stderr = { "ERROR: [youtube] x: Sign in to confirm you're not a bot\n" }
        val s = bench().session(listOf("A - T", "B - U"), false)
        assertEquals(1, ran.size)
        assertEquals(BenchRun.BLOCKED_STOP, s.stopped)
        assertEquals("blocked", s.runs.single().outcome)
        assertTrue(db.read { Health.isCooling(it, "youtube", now) })
        assertEquals(1, db.read { d -> d.one("SELECT COUNT(*) FROM events WHERE decision = 'blocked'") { it.long(0) } })
        val e = assertFailsWith<BenchRun.Refused> { bench().session(listOf("C - V"), false) }
        assertTrue("cooling" in e.words, e.words)
        assertEquals(1, ran.size)
    }

    @Test
    fun `every run is an events row, a search's under youtube-search, and paused after the phone's last run`() {
        db.writeBlocking { it.kvSet(Pace.LAST_SENT + "youtube", (now.epochSecond - 1).toString()) }
        bench().session(listOf("A - T"), false)
        val rows = db.read { d ->
            d.query("SELECT run, decision FROM events WHERE provider = 'youtube' ORDER BY id") { it.text(0) to it.text(1) }
        }
        assertEquals(2, rows.size)
        assertTrue(rows[0].first!!.startsWith(BenchRun.SEARCH_RUN), rows.toString())
        assertTrue(rows[1].first!!.startsWith(BenchRun.DOWNLOAD_RUN), rows.toString())
        // The first pause: the delay's draw (3.75) less the second since the phone's last run; then the draw less the
        // time since the search ended (none here).
        assertEquals(listOf(2.75, 3.75), slept.take(2))  // then the kill check's own wait
        // The search's argv: the phone's template, with the bench's -v; the download the chosen video's address.
        assertTrue("-v" in ran[0], ran[0].toString())
        assertEquals(YouTubeData.read().searchTarget("A - T"), ran[0].last())
        assertEquals(YouTubeData.read().watchUrl("aaaaaaaaaaa"), ran[1].last())
    }

    @Test
    fun `under loopback a public host's query is refused before any run, and observe is never asked`() {
        for (q in listOf("A - T", "https://www.youtube.com/watch?v=aaaaaaaaaaa", "http://example.org/clip.m4a",
                         "http://u@127.0.0.1/clip.m4a")) {
            assertFailsWith<BenchRun.Refused> { bench(HostGate.Mode.LOOPBACK).session(listOf(q), false) }
        }
        assertEquals(BenchRun.NO_OBSERVE, assertFailsWith<BenchRun.Refused> {
            bench(HostGate.Mode.LOOPBACK).session(listOf("http://10.0.2.2:8000/clip.m4a"), true)
        }.words)
        assertTrue(ran.isEmpty() && opened.isEmpty())
        assertEquals(0L, db.read { d -> d.one("SELECT COUNT(*) FROM events") { it.long(0) } })
        // Four lines are more than the day allows.
        assertFailsWith<BenchRun.Refused> { bench().session(listOf("a - b", "c - d", "e - f", "g - h"), false) }
    }

    @Test
    fun `a loopback address is the search's and the download's target`() {
        val url = "http://10.0.2.2:8000/clip.m4a"
        val s = bench(HostGate.Mode.LOOPBACK).session(listOf(url), false)
        assertEquals(listOf(url, url), ran.take(2).map { it.last() })
        assertEquals("loopback", s.runs[1].chosenBy)
    }
}
