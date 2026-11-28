package io.github.danielhp95.caracole

import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.YouTubeRow
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

/**
 * A sheet from a YouTube video, end to end in the debug app on the emulator (the phone-youtube plan's Y2.7), with the
 * REAL `:ml` process and chord models and a test yt-dlp:
 *
 *     android/scripts/device-test.sh --models --sites chords YouTubeEndToEndTest
 *
 * The models are those device-test.sh pushes, installed by the phone's own models' job (as ChordsEndToEndTest does).
 * yt-dlp is [Caracole.youtubeForTests], a test process ([ClipYtDlp]) whose one download is the committed clip
 * (tests/fixtures/autochords/hearing.m4a, the test APK's `fixtures/` assets) written where the job's `-o` says: the
 * app's own gate, readiness and folder kept, nothing reaching YouTube. LRCLIB is the fake sites server's scenario
 * `chords` (`-e sites`), which times Calla Lake's River Road within the clip's length. The video is pasted into the
 * library page's request form (its YouTube field: `POST /request` with `youtube`, the form token, as the page posts
 * it). It asserts:
 *
 * - the job Ready, its chords "chords over the lyrics", its line's tone "ready";
 * - its requests the lyrics sites' (the fake sites' log: LRCLIB's alone) and the fake yt-dlp's (one run, its argv the
 *   app's own: `--proxy` the gate's, the video after `--`);
 * - the video's audio gone after Ready (no file in `cache/youtube/`, the song's `audio_path` and its record's `audio`
 *   none), the sheet credited to the video (`raw.youtube.id`);
 * - Settings' YouTube audio row then "On · yt-dlp <the pinned version> · N runs in the last 24 hours", one run more
 *   than before (a rolling 24 hours: no midnight between the two reads can move it).
 */
