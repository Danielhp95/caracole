package io.github.danielhp95.caracole

import android.app.AlertDialog
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.models.From
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.Pins
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/**
 * Settings' "Chords from audio" row in the app, on the emulator (the chords-on-the-phone design's §8.3):
 *
 *     android/scripts/device-test.sh --models SettingsChordsTest
 *
 * GitHub is this test's own server on the device's loopback, at CaracoleTestRunner.MODELS_PORT, where the app's
 * `phone.models` asks (Caracole.modelsForTests): its release lists beat_this's file and answers it, and BTC's blob,
 * each the file device-test.sh pushed (`-e models`; skipped without). Settings says "Not downloaded · 56 MB";
 * Download asks §6's question, then queues the `models` job, its line followed to "Ready · 56 MB on the phone"; the
 * library page then shows the "+"; Remove asks first, then takes the models away, the row "Not downloaded" again and
 * the "+" gone. On a metered network, Download asks its second question, and Not now queues nothing.
 */
@RunWith(AndroidJUnit4::class)
class SettingsChordsTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val pushed = InstrumentationRegistry.getArguments().getString("models")?.let(::File)
    private val phone: Phone get() = Caracole.phone(context)
    private var github: GitHub? = null

    @Before fun noModels() {
        Assume.assumeTrue("no chord models pushed: device-test.sh --models", pushed != null)
        assertNull(phone.models.remove())
        Caracole.meteredForTests = false
        PhoneChords.anyPhoneHearsForTests = true  // the emulator's processor: chords as a phone's
        github = GitHub(ModelFiles.read(), pushed!!)
    }

    @After fun reset() {
        // A models job this test queued ended before the next one's Remove.
        waitUntil("the models' jobs over", 300_000) {
            phone.queue.snapshot().none { it.spec.kind == PhoneKinds.MODELS.kind && it.active }
        }
        github?.close()
        Caracole.meteredForTests = null
        PhoneChords.anyPhoneHearsForTests = false
    }

    private fun line(s: ActivityScenario<SettingsActivity>): String {
        var text = ""
        s.onActivity { text = it.findViewById<TextView>(R.id.chords_line).text.toString() }
        return text
    }

    private fun button(s: ActivityScenario<SettingsActivity>, id: Int): Button {
        var found: Button? = null
        s.onActivity { found = it.findViewById(id) }
        return found!!
    }

    private fun click(s: ActivityScenario<SettingsActivity>, id: Int) = s.onActivity { it.findViewById<Button>(id).performClick() }

    /** The row's question once open: its message, then [which] of its buttons pressed. */
    private fun answer(s: ActivityScenario<SettingsActivity>, which: Int): String {
        var dialog: AlertDialog? = null
        waitUntil("the row's question") { s.onActivity { dialog = it.chordsAsked }; dialog?.isShowing == true }
        var message = ""
        s.onActivity {
            message = dialog!!.findViewById<TextView>(android.R.id.message)?.text?.toString().orEmpty()
            dialog!!.getButton(which).performClick()
        }
        return message
    }

    private fun plus(): Boolean = ActivityScenario.launch(MainActivity::class.java).use { main ->
        waitUntil("the library page", 60_000) {
            Pages.evaluate(main, "document.readyState === 'complete' && !!document.getElementById('tab-library')") == true
        }
        Pages.evaluate(main, "document.getElementById('add-audio') !== null") == true
    }

    private val size get() = io.github.danielhp95.caracole.core.index.Sizes.size(phone.models.bytes()!!)

    @Test fun downloadFromGitHubThenThePlusThenRemoveTakesItAway() {
        assertTrue(!plus())
        ActivityScenario.launch(SettingsActivity::class.java).use { s ->
            waitUntil("the row's line") { line(s).isNotEmpty() }
            assertEquals("Not downloaded · $size", line(s))
            assertEquals("Download ($size)", button(s, R.id.chords_download).text.toString())
            // The question says what is left to fetch (the app's own graph none of it), the row the models whole.
            val left = io.github.danielhp95.caracole.core.index.Sizes.size(phone.models.toDownload()!!)
            click(s, R.id.chords_download)
            val asked = answer(s, AlertDialog.BUTTON_POSITIVE)
            assertEquals("$left, once: beat_this's (MIT) from caracole's GitHub release and BTC's from its authors' " +
                             "repository on GitHub. Chords are then worked out on the phone; nothing about your audio " +
                             "leaves it.", asked)
            waitUntil("the models installed", 300_000) { line(s) == "Ready · $size on the phone" }
            assertNull(phone.models.ready())
            assertTrue(github!!.asked.toString(), github!!.asked.any { it.contains("/git/blobs/") })
            assertEquals(android.view.View.VISIBLE, button(s, R.id.chords_remove).visibility)
        }
        assertTrue("the library page's +", plus())
        ActivityScenario.launch(SettingsActivity::class.java).use { s ->
            waitUntil("the row ready") { line(s) == "Ready · $size on the phone" }
            click(s, R.id.chords_remove)
            assertEquals("Sheets you made stay. Making another needs the download again.",
                         answer(s, AlertDialog.BUTTON_POSITIVE))
            waitUntil("the models removed") { line(s) == "Not downloaded · $size" }
            assertNotNull(phone.models.ready())
        }
        assertTrue("no + once removed", !plus())
    }

    @Test fun onAMeteredNetworkDownloadAsksAgainAndNotNowQueuesNothing() {
        Caracole.meteredForTests = true
        ActivityScenario.launch(SettingsActivity::class.java).use { s ->
            waitUntil("the row's line") { line(s).isNotEmpty() }
            assertEquals("Not downloaded · $size", line(s))
            val before = phone.queue.snapshot().count { it.spec.kind == PhoneKinds.MODELS.kind }
            click(s, R.id.chords_download)
            answer(s, AlertDialog.BUTTON_POSITIVE)
            val left = io.github.danielhp95.caracole.core.index.Sizes.size(phone.models.toDownload()!!)
            assertEquals("You're on a metered network. Download $left anyway?", answer(s, AlertDialog.BUTTON_NEGATIVE))
            Thread.sleep(500)
            assertEquals(before, phone.queue.snapshot().count { it.spec.kind == PhoneKinds.MODELS.kind })
            assertEquals("Not downloaded · $size", line(s))
        }
    }

    /**
     * GitHub's API on loopback at the runner's port, as ModelsSource asks it: the release by its tag listing the
     * release pin's asset, the asset's bytes at its API address, the blob pin's at its git address; each file the one
     * device-test.sh pushed, streamed. One request a connection; [asked] each path.
     */
    private class GitHub(pins: Pins, files: File) : AutoCloseable {
        private val socket = ServerSocket(CaracoleTestRunner.MODELS_PORT, 16, InetAddress.getByName("127.0.0.1"))
        private val base = "http://127.0.0.1:${socket.localPort}"
        val asked = CopyOnWriteArrayList<String>()
        private val routes = HashMap<String, Any>()

        init {
            for (pin in pins.files) when (val from = pin.from) {
                is From.Release -> {
                    val asset = "/repos/Danielhp95/caracole/releases/assets/7"
                    routes[asset] = File(files, pin.name)
                    routes["/repos/Danielhp95/caracole/releases/tags/${pins.release}"] =
                        ("""{"tag_name": "${pins.release}", "assets": [{"name": "${from.asset}", "url": "$base$asset", """ +
                            """"size": ${pin.bytes}, "digest": "sha256:${pin.sha256}", "state": "uploaded"}]}""")
                            .toByteArray()
                }
                is From.Blob -> routes["/repos/${from.repository}/git/blobs/${from.blob}"] = File(files, pin.name)
                From.App -> Unit
            }
            thread(isDaemon = true, name = "test-models-github") {
                while (!socket.isClosed) {
                    val client = try {
                        socket.accept()
                    } catch (e: IOException) {
                        break
                    }
                    thread(isDaemon = true) { answer(client) }
                }
            }
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
            val out = client.getOutputStream()
            when (val body = routes[path]) {
                is ByteArray -> {
                    out.write(head(200, body.size.toLong()))
                    out.write(body)
                }
                is File -> {
                    out.write(head(200, body.length()))
                    body.inputStream().use { it.copyTo(out, 1 shl 16) }
                }
                else -> {
                    val none = """{"message": "Not Found"}""".toByteArray()
                    out.write(head(404, none.size.toLong()))
                    out.write(none)
                }
            }
            out.flush()
        }

        private fun head(status: Int, length: Long) =
            ("HTTP/1.1 $status ${if (status == 200) "OK" else "Not Found"}\r\nContent-Length: $length\r\n" +
                "Content-Type: application/octet-stream\r\nConnection: close\r\n\r\n").toByteArray(Charsets.ISO_8859_1)

        override fun close() = socket.close()
    }
}
