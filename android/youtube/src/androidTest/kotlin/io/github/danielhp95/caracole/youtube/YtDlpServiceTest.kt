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
        val ran = client.run(argv, timeoutS, { _, line -> lines.add(line) }, {})
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
    }

    @Test
    fun aSearchUnderLoopbackIsRefused() {
        val argv = listOf("--ignore-config", "--proxy", gate.proxyArg, "--flat-playlist", "--dump-single-json", "--",
                          "ytsearch1:anything")
        val why = refused(argv)
        assertTrue(why, "loopback" in why)
        assertTrue(gate.log().toString(), gate.log().isEmpty())
    }

    /** The gate's secret crosses the binder in the argv and is written to no log, of either process. */
    @Test
    fun theSecretIsInNoLog() {
        LoopbackServer(Runs.clip).use { server ->
            val ran = run(Runs.download(gate.proxyArg, server.url(), Runs.into("secret")))
            assertEquals(ran.stderrTail, 0, ran.exit)
        }
        val marker = "caracole-ytdlp-test-marker-${SystemClock.elapsedRealtime()}"
        Runs.said(marker)
        // This app's uid reads its own processes' lines alone, the :youtube process's among them.
        val log = ProcessBuilder("logcat", "-d", "-v", "brief").redirectErrorStream(true).start().let {
            val text = it.inputStream.readBytes().decodeToString()
            it.waitFor()
            text
        }
        assertTrue("logcat read nothing of this process", marker in log)
        assertTrue("logcat read nothing of :youtube", Regex("""/caracole-ytdlp\s*\(""").containsMatchIn(log))
        val secret = gate.proxyArg.removePrefix("http://").substringBefore('@')
        assertFalse("the gate's user and secret are in logcat", secret in log)
        assertFalse("the gate's secret is in logcat", secret.substringAfter(':') in log)
        assertFalse("the gate's secret is in stderr", lines.any { secret.substringAfter(':') in it })
    }
}