@RunWith(AndroidJUnit4::class)
class YouTubeEndToEndTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val arguments = InstrumentationRegistry.getArguments()
    private val sites: String? = arguments.getString("sites")
    private val pushed = File(arguments.getString("models") ?: "/data/local/tmp/caracole-models")

    @Before fun sitesAndYtDlp() {
        Assume.assumeTrue("no fake sites server: -e sites http://10.0.2.2:PORT (device-test.sh --sites chords)",
                          sites != null)
        Caracole.sitesForTests = RoutedTransport(sites!!)
    }

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
        Caracole.youtubeForTests = null
        PhoneChords.anyPhoneHearsForTests = false
    }

    @Test fun aPastedVideoGivesReadyChordsOverTheLyricsAndItsAudioGoes() {
        val phone = installed()
        val ytdlp = ClipYtDlp()
        Caracole.youtubeForTests = ytdlp
        assertNull("this phone makes a sheet from a video", phone.youtubeOffered())
        val runsBefore = runsToday(phone)
        val asked = log().length()

        // The request form's YouTube field, posted as the library page posts it.
        val (status, body) = PhoneForms.post("/request", "artist" to ARTIST, "title" to TITLE, "youtube" to WATCH)
        assertEquals(body, 200, status)  // the request form's answer: the job's view (/lookup's is a 202)
        val answer = JSONObject(body)
        val id = answer.optJSONObject("job")?.getInt("id") ?: answer.getInt("job")
        val job = runBlocking { withTimeout(300_000) { phone.queue.await(id) } }
        val ends = job.stages.associate { it.name to (it.state to it.detail) }
        assertEquals(ends.toString(), Job.DONE, job.state)
        assertEquals("done" to "chords over the lyrics", ends["chords"])
        assertEquals("ready", PhoneForms.line(job.id).getString("tone"))

        // Its requests: the lyrics sites' (LRCLIB's alone, each a URL the scenario answers) and the fake yt-dlp's.
        val requests = log(asked)
        assertTrue("LRCLIB was asked", requests.length() > 0)
        for (i in 0 until requests.length()) {
            val request = requests.getJSONObject(i)
            assertEquals("a request of another site's: $request", "lrclib", request.getString("provider"))
            assertTrue("a URL the scenario doesn't answer: $request", request.getBoolean("known"))
        }
        assertEquals("one yt-dlp run", 1, ytdlp.argvs.size)
        val argv = ytdlp.argvs.single()
        assertTrue("$argv", "--proxy" in argv && argv.last() == WATCH)

        // The video's audio gone after Ready; the sheet the video's.
        phone.parts.database.read { db ->
            val song = Songs.byKey(db, Normalize.identityKey(ARTIST, TITLE)) ?: throw AssertionError("no song")
            assertNull(song.audioPath)
            assertNull(Records.load(db, song.id).audio)
            val sheet = Kept.keptFiles(db, song.id).first { it.name == "sheet (auto).txt" }
            val raw = Versions.get(db, sheet.versionId)!!.raw
            assertEquals(JsonPrimitive(VIDEO), (raw["youtube"] as JsonObject)["id"])
            assertEquals(JsonPrimitive("phone"), raw["made_on"])
        }
        val folder = YouTubeAudio.folder(File(phone.parts.stateDir, "cache"))
        assertEquals(emptyList<String>(), folder.listFiles().orEmpty().filter { it.name.endsWith(".m4a") }.map { it.name })
        assertEquals("no part folder left", emptyList<String>(),
                     folder.listFiles().orEmpty().filter { it.name.startsWith(".part-") }.map { it.name })

        // Settings' YouTube audio row says it, one run more in the last 24 hours.
        val runs = runsToday(phone)
        assertEquals(runsBefore + 1, runs)
        val expected = YouTubeRow.line(YouTubeRow.State(true, null, null, null, BuildConfig.YTDLP_VERSION, runs))
        assertEquals("On · yt-dlp ${BuildConfig.YTDLP_VERSION} · $runs run${if (runs == 1L) "" else "s"} in the last 24 hours",
                     expected)
        ActivityScenario.launch(SettingsActivity::class.java).use { settings ->
            var said = ""
            waitUntil("Settings' YouTube audio row", 30_000) {
                settings.onActivity { said = it.findViewById<TextView>(R.id.youtube_line).text.toString() }
                said == expected
            }
        }
    }

    // --- the phone, its models and its yt-dlp -----------------------------------------------------------------------

    /** The phone with the real models installed by its own job, from the files device-test.sh pushed (as
     * ChordsEndToEndTest installs them); this emulator's reason not to hear passed over. */
    private fun installed(): Phone {
        val phone = Caracole.phone(context)
        val pins = ModelFiles.read()
        val kept = File(File(phone.parts.stateDir, ModelFiles.FOLDER), ".c${pins.contract}${ModelFiles.KEPT}")
        if (phone.models.ready() != null) {
            kept.mkdirs()
            for (pin in pins.files) {
                val from = File(pushed, pin.name)
                assertTrue("no ${pin.name} in $pushed: run it through device-test.sh --models", from.isFile)
                from.copyTo(File(kept, pin.name), overwrite = true)
            }
            val job = phone.queue.submit(phone.models.spec(meteredOk = true)).first
            val done = runBlocking { withTimeout(300_000) { phone.queue.await(job.id) } }
            assertEquals(done.stages.joinToString { it.detail }, Job.DONE, done.state)
        }
        assertNull(phone.models.ready())
        PhoneChords.anyPhoneHearsForTests = true
        return phone
    }

    /** A yt-dlp of one download, as a run with no FFmpeg leaves it: the committed clip written where `-o` says, and
     * the line `--print after_move:` prints of it (its id, title, channel, length and file); a second run fails the
     * test. Nothing is sent anywhere. */
    private inner class ClipYtDlp : YtDlpProcess {
        val argvs = java.util.concurrent.CopyOnWriteArrayList<List<String>>()

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            if (argvs.isNotEmpty()) throw AssertionError("a second yt-dlp run")
            argvs += argv
            assertTrue("no -o in the argv: $argv", argv.indexOf("-o") in 0 until argv.size - 1)
            val file = File(argv[argv.indexOf("-o") + 1].replace("%(ext)s", "m4a"))
            file.parentFile!!.mkdirs()
            instrumentation.context.assets.open("fixtures/$CLIP").use { input -> file.outputStream().use { input.copyTo(it) } }
            val line = JSONObject(mapOf("id" to VIDEO, "title" to "$ARTIST - $TITLE", "channel" to ARTIST,
                                        "duration" to CLIP_SECONDS, "filepath" to file.path)).toString()
            onLine(line)
            return Ran(0, line + "\n", "")
        }
    }

    /** The yt-dlp runs of the last 24 hours, as the row counts them. */
    private fun runsToday(phone: Phone): Long = phone.parts.database.read { db -> YouTubeRow.runsSince(db, Instant.now()) }

    // --- the fake sites ---------------------------------------------------------------------------------------------

    private fun log(since: Int = 0): JSONArray {
        val connection = URL("$sites/log?since=$since").openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            assertEquals(200, connection.responseCode)
            return JSONObject(connection.inputStream.use { String(it.readBytes(), Charsets.UTF_8) }).getJSONArray("requests")
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        const val CLIP = "autochords/hearing.m4a"
        const val CLIP_SECONDS = 20.0  // its length, as yt-dlp says it (fake_sites.py CLIP_SECONDS)
        const val ARTIST = "Calla Lake"  // the scenario `chords`' song (tests/helpers/fake_sites.py CHORDS)
        const val TITLE = "River Road"
        const val VIDEO = "RiverRoad01"
        const val WATCH = "https://www.youtube.com/watch?v=$VIDEO"
    }
}
