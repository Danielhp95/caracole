package io.github.danielhp95.caracole

import android.os.Process
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.youtube.GateRefused
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.youtube.Env
import io.github.danielhp95.caracole.youtube.ProcessYtDlp
import io.github.danielhp95.caracole.youtube.YtDlpClient
import io.github.danielhp95.caracole.youtube.YtDlpEngine
import java.io.File
import java.io.RandomAccessFile
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Collections
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicInteger
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The app's yt-dlp (`PhoneDeps.youtube`, the debug build's :youtube) driven by core.youtube's real runner, [YtDlp],
 * through [ProcessYtDlp], one gate a run opened in this, the main process, under the test runner's loopback: a
 * download of the clip `android/scripts/device-test.sh --youtube` serves on the host (`-e clip`, reached as
 * `http://10.0.2.2:PORT/clip.m4a`), its argv youtube.json's download template filled, the gate's log naming 10.0.2.2
 * alone, one `events` row with the computer's fields; a run whose yt-dlp asks a host the gate refuses, the gate's
 * refusal in the data's words and never a block; a run while another holds the app's turn, nothing started; a run
 * interrupted or closed mid-download, cut off, counted, its process gone; and after each, nothing left: no `:youtube`
 * or qjs process, no gate or client thread, no gate open, nothing in the run's folders but the runner's own, and the
 * gate's secret in no line, event, kv record, exception or log line.
 *
 * The runner builds a download's target from a video's id (YouTube's watch address), which the glue refuses under
 * the tests' loopback: [Swapping] hands ProcessYtDlp the very argv the runner built, its target alone swapped for a
 * loopback one; what the runner built is compared whole.
 */
@RunWith(AndroidJUnit4::class)
class YtDlpEngineTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val data = YouTubeData.read()
    private val phone get() = Caracole.phone(context)
    private val database get() = phone.parts.database
    private val engine: YouTubeEngine get() = checkNotNull(phone.youtube) { "a debug build carries its yt-dlp" }
    private val gates = Collections.synchronizedList(mutableListOf<YtDlpGate>())
    private val lines = Collections.synchronizedList(mutableListOf<String>())
    private val thrown = Collections.synchronizedList(mutableListOf<Throwable>())

    private fun clip(): String = InstrumentationRegistry.getArguments().getString("clip")
        ?: fail("no clip: run it through android/scripts/device-test.sh --youtube") as Nothing

    @Before
    fun clean() {
        database.writeBlocking { db ->
            db.execute("DELETE FROM events WHERE provider = 'youtube'")
            for (key in listOf("http:last_request:youtube", "provider:youtube")) db.execute("DELETE FROM kv WHERE key = ?", key)
        }
        engine.cacheDir.deleteRecursively()
    }

    @After
    fun nothingLeft() {
        waitFor(15_000, "no :youtube or qjs process") { leftover().isEmpty() }
        val threads = Thread.getAllStackTraces().keys.filter { it.isAlive }.map { it.name }
            .filter { it.startsWith("caracole-gate-") || it.startsWith("caracole-ytdlp-client") }
        assertEquals("threads left", emptyList<String>(), threads)
        for (gate in gates) assertFalse("a gate left open", HostGate.isOpen(gate.proxyArg))
        assertFalse("the run's stdout or stderr left", Env.out(context).exists() || Env.err(context).exists())
        assertTrue("the run's TMPDIR left", Env.tmp(context).listFiles().orEmpty().isEmpty())
        val kept = engine.cacheDir.listFiles().orEmpty().map { it.name }.toSet()
        assertTrue("the runner's folder holds $kept", kept.all { it == CACHE || it.startsWith(INTO) })
        noSecret()
    }

    @Test
    fun theEngineIsTheDebugBuildsAndReady() {
        assertTrue(engine is YtDlpEngine)
        assertNull(engine.ready())
        assertTrue(engine.qjs.canExecute())
        assertEquals(File(Caracole.cacheDir(context), "youtube"), engine.cacheDir)
        assertTrue(engine.process() is ProcessYtDlp)
    }

    @Test
    fun aDownloadTakesTheClipByTheDatasArgvThroughAGateThatNames10002Alone() {
        val into = into("download")
        val swapping = Swapping(engine.process(), clip())
        val got = withRunner(swapping, RUN) { it.download(ID, into) }
        // What the runner built is youtube.json's download template, filled; ProcessYtDlp ran it, its target swapped.
        val gate = gates.single()
        val expected = data.argv("download", data.watchUrl(ID), File(engine.cacheDir, CACHE).path, engine.qjs.path,
                                 gate.proxyArg, into.path)
        assertEquals(listOf(expected), swapping.built)
        assertTrue(expected.none { '<' in it && '>' in it && it.substringAfter('<').substringBefore('>') in data.placeholders })
        assertEquals(setOf("10.0.2.2"), gate.log().keys)
        assertTrue(gate.log()["10.0.2.2"]!!.connects > 0)
        assertEquals(File(into, "audio.m4a").canonicalFile, got.path.canonicalFile)
        assertTrue(got.path.length() > 0)
        assertEquals(ID, got.video.id)
        // One events row, the computer's fields; the pause's record.
        val rows = events()
        assertEquals(listOf(Row(RUN, "youtube", data.watchUrl(ID), null, "ok", null)), rows)
        assertTrue(read { it.kvGet("http:last_request:youtube") } != null)
        (swapping.inner as ProcessYtDlp).close()
    }

    @Test
    fun aRunAskingAHostTheGateRefusesIsTheGatesRefusalNeverABlock() {
        Redirecting("http://$REFUSED/clip.m4a").use { server ->
            val into = into("refused")
            val e = try {
                withRunner(Swapping(engine.process(), server.url()), RUN) { it.download(ID, into) }
                fail("not refused") as Nothing
            } catch (e: GateRefused) {
                thrown += e
                e
            }
            val words = YouTubeData.fillAll(data.text("refusal", data.gate), mapOf("host" to REFUSED))
            assertEquals(REFUSED, e.host)
            assertTrue(e.message, e.message!!.endsWith(": $words")) // ProviderError's "youtube: <url>: " before it
            val log = gates.single().log()
            assertTrue(log.toString(), (log[REFUSED]?.refused ?: 0) > 0)
            assertEquals(listOf(Row(RUN, "youtube", data.watchUrl(ID), null, "error", words)), events())
            val health = read { Health.state(it, "youtube") }
            assertEquals("no strike", 0, health.strikes.toInt())
            assertNull("no cooldown", health.cooldownUntil)
        }
    }

    @Test
    fun aRunWhileAnotherHoldsTheAppsTurnStartsNothing() {
        RandomAccessFile(File(context.filesDir, YtDlpClient.LOCK), "rw").use { raf ->
            raf.channel.lock().use {
                var runner: YtDlp? = null
                val e = try {
                    withRunner(engine.process(), RUN, { runner = it }) { it.download(ID, into("turn")) }
                    fail("started") as Nothing
                } catch (e: ProviderError) {
                    thrown += e
                    e
                }
                assertTrue(e.message, e.message!!.endsWith(": ${YtDlpClient.ANOTHER_RUN}"))
                assertEquals(0, runner!!.requestsMade)
                assertEquals(emptyList<Row>(), events())
                assertEquals(emptyList<String>(), leftover())
            }
        }
    }

    @Test
    fun aRunInterruptedOrClosedMidDownloadIsCutOffCountedAndItsProcessGone() {
        Trickling().use { server ->
            // Interrupted: the thread's interrupt stops yt-dlp, the runner rethrows it, counted.
            val worker = Thread {
                try {
                    withRunner(Swapping(engine.process(), server.url()), RUN) { it.download(ID, into("interrupted")) }
                } catch (t: Throwable) {
                    thrown += t
                }
            }.apply { start() }
            waitFor(120_000, "the download under way") { server.downloading() }
            worker.interrupt()
            worker.join(60_000)
            assertFalse(worker.isAlive)
            assertTrue(thrown.toString(), thrown.single() is InterruptedException)
            waitFor(10_000, "its process gone") { leftover().isEmpty() }
            assertEquals(listOf("error"), events().map { it.decision })
        }
        thrown.clear()
        Trickling().use { server ->
            // Closed: ProcessYtDlp's close stops the run under way (a CancellationException), and starts none after.
            val process = engine.process() as ProcessYtDlp
            val worker = Thread {
                try {
                    withRunner(Swapping(process, server.url()), RUN2) { it.download(ID, into("closed")) }
                } catch (t: Throwable) {
                    thrown += t
                }
            }.apply { start() }
            waitFor(120_000, "the download under way") { server.downloading() }
            process.close()
            worker.join(60_000)
            assertTrue(thrown.toString(), thrown.single() is CancellationException)
            waitFor(10_000, "its process gone") { leftover().isEmpty() }
            assertEquals(listOf("error"), events().filter { it.run == RUN2 }.map { it.decision })
            try {
                process.run(listOf("--version"), 10.0, {}, {})
                fail("ran after close")
            } catch (_: YtDlpProcess.NotStarted) {
            }
        }
    }

    // -- helpers -------------------------------------------------------------------------------------------------------

    /** The runner over [process] in one write, its gates kept in [gates] (the runner closes each), its lines [lines]. */
    private fun <T> withRunner(process: YtDlpProcess, runId: String, made: (YtDlp) -> Unit = {}, body: (YtDlp) -> T): T =
        database.writeBlocking { db ->
            val runner = YtDlp(process, PhoneConfig.read(db).provider("youtube"), engine.cacheDir, engine.qjs.path,
                               { engine.gate().also { gates += it } }, db, Pacing.REAL, budget = 6, runId = runId,
                               onLine = { lines += it })
            made(runner)
            body(runner)
        }

    /** The argv the runner built, handed on with its last element, the target, swapped for [target]. */
    private class Swapping(val inner: YtDlpProcess, private val target: String) : YtDlpProcess {
        val built: MutableList<List<String>> = Collections.synchronizedList(mutableListOf())

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            built += argv
            return inner.run(argv.dropLast(1) + target, timeoutS, onLine, waiting)
        }
    }

    private fun into(name: String) = File(engine.cacheDir, "$INTO$name").apply { deleteRecursively(); mkdirs() }

    private data class Row(val run: String, val provider: String, val url: String?, val status: Long?,
                           val decision: String, val message: String?)

    private fun events(): List<Row> = read { db ->
        db.query("SELECT run, provider, url, status, decision, message FROM events WHERE provider = 'youtube' ORDER BY rowid") {
            Row(it.text(0)!!, it.text(1)!!, it.text(2), it.long(3), it.text(4)!!, it.text(5))
        }
    }

    private fun <T> read(block: (Db) -> T): T = database.read(block)

    /** The gate's address, its user and its secret, in none of the lines, events, kv records, exceptions or the log. */
    private fun noSecret() {
        val texts = mutableListOf<String>()
        texts += lines
        texts += thrown.map { it.toString() + (it.message ?: "") }
        texts += read { db ->
            db.query("SELECT COALESCE(url, '') || ' ' || COALESCE(message, '') FROM events") { it.text(0) ?: "" } +
                db.query("SELECT key || ' ' || COALESCE(value, '') FROM kv") { it.text(0) ?: "" }
        }
        texts += ProcessBuilder("logcat", "-d").redirectErrorStream(true).start().let {
            val text = it.inputStream.readBytes().decodeToString()
            it.waitFor()
            text
        }
        for (gate in gates) {
            val credentials = gate.proxyArg.substringAfter("://").substringBefore('@')
            for (part in listOf(gate.proxyArg, credentials.substringBefore(':'), credentials.substringAfter(':'))) {
                assertFalse("the gate's secret is said", texts.any { part in it })
            }
        }
    }

    /** The `:youtube` and qjs processes of the app's uid now, by their command lines. */
    private fun leftover(): List<String> {
        val found = mutableListOf<String>()
        for (dir in File("/proc").listFiles().orEmpty()) {
            val pid = dir.name.toIntOrNull() ?: continue
            if (pid == Process.myPid()) continue
            try {
                val uid = File(dir, "status").readLines().firstOrNull { it.startsWith("Uid:") }
                    ?.split(Regex("\\s+"))?.get(1)?.toIntOrNull()
                if (uid != Process.myUid()) continue
                val line = File(dir, "cmdline").readBytes().decodeToString().replace('\u0000', ' ').trim()
                if (line.endsWith(YtDlpClient.PROCESS) || "libqjs.so" in line) found += line
            } catch (_: Exception) {
                continue
            }
        }
        return found
    }

    private fun waitFor(ms: Long, what: String, done: () -> Boolean) {
        val until = System.currentTimeMillis() + ms
        while (!done()) {
            if (System.currentTimeMillis() > until) fail("$what didn't come in ${ms / 1000} s")
            Thread.sleep(100)
        }
    }

    /** A server on 127.0.0.1 of this process, each connection one request answered by [answer] (then closed). */
    private abstract class Served : AutoCloseable {
        private val server = ServerSocket(0, 10, InetAddress.getByName("127.0.0.1"))
        val asked = AtomicInteger()

        init {
            Thread({
                while (!server.isClosed) {
                    val socket = try {
                        server.accept()
                    } catch (_: Exception) {
                        break
                    }
                    Thread({ serve(socket) }, "engine-test-serve").apply { isDaemon = true; start() }
                }
            }, "engine-test-accept").apply { isDaemon = true; start() }
        }

        fun url(): String = "http://127.0.0.1:${server.localPort}/clip.m4a"

        private fun serve(socket: Socket) = try {
            socket.use {
                val head = StringBuilder()
                val input = it.getInputStream()
                while (!head.endsWith("\r\n\r\n")) {
                    val b = input.read()
                    if (b < 0) return
                    head.append(b.toChar())
                }
                asked.incrementAndGet()
                answer(it)
            }
        } catch (_: Exception) {
        }

        abstract fun answer(socket: Socket)

        override fun close() = server.close()
    }

    /** Every request answered with a redirect to [to]. */
    private class Redirecting(private val to: String) : Served() {
        override fun answer(socket: Socket) {
            socket.getOutputStream().write(("HTTP/1.1 302 Found\r\nLocation: $to\r\nContent-Length: 0\r\n" +
                "Connection: close\r\n\r\n").toByteArray())
        }
    }

    /** Every request answered as an m4a of a megabyte that comes a byte every 100 ms, until the client goes. */
    private class Trickling : Served() {
        private val bodies = AtomicInteger()

        /** The download's own request (yt-dlp's second, after its extractor's look) has had a byte of its body. */
        fun downloading(): Boolean = bodies.get() >= 2

        override fun answer(socket: Socket) {
            val out = socket.getOutputStream()
            out.write(("HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nContent-Length: 1000000\r\n" +
                "Connection: close\r\n\r\n").toByteArray())
            out.flush()
            var first = true
            while (true) {
                out.write(0)
                out.flush()
                if (first) bodies.incrementAndGet().also { first = false }
                Thread.sleep(100)
            }
        }
    }

    companion object {
        private const val ID = "aaaaaaaaaaa"
        private const val RUN = "youtube-sheet:engine-test"
        private const val RUN2 = "youtube-sheet:engine-test-2"
        private const val CACHE = "yt-dlp"
        private const val INTO = "into-"
        private const val REFUSED = "refused.example"
    }
}
