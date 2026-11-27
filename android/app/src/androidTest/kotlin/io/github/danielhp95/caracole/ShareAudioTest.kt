package io.github.danielhp95.caracole

import android.content.Intent
import android.net.Uri
import android.webkit.WebView
import androidx.core.content.FileProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.lookups.InboxShare
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * An audio file shared to caracole (the chords-on-the-phone design's §8.2), in the app on the emulator:
 *
 *     android/scripts/device-test.sh --models ShareAudioTest
 *
 * A share, as Android's share sheet sends one to ShareActivity (SEND of an audio stream behind a content URI): the
 * file staged as an upload, read once, and the library screen opened at its page, `/share/audio?upload=ID`, its guess
 * in Artist and Title; Make sheet queues `caracole audio --upload=ID` and lands on the Journal; Cancel drops the file
 * and takes the screen back behind the app that shared; two audio files shared together are each answered "Share one
 * audio file at a time.", a PDF beside them still filed by the inbox; with no chord models, the page says why, naming
 * Settings, and nothing is staged. Each test sets the models' state it needs: installed from the files device-test.sh
 * pushed (`-e models`, ChordsEndToEndTest's way; skipped without), or removed.
 */
@RunWith(AndroidJUnit4::class)
class ShareAudioTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val pushed = InstrumentationRegistry.getArguments().getString("models")?.let(::File)
    private val phone: Phone get() = Caracole.phone(context)

    @After fun leave() {
        PhoneChords.anyPhoneHearsForTests = false
        instrumentation.runOnMainSync { (at(Stage.RESUMED) ?: at(Stage.STOPPED) ?: at(Stage.PAUSED))?.finish() }
        waitUntil("the library screen gone") { listOf(Stage.RESUMED, Stage.PAUSED, Stage.STOPPED).all { at(it) == null } }
    }

    /** The phone with the chord models device-test.sh pushed installed by its own job. */
    private fun installed() {
        Assume.assumeTrue("no chord models pushed: device-test.sh --models", pushed != null)
        val pins = ModelFiles.read()
        if (phone.models.ready() != null) {
            val kept = File(File(phone.parts.stateDir, ModelFiles.FOLDER), ".c${pins.contract}${ModelFiles.KEPT}")
            kept.mkdirs()
            for (pin in pins.files) File(pushed, pin.name).copyTo(File(kept, pin.name), overwrite = true)
            val job = phone.queue.submit(phone.models.spec(meteredOk = true)).first
            val done = runBlocking { withTimeout(300_000) { phone.queue.await(job.id) } }
            assertEquals(done.stages.joinToString { it.detail }, Job.DONE, done.state)
        }
        PhoneChords.anyPhoneHearsForTests = true
        assertNull(phone.audioProblem())
    }

    private fun staged(): List<String> = File(phone.parts.stateDir, "audio").list().orEmpty()
        .filter { it.startsWith(".upload-") && !it.endsWith(".json") && !it.endsWith(".kept") }

    /** [name] with [data] behind a content URI of the app's FileProvider, as a music app or a file manager shares it. */
    private fun uri(name: String, data: ByteArray): Uri {
        val file = File(File(context.cacheDir, "handoff/share-audio-test"), name).apply {
            parentFile!!.mkdirs()
            writeBytes(data)
        }
        return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    }

    private fun clip(): ByteArray = instrumentation.context.assets.open("fixtures/autochords/hearing.mp3").use { it.readBytes() }

    private fun share(type: String, vararg uris: Uri) {
        ShareActivity.told = null
        ShareActivity.opened = null
        val intent = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris.toList()))
        }
        context.startActivity(intent.setClass(context, ShareActivity::class.java).setType(type)
                                  .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
    }

    private fun at(stage: Stage): MainActivity? {
        var found: MainActivity? = null
        val look = { found = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(stage)
            .filterIsInstance<MainActivity>().firstOrNull() }
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) look() else instrumentation.runOnMainSync(look)
        return found
    }

    private fun screen(): MainActivity = at(Stage.RESUMED) ?: at(Stage.PAUSED) ?: at(Stage.STOPPED)
        ?: throw AssertionError("no library screen")

    private fun evaluate(script: String): Any? {
        var raw: String? = null
        val latch = CountDownLatch(1)
        instrumentation.runOnMainSync {
            screen().findViewById<WebView>(R.id.web).evaluateJavascript(script) { raw = it; latch.countDown() }
        }
        check(latch.await(10, TimeUnit.SECONDS)) { "no answer from the page to: $script" }
        val value = (JSONTokener("[${raw ?: "null"}]").nextValue() as JSONArray).get(0)
        return if (value == JSONObject.NULL) null else value
    }

    private fun loaded(): String? = runCatching {
        evaluate("document.readyState === 'complete' ? location.href : null") as String?
    }.getOrNull()

    private fun shownAt(what: String, part: String) = waitUntil(what, 60_000) { loaded()?.contains(part) == true }

    private fun text(selector: String): String =
        evaluate("(document.querySelector('$selector') || {}).textContent || ''") as String

    private fun value(selector: String): String = evaluate("document.querySelector('$selector').value") as String

    @Test fun anMp3SharedGivesThePageWithItsGuessAndMakeSheetQueuesTheJob() {
        installed()
        share("audio/mpeg", uri("Calla Lake - River Road.mp3", clip()))
        shownAt("the audio file's page", "/share/audio?upload=")
        val upload = loaded()!!.substringAfter("upload=")
        assertEquals("Calla Lake - River Road.mp3 · MP3 · 0:20", text(".lede"))
        assertEquals("Calla Lake", value("form[action=\"/audio\"] input[name=artist]"))
        assertEquals("River Road", value("form[action=\"/audio\"] input[name=title]"))
        assertEquals(listOf(".upload-$upload.mp3"), staged())

        val before = phone.queue.snapshot().map { it.id }.toSet()
        evaluate("document.querySelector('form[action=\"/audio\"]').submit(); true")
        shownAt("the Journal", "#tab=requests")
        val job = phone.queue.snapshot().first { it.id !in before }
        assertEquals(listOf("audio", "--progress", "--upload=$upload", "--song=Calla Lake - River Road"),
                     job.steps.single().args)
        val done = runBlocking { withTimeout(300_000) { phone.queue.await(job.id) } }
        assertEquals(done.stages.joinToString { "${it.name} ${it.state} ${it.detail}" }, Job.DONE, done.state)
    }

    @Test fun cancelDropsTheFileAndLeavesTheShare() {
        installed()
        share("*/*", uri("Calla Lake - Cancelled.mp3", clip()))
        shownAt("the audio file's page", "/share/audio?upload=")
        assertEquals(1, staged().size)
        evaluate("document.querySelector('form[action=\"/share/audio/cancel\"]').submit(); true")
        waitUntil("the file dropped") { staged().isEmpty() }
        // The screen went behind the app that shared (the launcher): stopped, never finished.
        waitUntil("the screen behind") { at(Stage.STOPPED) != null }
    }

    @Test fun twoAudioFilesSharedTogetherAreAnsweredOneAtATimeAndAPdfStillGoesToTheInbox() {
        share("*/*", uri("A - One.mp3", clip()), uri("A - Two.flac", clip()), uri("Share Audio - A Score.pdf",
                                                                                     "%PDF-1.4 score".toByteArray()))
        val said = waitForToast()
        assertEquals(listOf(ShareActivity.ONE_AT_A_TIME, ShareActivity.ONE_AT_A_TIME,
                            "Waiting for its song: Share Audio - A Score.pdf"), said.lines())
        assertEquals(emptyList<String>(), staged())
        assertNull(ShareActivity.opened)
        assertTrue("Share Audio - A Score.pdf" in InboxShare.folder(phone.parts).waiting())
        InboxShare.folder(phone.parts).drop("Share Audio - A Score.pdf")
    }

    @Test fun withNoChordModelsThePageSaysWhyAndNothingIsStaged() {
        phone.models.remove()
        val why = phone.audioProblem()
        Assume.assumeTrue("a phone that makes sheets with no models", why != null)
        share("audio/mpeg", uri("Calla Lake - River Road.mp3", clip()))
        shownAt("the audio file's page", "/share/audio?name=")
        assertEquals("No sheets from audio files here: $why.", text(".message"))
        assertEquals(0, (evaluate("document.querySelectorAll('form[action=\"/audio\"]').length") as Number).toInt())
        assertEquals(emptyList<String>(), staged())
    }

    private fun waitForToast(): String {
        val until = System.nanoTime() + 60_000_000_000L
        while (System.nanoTime() < until) {
            ShareActivity.told?.let { return it }
            Thread.sleep(50)
        }
        throw AssertionError("no toast in 60 s")
    }
}
