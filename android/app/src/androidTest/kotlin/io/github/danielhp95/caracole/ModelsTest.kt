package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.models.From
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.ModelsSource
import io.github.danielhp95.caracole.core.models.Pin
import io.github.danielhp95.caracole.core.models.Pins
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.lookups.ModelsRunner
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread
import kotlin.random.Random

/**
 * The chord models' job in the app, on the device:
 *
 *     android/scripts/device-test.sh ModelsTest
 *
 * GitHub is this test's own server on the device's loopback ([GitHub]: its API's release `models` by its tag, the
 * asset's bytes at its API address, BTC's blob at its git address, as ModelsSource asks them), the pins a test's own
 * (three files of a few hundred KB of the real pins' shape, under a contract of their own: the real ones need the
 * real 42 MB file), the runner made over the phone's own parts and run on its queue, as the app's Settings queues
 * `phone.models`: the job installs them into `stateDir/models/c99/`, records kv models:installed and says the kind's
 * line in the Requests tab; a second run asks nothing; Remove takes them, and their record, away.
 */
@RunWith(AndroidJUnit4::class)
class ModelsTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val github = GitHub()

    @After fun close() = github.close()

    private val graph = Random(1).nextBytes(3_000)
    private val weights = Random(2).nextBytes(300_000)
    private val beats = Random(3).nextBytes(500_000)
    private val blob = "11c6edbaaaee33737aa7a41dcb9044191630326f"

    private fun pin(name: String, bytes: ByteArray, from: From) = Pin(name, bytes.size.toLong(), sha256(bytes), from)

    private val pins = Pins(99, "models", listOf(
        pin("btc-graph.onnx", graph, From.App),
        pin("btc_model_large_voca.pt", weights,
            From.Blob("jayg996/BTC-ISMIR19", "2682317be668032e6e4b269ded36adaa2ad57df0", "btc_model_large_voca.pt",
                      blob)),
        pin("beat_this-final0-fp16.onnx", beats, From.Release("beat_this-final0-fp16.onnx")),
    ))

    @Test fun theJobInstallsThemFromGitHubASecondAsksNothingAndRemoveTakesThemAway() {
        val phone = Caracole.phone(context)
        // The debug build carries the real pins (its :ml's models.json): the phone's own job is offered.
        assertNotNull(phone.models.folder())
        github.publish()
        val source = ModelsSource(base = github.base, redirects = emptySet(), pins = { pins },
                                  app = { name -> if (name == "btc-graph.onnx") graph.inputStream() else null })
        val runner = ModelsRunner(phone.parts, source)
        val folder = File(phone.parts.stateDir, "models/c99")
        assertEquals(folder, runner.folder())
        assertEquals("The chord models aren't on the phone.", runner.ready())

        val job = run(phone, runner)
        assertEquals(Job.DONE, job.state)
        assertEquals(Line("ready", "Chord models ready · 0.8 MB"), JobViews.line(job))
        assertEquals(listOf("/repos/Danielhp95/caracole/releases/tags/models",
                            "/repos/Danielhp95/caracole/releases/assets/9",
                            "/repos/jayg996/BTC-ISMIR19/git/blobs/$blob"), github.asked)
        assertNull(runner.ready())
        assertNull(ModelFiles.verify(folder, pins))
        assertArrayEquals(beats, File(folder, "beat_this-final0-fp16.onnx").readBytes())
        val record = kv(ModelsRunner.INSTALLED)!!
        assertTrue(record, record.startsWith("""{"contract": 99, "files": ["btc-graph.onnx", "btc_model_large_voca.pt", """ +
                                                 """"beat_this-final0-fp16.onnx"], "bytes": 803000, "when": """))

        github.asked.clear()
        val again = run(phone, runner)
        assertEquals(Line("ready", "Chord models ready · 0.8 MB"), JobViews.line(again))
        assertEquals(listOf<String>(), github.asked)

        assertNull(runner.remove())
        assertFalse(File(phone.parts.stateDir, ModelFiles.FOLDER).exists())
        assertNull(kv(ModelsRunner.INSTALLED))
        assertEquals("The chord models aren't on the phone.", runner.ready())
    }

    private fun kv(key: String): String? = Caracole.phone(context).parts.database.read { it.kvGet(key) }

    private fun run(phone: io.github.danielhp95.caracole.server.Phone, runner: ModelsRunner): Job {
        val job = phone.queue.submit(runner.spec()).first
        Pages.waitUntil("the models' job over", 60_000) {
            phone.queue.job(job.id)?.state.let { it == Job.DONE || it == Job.FAILED }
        }
        return phone.queue.job(job.id)!!.also { assertEquals(it.stages.joinToString { s -> s.detail }, Job.DONE, it.state) }
    }

    /**
     * GitHub's API on the device's loopback, as ModelsSource asks it: the release `models` listing beat_this's asset,
     * the asset's bytes at its API address (no hop: a direct answer), BTC's blob at its git address. Plain HTTP/1.1,
     * one request a connection; [asked] each request's path.
     */
    private inner class GitHub : AutoCloseable {
        private val socket = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        val base: URI = URI("http://127.0.0.1:${socket.localPort}")
        val asked = CopyOnWriteArrayList<String>()
        private val routes = ConcurrentHashMap<String, ByteArray>()

        init {
            thread(isDaemon = true, name = "test-github") {
                while (!socket.isClosed) {
                    val client = try {
                        socket.accept()
                    } catch (e: java.io.IOException) {
                        break
                    }
                    thread(isDaemon = true) { answer(client) }
                }
            }
        }

        fun publish() {
            val asset = "/repos/Danielhp95/caracole/releases/assets/9"
            routes[asset] = beats
            routes["/repos/jayg996/BTC-ISMIR19/git/blobs/$blob"] = weights
            routes["/repos/Danielhp95/caracole/releases/tags/models"] =
                ("""{"tag_name": "models", "assets": [{"name": "beat_this-final0-fp16.onnx", "url": "$base$asset", """ +
                    """"size": ${beats.size}, "digest": "sha256:${sha256(beats)}", "state": "uploaded"}]}""").toByteArray()
        }

        private fun answer(client: Socket) = client.use {
            val input = client.getInputStream()
            val head = StringBuilder()
            while (!head.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) return
                head.append(b.toChar())
            }
            val path = head.lineSequence().first().split(" ").getOrElse(1) { "" }.substringBefore('?')
            asked += path
            val body = routes[path]
            val status = if (body == null) "404 Not Found" else "200 OK"
            val bytes = body ?: """{"message": "Not Found"}""".toByteArray()
            val out = client.getOutputStream()
            out.write(("HTTP/1.1 $status\r\nContent-Length: ${bytes.size}\r\nContent-Type: application/octet-stream\r\n" +
                "Connection: close\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
            out.write(bytes)
            out.flush()
        }

        override fun close() = socket.close()
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
