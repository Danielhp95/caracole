package io.github.danielhp95.caracole

import android.app.ActivityManager
import android.app.Instrumentation
import android.os.Bundle
import android.os.Process
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Scores
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.ml.EndToEnd
import io.github.danielhp95.caracole.ml.MlChordModels
import io.github.danielhp95.caracole.ml.MlProtocol
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CancellationException
import kotlin.concurrent.thread

/**
 * A sheet from an audio file, end to end in the debug app on the emulator (the design's §4.2, B2's rows), with the
 * REAL `:ml` process and the REAL chord models:
 *
 *     android/scripts/device-test.sh --models --sites chords ChordsEndToEndTest
 *
 * The models are those device-test.sh pushes (`-e models`, `/data/local/tmp/caracole-models`), installed by the
 * phone's own models' job: copied beside their folder as the files a fetch kept for its next try (ModelFiles.KEPT,
 * `stateDir/models/.c1.kept/`), each hashed again by ModelsSource.fetch, which asks GitHub nothing for them and
 * writes the folder's manifest of the real pins as a download does. The committed clip (tests/fixtures/autochords/
 * hearing.mp3, the test APK's `fixtures/` assets) is staged through the phone's AudioStore (a test's examiner: the
 * app's own is the audio routes'), its `audio` job queued on the phone's real queue; LRCLIB is the fake sites server's
 * scenario `chords` (`-e sites`), which times the clip's song within its length. It asserts:
 *
 * - the job Ready, its chords "chords over the lyrics", its time from queued to Ready said;
 * - the sheet's chords (its version's `heard`, read back to Harte labels) at B1's WCSR against the computer's hearing
 *   of that clip (vectors/autochords/models.jsonl, its thresholds the records' meta), its beats at B1's F;
 * - the job's requests LRCLIB's alone (the fake server's log), the version's maker (`made_on`, `made_by`, `models`,
 *   `runtime`), the song's checkpoints gone once heard;
 * - the `:ml` process killed mid-job fails it in words (a setup failure: Try again) while the library page answers;
 * - what `waiting` throws comes out of `hear` as itself, the `:ml` process gone after; and one hearing at a time.
 */
