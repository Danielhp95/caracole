package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.youtube.FakeYtDlpProcess
import io.github.danielhp95.caracole.core.testing.youtube.FakeYtDlpProcess.Planned
import java.io.File
import java.net.InetAddress
import java.net.Socket
import java.nio.file.Files
import java.time.Instant
import java.util.Base64
import java.util.concurrent.TimeoutException
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * YtDlp's phone half, which Python's runner hasn't (runs.jsonl holds the rest, YouTubeReplay): the gate's `proxyArg`
 * in every run, a refusal of the gate read from its log first, `beforeRun`, the gate's secret written nowhere, the
 * phone's classes, the pause after the last run kv `http:last_request:youtube` keeps. Every gate is a real HostGate in
 * loopback mode; yt-dlp is [FakeYtDlpProcess]: no test reaches a real host.
 */
class YtDlpTest {
    private val data = YouTubeData.read()
    private val dir: File = Files.createTempDirectory("caracole-ytdlp").toFile()
    private val database: Database = TestDb.fresh(dir)
    private val gate = HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
    private val opened = gate.start()
    private val started = Instant.parse("2026-11-26T12:00:00Z")
    private var t = 1000.0
    private val slept = mutableListOf<Double>()
    private val drawn = mutableListOf<Pair<Double, Double>>()
    private val pacing = Pacing(sleep = { slept += it; t += it }, draws = Draws { low, high -> drawn += low to high; 5.0 },
                                wallSeconds = { 1_795_000_000.0 + t }, monotonic = { t }, clock = { started })
    private val policy = PhoneConfig.DEFAULTS.provider("youtube")
    private val id = "dQw4w9WgXcQ"

    @AfterTest
    fun close() {
        gate.close()
        database.close()
        dir.deleteRecursively()
    }

    private fun <T> db(block: (Db) -> T): T {
        var out: T? = null
        database.writeBlocking { out = block(it) }
        @Suppress("UNCHECKED_CAST")
        return out as T
    }

    private fun runner(db: Db, fake: FakeYtDlpProcess, budget: Int = 6, beforeRun: () -> String? = { null },
                       heard: MutableList<Event>? = null, lines: MutableList<String>? = null) =
        YtDlp(fake, policy, File(dir, "cache"), "/qjs", { YtDlpGate.keptOpen(opened) }, YtDlp.Writes.of(db), pacing, budget = budget,
              runId = "youtube-test",
              beforeRun = beforeRun, onEvent = heard?.let { h -> { e: Event -> h += e } },
              onLine = { line -> lines?.add(line) })

    private fun ok(stdout: String = "{\"entries\": []}") = Ran(0, stdout, "")
    private fun failed(stderr: String) = Ran(1, "", stderr)

    private fun events(db: Db) = db.query("SELECT url, status, decision, message FROM events ORDER BY id") {
        listOf(it.text(0), it.long(1), it.text(2), it.text(3))
    }

