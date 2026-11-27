package io.github.danielhp95.caracole.youtube

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.youtube.Runs.context
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * One yt-dlp run in `:youtube` ([YtDlpService]) from this, the main process ([YtDlpClient]), through a gate of the main
 * process ([GateService], under the test runner's `caracole.network=loopback`): `--version`; youtube.json's download
 * argv over a clip of the test's own, served on 127.0.0.1 by plain HTTP (a proxied GET) and by HTTPS (a CONNECT); the
 * refusals. No request leaves the device: the gate allows 127.0.0.1 and 10.0.2.2 alone, and the service refuses a
 * target that isn't one. Run by `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class YtDlpServiceTest {
    private lateinit var gates: GateService.Client
    private lateinit var gate: GateService.Gate
    private val client = YtDlpClient(context)
    private val lines = mutableListOf<String>()

    @Before
    fun open() {
        gates = GateService.Client(context)
        gate = gates.open()
    }

    @After
    fun close() {
        client.close()
        gate.close()
        gates.close()
    }

    private fun run(argv: List<String>, timeoutS: Double = 120.0): Ran {
        val t0 = SystemClock.elapsedRealtime()
        val ran = client.run(argv, timeoutS, { _, line -> lines.add(line) }, {}, Runs.folders(argv))
        Runs.said("ran in ${SystemClock.elapsedRealtime() - t0} ms: exit ${ran.exit}, the process started at " +
            "${ran.processStartMs} ms, Python ready at ${ran.pythonReadyMs} ms")
        return ran
    }

    /** Where a download's `--print after_move:` line says the audio is, and that line's JSON. */
    private fun printed(ran: Ran): JSONObject {
        val line = ran.stdout.lines().lastOrNull { it.startsWith("{") && it.contains("\"filepath\"") }
        assertNotNull("no after_move line in stdout: ${ran.stdout}\n${ran.stderrTail}", line)
        return JSONObject(line!!)
    }

    @Test
    fun versionThroughTheGate() {
        val ran = run(Runs.version(gate.proxyArg))
        assertEquals(ran.stderrTail, 0, ran.exit)
        assertFalse(ran.killed)
        assertTrue(ran.stdout, Regex("""\d{4}\.\d+\.\d+\n""").matches(ran.stdout))
        assertTrue(ran.processStartMs >= 0 && ran.pythonReadyMs >= ran.processStartMs)
    }

    @Test
    fun theClipByAPlainHttpGetThroughTheGate() {
        LoopbackServer(Runs.clip).use { server ->
            val into = Runs.into("http")
            val ran = run(Runs.download(gate.proxyArg, server.url(), into))
            assertEquals(ran.stderrTail, 0, ran.exit)
            val info = printed(ran)
            val file = File(info.getString("filepath"))
            assertEquals(File(into, "audio.m4a"), file)
            assertArrayEquals(Runs.clip, file.readBytes())
            // The gate's credentials were sent: a request without them is a 407, logged nowhere; this one went through.
            val use = gate.log()["127.0.0.1"]
            assertNotNull(gate.log().toString(), use)
            assertTrue(use.toString(), use!!.connects >= 1 && use.bytesDown >= Runs.clip.size && use.refused == 0)
            assertFalse(gate.refusedAny())
            assertTrue(server.paths.toString(), "/clip.m4a" in server.paths)
            Runs.said("plain GET: ${server.paths.size} requests, the gate's log $use, after_move ${info.keys().asSequence().toList()}")
        }
    }

    @Test
    fun theClipOverHttpsThroughTheGatesConnect() {
        LoopbackServer(Runs.clip, tls = Runs.certificate()).use { server ->
            val into = Runs.into("https")
            // The loopback server's certificate is the test's own, self-signed: unchecked for this target alone.
            val ran = run(Runs.download(gate.proxyArg, server.url("https"), into, listOf("--no-check-certificates")))
            assertEquals(ran.stderrTail, 0, ran.exit)
            assertArrayEquals(Runs.clip, File(printed(ran).getString("filepath")).readBytes())
            val use = gate.log()["127.0.0.1"]
            assertNotNull(gate.log().toString(), use)
            assertTrue(use.toString(), use!!.connects >= 1 && use.bytesDown >= Runs.clip.size && use.refused == 0)
            Runs.said("CONNECT: ${server.paths.size} requests, the gate's log $use")
        }
    }

    private fun refused(argv: List<String>): String = try {
        run(argv)
        fail("not refused")
        ""
    } catch (e: Refused) {
        assertFalse(e.words, gate.proxyArg in e.words)
        e.words
    }

    @Test
    fun anArgvWithNoProxyOrAnotherIsRefused() {
        refused(listOf("--ignore-config", "--version"))
        refused(Runs.version("http://10.0.2.2:3128"))
        refused(Runs.version("http://someone:else@10.0.2.2:3128"))
        // A gate-shaped address that is no open gate of the app's: refused by the client before it binds anything.
        val closed = gates.open().also { it.close() }
        assertEquals(YtDlpClient.NOT_OUR_GATE, refused(Runs.version(closed.proxyArg)))
        val user = gate.proxyArg.substringAfter("://").substringBefore(':')
        assertEquals(YtDlpClient.NOT_OUR_GATE, refused(Runs.version(gate.proxyArg.replace(user, "0".repeat(user.length)))))
    }

    /** In GateService's own process (this one) the registry is this one's: a gate-shaped address that isn't open
     * here is refused at once, with nothing bound or asked, even while the main looper (which would deliver a bind)
     * is busy. */
    @Test
    fun aGateNotOpenHereIsRefusedAtOnceInTheGatesOwnProcess() {
        val closed = gates.open().also { it.close() }
        val release = java.util.concurrent.CountDownLatch(1)
        val busy = java.util.concurrent.CountDownLatch(1)
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            busy.countDown()
            release.await(20, java.util.concurrent.TimeUnit.SECONDS)
        }
        try {
            assertTrue(busy.await(10, java.util.concurrent.TimeUnit.SECONDS))
            val t0 = SystemClock.elapsedRealtime()
            assertEquals(YtDlpClient.NOT_OUR_GATE, refused(Runs.version(closed.proxyArg)))
            val took = SystemClock.elapsedRealtime() - t0
            Runs.said("a gate not open here refused in $took ms, the main looper busy")
            assertTrue("refused in $took ms", took < 2_000)
        } finally {
            release.countDown()
        }
    }

    @Test
    fun aSearchUnderLoopbackIsRefused() {
        val why = refused(Runs.search(gate.proxyArg))
        assertTrue(why, "loopback" in why)
        assertTrue(gate.log().toString(), gate.log().isEmpty())
    }

    /** A request whose mode isn't exactly LOOPBACK or NETWORK, none included, is refused before Python starts, and
     * its process ends. */
    @Test
    fun aRequestOfNoModeOrAnotherIsRefused() {
        for (mode in listOf(null, "", "loopback", "network", "OBSERVE")) {
            RawService().use { raw ->
                raw.send(7) {
                    putStringArray(YtDlpService.Wire.ARGV, Runs.version(gate.proxyArg).toTypedArray())
                    if (mode != null) putString(YtDlpService.Wire.NETWORK, mode)
                }
                val refused = raw.next(YtDlpService.Wire.REFUSED)
                assertNotNull("$mode: not refused", refused)
                assertEquals(7L, refused!!.getLong(YtDlpService.Wire.RUN_ID))
                assertEquals(YtDlpService.BAD_MODE, refused.getString(YtDlpService.Wire.WORDS))
                assertEquals(null, raw.next(YtDlpService.Wire.READY, 1))
            }
            assertEquals(emptyMap<Int, String>(), Runs.settle(10_000))
        }
    }

    /** One request a process: a second on the same binding is refused, and the process ends, the first with it. */
    @Test
    fun aSecondRequestInOneProcessIsRefusedAndTheProcessEnds() {
        RawService().use { raw ->
            raw.send(1) {
                putStringArray(YtDlpService.Wire.ARGV, Runs.version(gate.proxyArg).toTypedArray())
                putString(YtDlpService.Wire.NETWORK, "LOOPBACK")
                putLong(YtDlpService.Wire.DELAY_STARTED, 3_000)
            }
            raw.send(2) {
                putStringArray(YtDlpService.Wire.ARGV, Runs.version(gate.proxyArg).toTypedArray())
                putString(YtDlpService.Wire.NETWORK, "LOOPBACK")
            }
            val refused = raw.next(YtDlpService.Wire.REFUSED)
            assertEquals(2L, refused?.getLong(YtDlpService.Wire.RUN_ID))
            assertEquals(YtDlpService.ONE_RUN, refused?.getString(YtDlpService.Wire.WORDS))
            assertEquals(emptyMap<Int, String>(), Runs.settle(10_000))
            assertEquals(null, raw.next(YtDlpService.Wire.DONE, 1))
        }
    }

    /** A request let go of before it began runs nothing: the service asks whether it is still bound before Python,
     * the check and the run, and ends; or, unbound before its handler read the request, it ends with no answer. */
    @Test
    fun aRequestLetGoOfRunsNothing() {
        Env.err(context).delete()
        RawService().use { raw ->
            raw.send(3) {
                putStringArray(YtDlpService.Wire.ARGV, Runs.version(gate.proxyArg).toTypedArray())
                putString(YtDlpService.Wire.NETWORK, "LOOPBACK")
                putLong(YtDlpService.Wire.DELAY_STARTED, 2_000)
            }
            raw.unbind()
            // Either order holds: the service took the request (STARTED, then it ends, still let go of) or it ended on
            // the unbind before its handler read it (no answer at all). What matters: no READY, no yt-dlp, no process.
            assertEquals(emptyMap<Int, String>(), Runs.settle(10_000))
            assertEquals(null, raw.next(YtDlpService.Wire.READY, 1))
        }
        assertFalse("yt-dlp ran", Env.err(context).exists())
    }

    /** yt-dlp's `-v` prints its proxy map, the gate's secret in it: the client redacts it from every line, the tail
     * and the stdout. */
    @Test
    fun verboseOutputIsRedacted() {
        LoopbackServer(Runs.clip).use { server ->
            val ran = run(Runs.download(gate.proxyArg, server.url(), Runs.into("verbose"), listOf("-v")))
            assertEquals(ran.stderrTail, 0, ran.exit)
            val map = lines.firstOrNull { it.startsWith("[debug] Proxy map:") }
            assertNotNull(lines.joinToString("\n"), map)
            assertTrue(map, YtDlpClient.PROXY_SAID in map!!)
            assertNoSecret(ran)
        }
    }

    /** yt-dlp's parser takes a unique prefix of an option: `--prox` is `--proxy`. The client finds the gate's address by
     * its shape in what it is given and in what yt-dlp writes, whatever spelled it. */
    @Test
    fun aProxySpelledByAPrefixIsRedactedToo() {
        LoopbackServer(Runs.clip).use { server ->
            val argv = Runs.download(gate.proxyArg, server.url(), Runs.into("prefix"), listOf("-v"))
                .map { if (it == "--proxy") "--prox" else it }
            assertTrue("--prox" in argv)
            val ran = run(argv)
            assertEquals(ran.stderrTail, 0, ran.exit)
            val map = lines.firstOrNull { it.startsWith("[debug] Proxy map:") }
            assertNotNull(lines.joinToString("\n"), map)
            assertTrue(map, YtDlpClient.PROXY_SAID in map!!)
            assertNoSecret(ran)
        }
    }

    /** The run's folders, sent with the request, are folders of the app's own storage named by their canonical
     * paths, and the argv names those alone. */
    @Test
    fun aRunsFoldersAreItsOwnInTheAppsStorage() {
        LoopbackServer(Runs.clip).use { server ->
            val into = Runs.into("own")
            val argv = Runs.download(gate.proxyArg, server.url(), into)
            val cache = Runs.folders(argv).cache!!
            for (folders in listOf(RunFolders(File("/data/local/tmp"), into), RunFolders(cache, File("/sdcard")))) {
                val e = assertThrows(Refused::class.java) { client.run(argv, 60.0, { _, _ -> }, {}, folders) }
                assertEquals(YtDlpService.BAD_FOLDER, e.words)
            }
            val link = File(context.cacheDir, "youtube-test-link").apply { delete() }
            android.system.Os.symlink(into.path, link.path)
            try {
                val e = assertThrows(Refused::class.java) {
                    client.run(argv, 60.0, { _, _ -> }, {}, RunFolders(cache, link))
                }
                assertEquals(YtDlpService.BAD_FOLDER, e.words)
            } finally {
                link.delete()
            }
            // Folders of the app's own, but not those the argv names: the glue's refusal.
            val other = Runs.into("other")
            val e = assertThrows(Refused::class.java) { client.run(argv, 60.0, { _, _ -> }, {}, RunFolders(cache, other)) }
            assertTrue(e.words, "folders" in e.words)
            assertTrue("a refused run wrote nothing", other.listFiles().isNullOrEmpty())
        }
    }

    private val secret get() = gate.proxyArg.removePrefix("http://").substringBefore('@')

    private fun assertNoSecret(ran: Ran?) {
        for (part in listOf(gate.proxyArg, secret.substringBefore(':'), secret.substringAfter(':'))) {
            assertFalse("the gate's secret in a line", lines.any { part in it })
            if (ran != null) assertFalse("the gate's secret in Ran", part in ran.stderrTail || part in ran.stdout)
        }
    }

    /** The gate's secret crosses the binder in the argv and is written to no log, of either process: after a
     * download, a refusal, a run that fails, and a verbose run. */
    @Test
    fun theSecretIsInNoLog() {
        LoopbackServer(Runs.clip).use { server ->
            val ran = run(Runs.download(gate.proxyArg, server.url(), Runs.into("secret")))
            assertEquals(ran.stderrTail, 0, ran.exit)
            assertNoSecret(ran)
            refused(Runs.search(gate.proxyArg))
            val missing = run(Runs.download(gate.proxyArg, server.url().replace("clip.m4a", "none.m4a"),
                                            Runs.into("missing")))
            assertTrue(missing.stderrTail, missing.exit != 0)
            assertNoSecret(missing)
            val verbose = run(Runs.download(gate.proxyArg, server.url(), Runs.into("secret-v"), listOf("-v")))
            assertNoSecret(verbose)
        }
        val marker = "caracole-ytdlp-test-marker-${SystemClock.elapsedRealtime()}"
        Runs.said(marker)
        val log = Runs.logcat()
        assertTrue("logcat read nothing of this process", marker in log)
        assertTrue("logcat read nothing of :youtube", Regex("""/caracole-ytdlp\s*\(""").containsMatchIn(log))
        assertTrue("logcat read no refusal", "refused a run" in log)
        for (part in listOf(secret, secret.substringBefore(':'), secret.substringAfter(':'))) {
            assertFalse("the gate's secret is in logcat", part in log)
        }
    }
}