@RunWith(AndroidJUnit4::class)
class ChordsEndToEndTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val arguments = InstrumentationRegistry.getArguments()
    private val sites: String? = arguments.getString("sites")
    private val pushed = File(arguments.getString("models") ?: "/data/local/tmp/caracole-models")

    private val record: JSONObject by lazy {
        records("conformance/autochords/models.jsonl")
            .first { it.optString("kind") == "hearing" && it.getJSONObject("file").getString("fixture") == CLIP }
    }
    private val gates: EndToEnd.Gates by lazy {
        EndToEnd.Gates.of(records("conformance/autochords/models.jsonl").first { it.optString("kind") == "meta" }
                              .toString())
    }

    @Before fun sitesAndExaminer() {
        Assume.assumeTrue("no fake sites server: -e sites http://10.0.2.2:PORT (device-test.sh --sites chords)",
                          sites != null)
        Caracole.sitesForTests = RoutedTransport(sites!!)
        Caracole.examinerForTests = AudioStore.Examiner { _, format ->
            AudioStore.Audio(format, record.getDouble("duration"), mapOf("artist" to listOf(ARTIST),
                                                                       "title" to listOf(TITLE)))
        }
    }

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
        Caracole.examinerForTests = null
        Caracole.anyPhoneHearsForTests = false
    }

    @Test fun aClipStagedAndQueuedGivesASheetWhoseChordsAreTheComputers() {
        val phone = installed()
        val before = log().length()
        val (job, seconds) = queue(phone, TITLE)
        report("the job queued to Ready in ${"%.1f".format(seconds)} s: " + job.stages.joinToString { "${it.name} ${it.state}" })
        val ends = job.stages.associate { it.name to (it.state to it.detail) }
        assertEquals(ends.toString(), Job.DONE, job.state)
        assertEquals("done" to "chords over the lyrics", ends["chords"])
        assertEquals("ready", PhoneForms.line(job.id).getString("tone"))

        // The job asked LRCLIB alone, through the fake sites, each URL one the scenario answers.
        val asked = log(before)
        assertTrue("LRCLIB was asked", asked.length() > 0)
        for (i in 0 until asked.length()) {
            val request = asked.getJSONObject(i)
            assertEquals("a request of another site's: $request", "lrclib", request.getString("provider"))
            assertTrue("a URL the scenario doesn't answer: $request", request.getBoolean("known"))
        }

        // The sheet's chords, the computer's for the clip, by B1's gate.
        val raw = autoVersion(phone, TITLE)
        assertEquals(JsonPrimitive("synced"), raw["lyrics"])
        val heard = Heard.of(raw.getValue("heard"))
        val computer = EndToEnd.Hearing.of(Json.parseToJsonElement(record.toString()).jsonObject)
        val harte = harte(heard.chords)
        val majmin = Scores.wcsr(computer.harte, harte, "majmin")
        val tetrads = Scores.wcsr(computer.harte, harte, "tetrads")
        val beats = Scores.beatF(Scores.trimBeats(computer.beats, gates.trim), Scores.trimBeats(heard.beats, gates.trim),
                                 gates.window)
        report("$CLIP on the phone: WCSR majmin $majmin, tetrads $tetrads; beats F $beats")
        assertTrue("WCSR majmin $majmin", majmin >= gates.wcsrMajminMin)
        assertTrue("WCSR tetrads $tetrads", tetrads >= gates.wcsrTetradsMin)
        assertTrue("beats F $beats", beats >= gates.fMin)

        // Who made it and from what.
        assertEquals(JsonPrimitive("phone"), raw["made_on"])
        val id = phone.parts.database.read { db -> db.kvGet("sync:id") }
        assertEquals(id?.let(::JsonPrimitive), raw["made_by"])
        assertEquals(JsonObject(phone.models.names().mapValues { JsonPrimitive(it.value) }), raw["models"])
        assertEquals(JsonPrimitive("onnxruntime 1.32.0"), raw["runtime"])

        // Its checkpoints gone once it was heard, the process with them.
        val kept = phone.parts.database.read { db -> Songs.byKey(db, Normalize.identityKey(ARTIST, TITLE))!!.audioPath }
        assertTrue("the song's audio kept: $kept", kept != null && File(kept).isFile)
        assertTrue(!Checkpoints.of(work(phone), File(kept!!)).folder.exists())
        Pages.waitUntil("the :ml process gone", 15_000) { mlPid() == null }
    }

    @Test fun theMlProcessKilledMidJobFailsItInWordsWhileTheLibraryPageAnswers() {
        val phone = installed()
        val title = "$TITLE (killed)"
        // A longer clip of the committed ones (long.wav), so that the models are seen at work.
        val submitted = submit(phone, title, LONG)
        var killed: Int? = null
        val end = System.currentTimeMillis() + 120_000
        while (killed == null && System.currentTimeMillis() < end) {
            val now = phone.queue.job(submitted.id)!!
            if (now.state == Job.DONE || now.state == Job.FAILED) break
            val chords = now.stages.firstOrNull { it.name == "chords" }
            val pid = mlPid()
            if (chords?.state == "running" && chords.detail in HEARING && pid != null) {
                killed = pid
                Process.killProcess(pid)
            }
            Thread.sleep(20)
        }
        assertNotNull("killed the :ml process mid-job", killed)
        assertTrue(killed != Process.myPid())
        assertEquals("the library page answers while it fails", 200, PhoneForms.get(Pages.origin() + "/").first)
        val job = runBlocking { withTimeout(300_000) { phone.queue.await(submitted.id) } }
        val ends = job.stages.associate { it.name to (it.state to it.detail) }
        assertEquals(ends.toString(), Job.FAILED, job.state)
        assertEquals(Job.FAILED to MlChordModels.DIED, ends["chords"])
        // The line the library page shows says it in the setup's words; its outcome offers Try again.
        val line = PhoneForms.line(job.id)
        assertEquals(line.toString(), "failed", line.getString("tone"))
        assertEquals(MlChordModels.DIED + ".", line.getString("text"))
        val outcome = Outcomes.outcome(job, Line(line.getString("tone"), line.getString("text")))
        assertEquals("Try again", outcome.action?.label)
        assertEquals("and after it", 200, PhoneForms.get(Pages.origin() + "/").first)
        report("the :ml process ($killed) killed mid-job: ${ends["chords"]}; the library page answered")
    }

    /** `hear`'s contract on the real process: what `waiting` throws comes out as itself and the `:ml` process goes;
     * a second hearing while one goes on is refused plainly. */
    @Test fun whatWaitingThrowsComesOutAsItselfAndOneHearingGoesAtATime() {
        val phone = installed()
        val audio = clip(File(context.filesDir, "chords-test/hearing.mp3"))
        val folder = ModelFiles.read().folder(phone.parts.stateDir)
        val work = File(context.filesDir, "chords-test/work")
        fun models() = MlChordModels(context, folder, work, installed = { ModelFiles.installed(folder, ModelFiles.read()) })

        val stop = CancellationException("the queue stopped")
        var steps = 0
        val thrown = runCatching { models().hear(audio, { steps++ }, { if (steps > 0) throw stop }) }.exceptionOrNull()
        assertSame(stop, thrown)
        models().awaitEnded()  // the process goes, nothing writing after
        assertNull(mlPid())
        // What it heard before its stop came, gone: the next hearing hears it again, its steps said.
        work.deleteRecursively()

        var first: Result<Heard>? = null
        val started = java.util.concurrent.CountDownLatch(1)
        val hearing = thread { first = runCatching { models().hear(audio, { started.countDown() }, {}) } }
        assertTrue(started.await(120, java.util.concurrent.TimeUnit.SECONDS))
        val second = runCatching { models().hear(audio, {}, {}) }.exceptionOrNull()
        assertTrue("$second", second is ChordsUnavailable)
        assertEquals(MlChordModels.BUSY, second!!.message)
        hearing.join(300_000)
        assertTrue("${first?.exceptionOrNull()}", first!!.isSuccess)
        models().awaitEnded()
    }

    // --- the phone, its models and its job ---------------------------------------------------------------------------

    /** The phone with the real models installed by its own job, from the files device-test.sh pushed; the phone's
     * own reason not to hear on the emulator said first, then passed over. */
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
        assertNull(ModelFiles.installed(pins.folder(phone.parts.stateDir), pins))
        // This emulator's own reason not to hear (its memory) is the phone's answer, then passed over for the test.
        assertEquals(MlChordModels.deviceProblem(context), phone.audioProblem())
        Caracole.anyPhoneHearsForTests = true
        assertNull(phone.audioProblem())
        return phone
    }

    /** The clip staged as an upload and its job queued, as the audio routes queue it (E24's). */
    private fun submit(phone: Phone, title: String, clip: String = CLIP): Job {
        val name = clip.substringAfterLast('/')
        val staged = clip(File(context.cacheDir, name), clip).inputStream().use { input ->
            phone.audio.stage(input, name, emptySet())
        }
        val display = "$ARTIST - $title"
        val commands = JobCommands.audioSheetSteps(display, staged.id)
        val spec = JobSpec("Sheet from an audio file: $display", JobCommands.AUDIO_SHEET + Normalize.identityKey(ARTIST, title),
                           "song", JobCommands.stages(commands.map { it.args }), display = display, commands = commands)
        return phone.queue.submit(spec).first
    }

    /** The job of [title] queued, and its time from queued to over, in seconds. */
    private fun queue(phone: Phone, title: String): Pair<Job, Double> {
        val started = System.nanoTime()
        val job = submit(phone, title)
        val over = runBlocking { withTimeout(300_000) { phone.queue.await(job.id) } }
        return over to (System.nanoTime() - started) / 1e9
    }

    private fun autoVersion(phone: Phone, title: String): JsonObject = phone.parts.database.read { db ->
        val song = Songs.byKey(db, Normalize.identityKey(ARTIST, title)) ?: throw AssertionError("no song $title")
        val file = Kept.keptFiles(db, song.id).first { it.name == "sheet (auto).txt" }
        Versions.get(db, file.versionId)!!.raw
    }

    private fun work(phone: Phone) = File(phone.parts.stateDir, "cache/autochords")

    private fun clip(to: File, clip: String = CLIP): File {
        if (!to.isFile) {
            to.parentFile!!.mkdirs()
            instrumentation.context.assets.open("fixtures/$clip").use { input -> to.outputStream().use { input.copyTo(it) } }
        }
        return to
    }

    /** The `:ml` process's pid, while it runs. */
    private fun mlPid(): Int? = context.getSystemService(ActivityManager::class.java).runningAppProcesses.orEmpty()
        .firstOrNull { it.processName == context.packageName + MlProtocol.PROCESS_SUFFIX }?.pid

    /** The sheet's chords, common names (btc.py `recognize`'s), back to the Harte labels the gate reads: each common
     * name is one quality's of the vocabulary BTC hears in (checked one to one here). */
    private fun harte(chords: List<ChordSegment>): List<ChordSegment> {
        val qualities = Labels.vocabulary(170).filter { it.startsWith("C:") || it == "C" }
            .associateBy({ Labels.commonName(it).removePrefix("C") }, { if (it == "C") "maj" else it.removePrefix("C:") })
        assertEquals("one common name a quality", Labels.vocabulary(170).count { it.startsWith("C:") || it == "C" },
                     qualities.size)
        return chords.map { s ->
            if (s.label == "N") s else {
                val root = s.label.take(1) + s.label.drop(1).takeWhile { it == '#' || it == 'b' }
                val quality = qualities[s.label.removePrefix(root)] ?: throw AssertionError("no quality of ${s.label}")
                s.copy(label = if (quality == "maj") root else "$root:$quality")
            }
        }
    }

    // --- the fake sites ---------------------------------------------------------------------------------------------

    private fun read(path: String): ByteArray {
        val connection = URL(sites + path).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            assertEquals("${sites + path}", 200, connection.responseCode)
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    private fun log(since: Int = 0): JSONArray =
        JSONObject(String(read("/log?since=$since"), Charsets.UTF_8)).getJSONArray("requests")

    private fun records(name: String): List<JSONObject> = instrumentation.context.assets.open(name)
        .bufferedReader(Charsets.UTF_8).useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }

    private fun report(line: String) {
        Log.i("caracole-chords", line)
        instrumentation.sendStatus(0, Bundle().apply { putString(Instrumentation.REPORT_KEY_STREAMRESULT, "$line\n") })
    }

    companion object {
        const val CLIP = "autochords/hearing.mp3"
        const val LONG = "autochords/long.wav"
        const val ARTIST = "Calla Lake"  // the scenario `chords`' song (tests/helpers/fake_sites.py CHORDS)
        const val TITLE = "River Road"

        /** The chords stage's running words while the models hear (run.py's STEPS, the phone's cooling wait). */
        val HEARING = setOf("setting up the models", "hearing the chords", "finding the beats")
    }
}