    /** During a run, what yt-dlp would do: ask the gate (its address from the run's argv) for [target]. */
    private fun asks(target: String): (List<String>) -> Unit = { argv ->
        assertTrue(opened.proxyArg in argv)
        val credentials = opened.proxyArg.substringAfter("//").substringBefore('@')
        Socket(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), opened.port).use { s ->
            s.soTimeout = 10_000
            s.getOutputStream().write(("CONNECT $target HTTP/1.1\r\nProxy-Authorization: Basic " +
                Base64.getEncoder().encodeToString(credentials.toByteArray()) + "\r\n\r\n").toByteArray())
            s.getInputStream().read()
        }
    }

    @Test
    fun everyRunIsGivenTheGatesProxyArgOnceInThePhonesTemplate() = db { db ->
        val fake = FakeYtDlpProcess.of(ok(), ok("{\"id\": \"$id\"}"))
        val yt = runner(db, fake)
        yt.search("Radiohead Creep")
        yt.video(id)
        assertEquals(listOf(
            data.argv("search", data.searchTarget("Radiohead Creep"), File(File(dir, "cache"), "yt-dlp").path, "/qjs",
                      opened.proxyArg),
            data.argv("video", data.watchUrl(id), File(File(dir, "cache"), "yt-dlp").path, "/qjs", opened.proxyArg),
        ), fake.argvs)
        assertTrue(fake.argvs.all { argv -> argv.count { it == opened.proxyArg } == 1 })
        assertEquals(listOf(data.number("search_timeout"), data.number("search_timeout")), fake.timeouts)
    }

    @Test
    fun aRefusalOfTheGateIsAnErrorInTheDatasWordsDecidedBeforeStderrAndNeverABlock() = db { db ->
        val heard = mutableListOf<Event>()
        val fake = FakeYtDlpProcess(listOf(
            // yt-dlp asked for the attestation host, and then said what a block says: the gate's log decides.
            Planned(failed("ERROR: unable to download video data: HTTP Error 403: Forbidden"), asks("jnn-pa.googleapis.com:443")),
            // Exit 0, but the gate refused a host: still the refusal.
            Planned(ok(), asks("example.com:443")),
            Planned(ok()),
        ))
        val yt = runner(db, fake, heard = heard)
        val first = assertFailsWith<GateRefused> { yt.download(id, dir) }
        val words = data.text("refusal", data.gate)
        assertEquals(YouTubeData.fillAll(words, mapOf("host" to "jnn-pa.googleapis.com")), first.msg)
        assertEquals("jnn-pa.googleapis.com", first.host)
        val second = assertFailsWith<GateRefused> { yt.search("x") }
        assertEquals("example.com", second.host)
        assertEquals(emptyList(), yt.search("y"), "a refusal before a run is no refusal of it; and no block stops it")
        assertNull(Health.state(db, "youtube").cooldownUntil)
        assertEquals(listOf("error", "error", "ok"), heard.map { it.decision })
        assertEquals(3, yt.requestsMade)
    }

    @Test
    fun aBlockIsRecordedOnceAndEveryLaterRunIsRefusedWithNoProcess() = db { db ->
        val fake = FakeYtDlpProcess.of(failed("ERROR: unable to download video data: HTTP Error 429: Too Many Requests"))
        val yt = runner(db, fake)
        val e = assertFailsWith<ProviderBlocked> { yt.search("a") }
        assertEquals(429, e.status)
        assertFailsWith<ProviderBlocked> { yt.search("b") }
        assertFailsWith<ProviderBlocked> { yt.download(id, dir) }
        assertEquals(1, fake.argvs.size)
        val state = Health.state(db, "youtube")
        assertEquals(started.plusSeconds(26 * 3600), state.cooldownUntil)
        assertEquals(e.message, state.lastError)
        assertEquals(1, events(db).size)
    }

    @Test
    fun outOfDateIsThePhonesOwnClassAndRecordsNoBlock() = db { db ->
        val fake = FakeYtDlpProcess.of(failed("ERROR: [youtube] $id: Unable to extract player version"),
                                       failed("ERROR: [youtube] $id: Requested format is not available"), ok())
        val yt = runner(db, fake)
        assertFailsWith<ExtractorOutdated> { yt.download(id, dir) }
        val passed = assertFailsWith<VideoUnavailable> { yt.download(id, dir) }
        assertIs<PassedOver>(passed, "a pass-over is a VideoUnavailable the caller tells apart by its class")
        yt.search("next")
        assertNull(Health.state(db, "youtube").cooldownUntil)
        assertFalse(VideoUnavailable("youtube", null, null, "x") is PassedOver)
    }

    @Test
    fun aRunBeforeRunRefusesStartsNoProcessSpendsNothingAndWritesNoEvent() = db { db ->
        var metered = true
        val fake = FakeYtDlpProcess.of(ok())
        val yt = runner(db, fake, budget = 1, beforeRun = { if (metered) "waiting for Wi-Fi" else null })
        val e = assertFailsWith<RunHeldBack> { yt.search("a") }
        assertEquals("youtube: ytsearch8:a: waiting for Wi-Fi", e.message)
        assertEquals(0, yt.requestsMade)
        assertEquals(emptyList(), events(db))
        assertNull(db.kvGet(Pace.LAST_SENT + "youtube"))
        metered = false
        yt.search("a")
        assertEquals(1, yt.requestsMade)
    }

    @Test
    fun theBudgetsEventIsWrittenOnce() = db { db ->
        val yt = runner(db, FakeYtDlpProcess.of(ok()), budget = 1)
        yt.search("a")
        repeat(3) { assertFailsWith<BudgetExhausted> { yt.search("b") } }
        assertEquals(listOf("ok", "budget"), events(db).map { it[2] })
        assertEquals(YouTubeData.fillAll(data.text("budget_spent", data.runner), mapOf("budget" to "1")), events(db)[1][3])
    }

    @Test
    fun theGatesSecretIsInNoEventKvRecordExceptionOrLine() = db { db ->
        val (user, key) = opened.proxyArg.substringAfter("//").substringBefore('@').split(':')
        val said = "ERROR: Unable to connect to proxy ${opened.proxyArg}: user $user key $key"
        val lines = mutableListOf<String>()
        val fake = FakeYtDlpProcess(listOf(
            Planned(failed(said)),
            Planned(failed("ERROR: unable to download video data: HTTP Error 403 via ${opened.proxyArg}")),
        ))
        val yt = runner(db, fake, lines = lines)
        val messages = mutableListOf<String?>()
        messages += assertFailsWith<ProviderError> { yt.search("a") }.message
        messages += assertFailsWith<ProviderBlocked> { yt.search("b") }.message
        val yt2 = runner(db, FakeYtDlpProcess(listOf(Planned(ok(), notStarted = "can't start yt-dlp: ${opened.proxyArg}"))))
        messages += assertFailsWith<ProviderError> { yt2.search("c") }.message
        val written = events(db).toString() + db.query("SELECT key, value FROM kv") { it.text(0) + "=" + it.text(1) }
        for (text in messages + lines + written) {
            for (s in listOf(user, key, opened.proxyArg)) assertFalse(text!!.contains(s), "the secret in: $text")
        }
        assertTrue(messages[0]!!.contains(data.placeholders.getValue("proxy")), messages[0])
        assertTrue(lines.isNotEmpty())
    }

    @Test
    fun aTimeoutIsAnErrorInTheComputersWords() = db { db ->
        val yt = runner(db, FakeYtDlpProcess.of(Ran.timedOut()))
        val e = assertFailsWith<ProviderError> { yt.search("slow") }
        assertIs<TimeoutException>(e.cause)
        assertEquals("youtube: ytsearch8:slow: yt-dlp took longer than 120 s and was stopped", e.message)
        assertEquals(1, yt.requestsMade)
    }

    @Test
    fun aYtDlpThatCantStartIsAnErrorThatSpendsNothing() = db { db ->
        val yt = runner(db, FakeYtDlpProcess(listOf(Planned(ok(), notStarted = "no :youtube process"))))
        assertEquals("youtube: ytsearch8:a: no :youtube process", assertFailsWith<NotSent> { yt.search("a") }.message)
        assertEquals(0, yt.requestsMade)
        assertEquals(emptyList(), events(db))
    }

    @Test
    fun theFirstRunWaitsOutThePauseAfterThisSidesLastRunAndTheNextItsOwn() = db { db ->
        db.kvSet(Pace.LAST_SENT + "youtube", PyFormat.fixed(1_795_000_000.0 + t - 1.5, 3))
        val yt = runner(db, FakeYtDlpProcess.of(ok(), ok()))
        yt.search("a")
        assertEquals(listOf(policy.delay), drawn)
        assertEquals(listOf(5.0 - 1.5), slept)
        t += 2.0
        yt.search("b")
        assertEquals(listOf(policy.delay, policy.delay), drawn)
        assertEquals(listOf(3.5, 3.0), slept)
        assertEquals(listOf("ok", "ok"), events(db).map { it[2] })
        assertEquals(PyFormat.fixed(1_795_000_000.0 + t, 3), db.kvGet(Pace.LAST_SENT + "youtube"))
    }

    @Test
    fun aDownloadLeavesItsAudioInTheFolderOrIsAnError() = db { db ->
        val into = File(dir, "into").also { it.mkdir() }
        val line = "{\"id\": \"$id\", \"title\": \"Creep\", \"channel\": \"Radiohead - Topic\", \"duration\": 239, " +
            "\"filepath\": \"${into.path}/audio.m4a\"}"
        val fake = FakeYtDlpProcess(listOf(
            Planned(ok(line), during = { File(into, "audio.m4a").writeText("AAC") }),
            Planned(ok(line.replace("audio.m4a", "audio.webm")), during = { File(into, "audio.webm").writeText("x") }),
        ))
        val yt = runner(db, fake)
        assertEquals(Download(File(into, "audio.m4a"), Video(id, "Creep", "Radiohead - Topic", 239.0)), yt.download(id, into))
        val e = assertFailsWith<ProviderError> { yt.download(id, into) }
        assertEquals(YouTubeData.fillAll(data.text("no_audio_left", data.runner), mapOf("folder" to "into")), e.msg)
        assertTrue(fake.argvs.all { it.any { a -> a.startsWith(into.path + "/") } })
    }

    // Fix round 1 of Y1.3's review.

    /** A gate a run, each started fresh, kept for the test to look at once closed. */
    private class Fresh : () -> YtDlpGate {
        val opened = mutableListOf<HostGate.Opened>()
        override fun invoke(): YtDlpGate =
            HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE).start().also { opened += it }
    }

    private fun freshRunner(db: Db, fake: FakeYtDlpProcess, gates: () -> YtDlpGate, budget: Int = 6) =
        YtDlp(fake, policy, File(dir, "cache"), "/qjs", gates, YtDlp.Writes.of(db), pacing, budget = budget, runId = "youtube-test")

    /** Whether the gate is gone: its port refuses, and no thread of it is left. */
    private fun closed(opened: HostGate.Opened): Boolean {
        val refuses = try {
            Socket(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), opened.port).close()
            false
        } catch (_: java.net.ConnectException) {
            true
        }
        val threads = Thread.getAllStackTraces().keys.filter { it.isAlive && it.name.startsWith("caracole-gate-${opened.port}-") }
        return refuses && threads.isEmpty()
    }

    @Test
    fun theGateARunOpenedIsClosedAfterItOnEveryPath() = db { db ->
        val gates = Fresh()
        val fake = FakeYtDlpProcess(listOf(
            Planned(ok()),
            Planned(failed("ERROR: x"), during = { throw IllegalStateException("the process broke") }),
            Planned(ok(), notStarted = "no :youtube process"),
            Planned(Ran.timedOut()),
            Planned(failed("ERROR: unable to download video data: HTTP Error 403: Forbidden"),
                    during = { argv -> asksThrough(argv, "jnn-pa.googleapis.com:443") }),
        ))
        val yt = freshRunner(db, fake, gates)
        yt.search("ok")
        assertFailsWith<YouTubeData.Refused> { yt.search("a NUL \u0000 in it") }
        assertFailsWith<RunCutOff> { yt.search("broken") }  // started, then cut off: the phone's own, said so
        assertFailsWith<ProviderError> { yt.search("not started") }
        assertFailsWith<ProviderError> { yt.search("slow") }
        assertFailsWith<GateRefused> { yt.search("refused") }
        assertEquals(6, gates.opened.size, "one gate a run, the refused argv's too")
        for (g in gates.opened) assertTrue(closed(g), "the gate at ${g.port} is closed")
        assertEquals(0, fake.unmade)
    }

    /** As [asks], through the gate whose address is in [argv]. */
    private fun asksThrough(argv: List<String>, target: String) {
        val arg = argv.first { it.startsWith("http://") && '@' in it }
        val port = arg.substringAfterLast(':').toInt()
        val credentials = arg.substringAfter("//").substringBefore('@')
        Socket(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), port).use { s ->
            s.soTimeout = 10_000
            s.getOutputStream().write(("CONNECT $target HTTP/1.1\r\nProxy-Authorization: Basic " +
                Base64.getEncoder().encodeToString(credentials.toByteArray()) + "\r\n\r\n").toByteArray())
            s.getInputStream().read()
        }
    }

    @Test
    fun aGateKeptOpenForTheJobIsNotClosedByARun() = db { db ->
        val yt = runner(db, FakeYtDlpProcess.of(ok(), ok()))
        yt.search("a")
        yt.search("b")
        assertFalse(closed(opened), "the job's gate is still open")
    }

    @Test
    fun aProviderCoolingFromAnEarlierJobRefusesTheFirstRunWithNothingStarted() = db { db ->
        Health.recordBlock(db, "youtube", started.minusSeconds(3600), "youtube: 429: an earlier job's block")
        val before = Health.state(db, "youtube")
        val fake = FakeYtDlpProcess(emptyList())
        val yt = freshRunner(db, fake, { throw AssertionError("a gate opened for a run that can't be") })
        val e = assertFailsWith<ProviderBlocked> { yt.search("a") }
        assertEquals("youtube: ytsearch8:a: waiting out YouTube until 2026-11-27 13:00 UTC", e.message)
        assertEquals(emptyList(), fake.argvs)
        assertEquals(emptyList(), events(db))
        assertNull(db.kvGet(Pace.LAST_SENT + "youtube"))
        assertEquals(before, Health.state(db, "youtube"), "no new strike")
        assertEquals(0, yt.requestsMade)
    }

    @Test
    fun aBlockTheRunnerRecordsIsOneStrikeAndTheNextJobsRunnerRefusesWithoutAnother() = db { db ->
        val first = runner(db, FakeYtDlpProcess.of(failed("ERROR: unable to download video data: HTTP Error 429: Too Many Requests")))
        assertFailsWith<ProviderBlocked> { first.search("a") }
        val after = Health.state(db, "youtube")
        assertEquals(java.math.BigInteger.ONE, after.strikes)
        val fake = FakeYtDlpProcess(emptyList())
        assertFailsWith<ProviderBlocked> { runner(db, fake).search("b") }
        assertEquals(after, Health.state(db, "youtube"))
        assertEquals(emptyList(), fake.argvs)
        assertEquals(1, events(db).size)
    }

    @Test
    fun aRunCutOffByAnExceptionIsCountedLoggedAndSaidWithoutTheSecret() = db { db ->
        val (user, key) = opened.proxyArg.substringAfter("//").substringBefore('@').split(':')
        val fake = FakeYtDlpProcess(listOf(
            Planned(ok(), during = { throw IllegalStateException("the service died running ${opened.proxyArg}") }),
            Planned(ok(), during = { throw InterruptedException("stopped: $user:$key") }),
        ))
        val yt = runner(db, fake)
        val broken = assertFailsWith<ProviderError> { yt.search("a") }
        val stopped = assertFailsWith<InterruptedException> { yt.search("b") }
        assertTrue(Thread.interrupted(), "the interrupt is kept")
        assertEquals(2, yt.requestsMade, "each was started: the day's budget counts them")
        val rows = events(db)
        assertEquals(listOf("error", "error"), rows.map { it[2] })
        assertTrue(db.kvGet(Pace.LAST_SENT + "youtube") != null, "the next job's pause sees them")
        for (text in listOf(broken.message, stopped.message) + rows.map { it[3] as String? }) {
            for (secret in listOf(user, key, opened.proxyArg)) assertFalse(text!!.contains(secret), "the secret in: $text")
        }
    }

    // The runner's re-review.

    @Test
    fun aRunWhoseGateStoppedIsAnErrorInTheGatesWordsNeverABlock() = db { db ->
        gate.afterAccepting = { throw NoSuchElementException("a bug in the acceptor") }
        val fake = FakeYtDlpProcess(listOf(Planned(failed("ERROR: Unable to download API page: Connection refused"),
                                                   during = asks("www.youtube.com:443"))))
        val e = assertFailsWith<ProviderError> { runner(db, fake).search("Radiohead Creep") }
        assertTrue(e !is ProviderBlocked)
        val said = data.text("stopped_said", data.gate)
        assertTrue(e.message!!.endsWith(said), e.message)
        assertEquals(listOf("error", said), events(db).single().let { listOf(it[2], it[3]) })
    }
}
