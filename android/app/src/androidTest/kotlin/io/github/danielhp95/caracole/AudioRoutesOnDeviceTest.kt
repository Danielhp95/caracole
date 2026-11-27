package io.github.danielhp95.caracole

import android.os.Bundle
import android.app.Instrumentation
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.routes.AudioRoutes
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Base64

/**
 * The audio routes in the debug app on the emulator, through its real server and its real examiner (PhoneExaminer:
 * `:autochords`' lengths, Android's tags):
 *
 *     android/scripts/device-test.sh --models AudioRoutesOnDeviceTest
 *
 * - the examiner reads every file of vectors/web/audio_routes.jsonl's `caracole.audio_store.examine` records (the
 *   committed fixtures, and tiny tagged files of every format) as the computer's store does: each length to the bit,
 *   each tag the computer read Android's too (MediaMetadataRetriever's) but a WAV's and an AIFF's, whose ID3 chunk
 *   Android doesn't read, the differences reported;
 * - with the chord models not installed, an upload is refused in the route's words with the phone's reason, its body
 *   never staged;
 * - with them installed (`-e models`, as ChordsEndToEndTest installs them; skipped without), the library page says
 *   `server.audio.ok`, a committed clip is uploaded over HTTP (its guess and length the store's), Make sheet queues
 *   `caracole audio --upload=ID` for it, and a drop of it is refused while that job waits.
 */
@RunWith(AndroidJUnit4::class)
class AudioRoutesOnDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val pushed = InstrumentationRegistry.getArguments().getString("models")?.let(::File)

    @After fun reset() {
        PhoneChords.anyPhoneHearsForTests = false
    }

    @Test fun theExaminerReadsEveryFileAsTheComputersStoreDoes() {
        val records = records("conformance/web/audio_routes.jsonl")
            .filter { it.optString("fn") == "caracole.audio_store.examine" }
        assertTrue("${records.size} records", records.size >= 20)
        val told = ArrayList<String>()
        for ((n, r) in records.withIndex()) {
            val name = r.optString("file").ifEmpty { "tagged ${r.getJSONObject("out").getString("format")}" }
            val bytes = if (r.has("file")) asset("fixtures/${r.getString("file")}")
                        else Base64.getDecoder().decode(r.getString("bytes"))
            val spool = File(context.cacheDir, ".upload-test-$n.part").apply { writeBytes(bytes) }
            try {
                val out = r.getJSONObject("out")
                val read = PhoneExaminer.examine(spool, out.getString("format"))
                assertEquals(name, out.getDouble("duration"), read.durationS, 0.0)
                val tags = out.getJSONObject("tags")
                for (key in listOf("artist", "title", "album")) {
                    val want = if (tags.isNull(key)) null else tags.getString(key)
                    val got = read.tags[key].orEmpty().firstOrNull { it.isNotBlank() }?.trim()
                    if (want != got) told += "$name: $key Android's ${got ?: "none"}, mutagen's ${want ?: "none"}"
                }
            } finally {
                spool.delete()
            }
        }
        report("tags as Android reads them, where they differ from mutagen's: ${told.ifEmpty { listOf("none") }}")
        // The tagged files' artist and title are what a guess is made of: Android reads them in every format but WAV
        // and AIFF, whose ID3 chunk (mutagen's) its MediaMetadataRetriever doesn't read: their guess comes from the
        // file's name (the dialog's fields are editable).
        assertTrue(told.joinToString("\n"), told.all { it.startsWith("tagged WAV:") || it.startsWith("tagged AIFF:") })
    }

    @Test fun anUploadIsRefusedWithThePhonesReasonWhereItMakesNoSheet() {
        val phone = Caracole.phone(context)
        val why = phone.audioProblem()
        Assume.assumeTrue("the chord models are installed here", why != null)
        val (status, out) = upload(phone, asset("fixtures/autochords/decode.flac"), "decode.flac")
        assertEquals(409, status)
        assertEquals("${AudioRoutes.NOT_HERE}: $why.", out.getString("error"))
        val staged = File(phone.parts.stateDir, "audio").list().orEmpty().filter { it.startsWith(".upload-") }
        assertEquals(emptyList<String>(), staged)
    }

    @Test fun aClipUploadedOverHttpIsStagedAndItsSheetQueued() {
        Assume.assumeTrue("no chord models pushed: device-test.sh --models", pushed != null)
        val phone = installed()
        val page = get(phone, "/")
        val data = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(page)!!.groupValues[1]
        val audio = JSONObject(data).getJSONObject("server").getJSONObject("audio")
        assertEquals(audio.toString(), true, audio.getBoolean("ok"))
        val (status, up) = upload(phone, asset("fixtures/autochords/hearing.mp3"), "Calla Lake - River Road.mp3")
        assertEquals(up.toString(), 200, status)
        assertEquals("MP3", up.getString("format"))
        assertEquals(20.035918367346937, up.getDouble("duration"), 0.0)  // the computer's store's (examine records)
        assertEquals("Calla Lake", up.getJSONObject("guess").getString("artist"))
        val id = up.getString("upload")
        val (made, job) = post(phone, "/audio", "upload" to id, "artist" to "Calla Lake", "title" to "River Road")
        assertEquals(job.toString(), 200, made)
        val queued = phone.queue.snapshot().first { it.id == job.getJSONObject("job").getInt("id") }
        assertEquals(listOf("audio", "--progress", "--upload=$id", "--song=Calla Lake - River Road"),
                     queued.steps.single().args)
        if (queued.state == Job.QUEUED || queued.state == Job.RUNNING) {
            val (dropped, said) = json(phone, "/audio/drop", JSONObject().put("upload", id).toString())
            assertTrue(said.toString(), dropped == 409 || dropped == 404)  // 404: the job kept it already
        }
        runBlocking { withTimeout(300_000) { phone.queue.await(queued.id) } }
    }

    /** The phone with the chord models device-test.sh pushed installed by its own job (ChordsEndToEndTest's). */
    private fun installed(): Phone {
        val phone = Caracole.phone(context)
        val pins = ModelFiles.read()
        val kept = File(File(phone.parts.stateDir, ModelFiles.FOLDER), ".c${pins.contract}${ModelFiles.KEPT}")
        if (phone.models.ready() != null) {
            kept.mkdirs()
            for (pin in pins.files) File(pushed, pin.name).copyTo(File(kept, pin.name), overwrite = true)
            val job = phone.queue.submit(phone.models.spec(meteredOk = true)).first
            val done = runBlocking { withTimeout(300_000) { phone.queue.await(job.id) } }
            assertEquals(done.stages.joinToString { it.detail }, Job.DONE, done.state)
        }
        assertNull(phone.models.ready())
        PhoneChords.anyPhoneHearsForTests = true
        assertNull(phone.audioProblem())
        return phone
    }

    // --- the server, as the page's script asks it -------------------------------------------------------------------

    private fun connection(phone: Phone, path: String): HttpURLConnection =
        (URL(phone.server.origin + path).openConnection() as HttpURLConnection).apply {
            setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            setRequestProperty("Origin", phone.server.origin)
            setRequestProperty("Sec-Fetch-Site", "same-origin")
            setRequestProperty("Accept", "application/json")
            connectTimeout = 30_000
            readTimeout = 120_000
        }

    private fun csrf(phone: Phone): String {
        val data = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(get(phone, "/"))!!.groupValues[1]
        return JSONObject(data).getJSONObject("server").getString("csrf")
    }

    private fun get(phone: Phone, path: String): String = connection(phone, path).run {
        try {
            inputStream.use { String(it.readBytes(), Charsets.UTF_8) }
        } finally {
            disconnect()
        }
    }

    private fun send(phone: Phone, path: String, type: String, body: ByteArray, token: Boolean): Pair<Int, JSONObject> {
        val c = connection(phone, path)
        try {
            c.requestMethod = "POST"
            c.doOutput = true
            c.setRequestProperty("Content-Type", type)
            if (token) c.setRequestProperty("X-Caracole-Form-Token", csrf(phone))
            c.setFixedLengthStreamingMode(body.size)
            c.outputStream.use { it.write(body) }
            val status = c.responseCode
            val text = (if (status < 400) c.inputStream else c.errorStream).use { String(it.readBytes(), Charsets.UTF_8) }
            return status to JSONObject(text)
        } finally {
            c.disconnect()
        }
    }

    private fun upload(phone: Phone, data: ByteArray, name: String) =
        send(phone, "/audio/upload?name=" + URLEncoder.encode(name, "UTF-8"), "application/octet-stream", data, true)

    private fun json(phone: Phone, path: String, doc: String) =
        send(phone, path, "application/json", doc.toByteArray(), true)

    private fun post(phone: Phone, path: String, vararg fields: Pair<String, String>): Pair<Int, JSONObject> {
        val form = (listOf("csrf" to csrf(phone)) + fields).joinToString("&") { (k, v) ->
            URLEncoder.encode(k, "UTF-8") + "=" + URLEncoder.encode(v, "UTF-8")
        }
        return send(phone, path, "application/x-www-form-urlencoded", form.toByteArray(), false)
    }

    private fun asset(name: String): ByteArray = instrumentation.context.assets.open(name).use { it.readBytes() }

    private fun records(name: String): List<JSONObject> = instrumentation.context.assets.open(name)
        .bufferedReader(Charsets.UTF_8).useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }

    private fun report(line: String) {
        android.util.Log.i("caracole-audio", line)
        instrumentation.sendStatus(0, Bundle().apply { putString(Instrumentation.REPORT_KEY_STREAMRESULT, "$line\n") })
    }
}
