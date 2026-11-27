package io.github.danielhp95.caracole.ml

import android.app.ActivityManager
import android.app.Instrumentation
import android.content.ComponentName
import android.os.Bundle
import android.os.Process
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordSegment
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.autochords.Heard
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Scores
import io.github.danielhp95.caracole.autochords.Stages
import io.github.danielhp95.caracole.autochords.frontend.Mel
import io.github.danielhp95.caracole.autochords.frontend.Pcm
import java.io.File
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread
import kotlin.math.abs
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The design's B1 end-to-end gate (§4.2) on this device: each committed clip's audio file (tests/fixtures/autochords,
 * this test APK's assets) heard whole through [MlChordModels], in the `:ml` process ([MlService], [Pipeline]), against
 * the computer's hearing of it (tests/conformance/vectors/autochords/models.jsonl), every threshold read from the
 * records' meta (`gates.end_to_end`), none typed here:
 *
 * - its chords (the checkpoint's Harte labels, before common names) at a WCSR of `wcsr_majmin_min` and
 *   `wcsr_tetrads_min` (mir_eval's rules, [Scores.wcsr]) against the chords the computer's argmax names, spelled for
 *   the key; [Heard]'s chords their common names, `recognize`'s;
 * - its beats and downbeats at an F of `f_measure_min` within `window`, after `trim` s ([Scores.trimBeats]), against
 *   the computer's;
 * - its length the file's (a WAV's frames over its rate), and for the four clips (the parity tests' own inputs) each
 *   frame's chord the computer's argmax's, but where its top two were within the parity gate's margin;
 * - and the end-to-end gate's own files (`hearing` records: 44.1 kHz stereo MP3, 48 kHz stereo AAC), each model
 *   reading the computer's very length: BTC librosa's `ceil(n · ratio)`, beat_this soxr's.
 *
 * And the process boundary: the `:ml` process killed mid-hearing (after the chords, as the beats begin) is
 * [ChordsUnavailable] in its words, this process (the app's, where its server runs) and a server of its own still
 * answering; the next hearing goes on from `chords.json`, never hearing the chords again. It reports each clip's
 * scores, its time end to end and the `:ml` process's peak RSS while it heard.
 */
@RunWith(AndroidJUnit4::class)
class PipelineTest {
    @Before fun fresh() {
        work.deleteRecursively()
    }

    @Test fun theModelsAreReadyAndAFolderWithoutThemSaysWhy() {
        assertNull(MlChordModels(context, models, work).ready())
        val none = MlChordModels(context, File(context.filesDir, "no-models"), work).ready()
        assertTrue("$none", none!!.startsWith("the chord models aren't on the phone: no btc-graph.onnx"))
    }

    @Test fun eachClipHeardEndToEndMeetsTheGates() {
        val failures = mutableListOf<String>()
        val parity = gates.getJSONObject("btc")
        for (clip in clips) {
            val name = clip.getString("clip")
            val steps = mutableListOf<String>()
            val chords = MlChordModels(context, models, work, threads)
            val started = System.nanoTime()
            val heard = chords.hear(audio(name), { steps += it }, {})
            val took = (System.nanoTime() - started) / 1e9
            assertEquals(name, Pipeline.STEPS, steps)
            assertEquals(name, Pcm.format(audio(name))!!.seconds, heard.duration, 0.0)
            val btc = clip.getJSONObject("btc")
            val argmax = ints(btc.getJSONArray("argmax"))
            val scores = scores(name, argmax, btc.getJSONArray("segments"), clip.getJSONObject("beats"), chords, heard)
            // The clip's inputs are the parity tests' own (22,050 Hz mono): each frame BTC's argmax, the computer's but
            // where its top two were within the parity gate's margin, so a frame a wrong pad flips can't hide.
            val margin = btc.getJSONArray("margin")
            val reference = frameLabels(Labels.spellForKey(Labels.framesToSegments(argmax, Labels.FRAME_SECONDS,
                Labels.vocabulary(OrtModels.CLASSES))), argmax.size)
            val got = frameLabels(harte(chords, audio(name)), argmax.size)
            val differ = reference.indices.filter { reference[it] != got[it] }
            for (t in differ) {
                if (margin.getDouble(t) >= parity.getDouble("margin_under")) failures += "$name: frame $t is ${got[t]}"
            }
            report("$name: ${scores.line}; frames differing ${differ}; ${"%.1f".format(took)} s end to end, :ml's " +
                "peak RSS ${chords.lastPeakKb?.let { it / 1024 }} MB")
            failures += scores.failures.map { "$name: $it" }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    /** The end-to-end gate's own files: 44.1 kHz stereo MP3 and 48 kHz stereo AAC, one decode here where the computer
     * decodes twice (libsndfile or FFmpeg for BTC, torchaudio for beat_this), resampled once in float32 where
     * beat_this resamples in float64, each model's input of the computer's very length. */
    @Test fun eachEncodedFileHeardEndToEndMeetsTheGatesEachModelReadingTheComputersLength() {
        val failures = mutableListOf<String>()
        assertEquals(2, hearings.size)
        for (record in hearings) {
            val name = record.getJSONObject("file").getString("fixture").substringAfterLast('/')
            val chords = MlChordModels(context, models, work, threads)
            val started = System.nanoTime()
            val heard = chords.hear(audio(name), {}, {})
            val took = (System.nanoTime() - started) / 1e9
            val btc = record.getJSONObject("btc")
            val argmax = runs(btc.getJSONArray("argmax"))
            assertEquals(name, btc.getInt("frames"), argmax.size)
            val beats = record.getJSONObject("beats")
            val points = chords.checkpoints(audio(name))
            val pcm = Checkpoints.readPcm(points.read(Checkpoints.PCM_META)!!)
            val scores = scores(name, argmax, btc.getJSONArray("segments"), beats, chords, heard)
            report("$name: ${scores.line}; BTC read ${pcm.btcSamples} samples (the computer's " +
                "${btc.getLong("samples")}), beat_this ${Mel.frames(pcm.samples.toInt())} frames of ${pcm.samples} " +
                "samples (the computer's ${beats.getInt("frames")} frames); ${heard.duration} s (read_audio's " +
                "${record.getDouble("duration")}); ${"%.1f".format(took)} s end to end, :ml's peak RSS " +
                "${chords.lastPeakKb?.let { it / 1024 }} MB")
            if (pcm.btcSamples != btc.getLong("samples")) failures += "$name: BTC read ${pcm.btcSamples} samples"
            if (Mel.frames(pcm.samples.toInt()) != beats.getInt("frames")) failures += "$name: the mel's frames"
            if (heard.duration != record.getDouble("duration")) failures += "$name: its length ${heard.duration}"
            failures += scores.failures.map { "$name: $it" }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    /** The test APK's manifest (:ml's merged): MlService alone in the process MlProtocol names. */
    @Test fun theServiceRunsInTheProcessTheProtocolNames() {
        val info = context.packageManager.getServiceInfo(ComponentName(context, MlService::class.java), 0)
        assertEquals(context.packageName + MlProtocol.PROCESS_SUFFIX, info.processName)
        assertFalse(info.exported)
    }

    @Test fun theMlProcessKilledMidHearingIsChordsUnavailableAndTheNextHearingGoesOnFromItsChords() {
        val clip = clips.first { it.getString("clip") == "long" }
        val file = audio("long")
        val server = ServerSocket(0)
        thread(isDaemon = true) {
            while (!server.isClosed) try {
                server.accept().use { it.getOutputStream().write("ok\n".toByteArray()) }
            } catch (e: Exception) {
                break
            }
        }
        try {
            val chords = MlChordModels(context, models, work, threads)
            var killed: Int? = null
            val e = runCatching {
                chords.hear(file, { step ->
                    if (step == Pipeline.STEPS[2] && killed == null) killed = mlPid()?.also(Process::killProcess)
                }, {})
            }.exceptionOrNull()
            assertTrue("killed the :ml process (${killed})", killed != null && killed != Process.myPid())
            assertTrue("$e", e is ChordsUnavailable)
            assertEquals(MlChordModels.DIED, e!!.message)
            // This process, where the app's server lives, still answers.
            val answer = Socket("127.0.0.1", server.localPort).use { it.getInputStream().bufferedReader().readLine() }
            assertEquals("ok", answer)
            val points = chords.checkpoints(file)
            assertTrue(points.has(Checkpoints.CHORDS))
            assertFalse(points.has(Checkpoints.BEATS))
            assertFalse(points.has(Checkpoints.HEARD))
            assertTrue(points.folder.list()!!.none { it.endsWith(Checkpoints.PART) && it.startsWith("chords") })

            val steps = mutableListOf<String>()
            val heard = chords.hear(file, { steps += it }, {})
            assertEquals(listOf(Pipeline.STEPS[0], Pipeline.STEPS[2]), steps)
            val btc = clip.getJSONObject("btc")
            val scores = scores("long", ints(btc.getJSONArray("argmax")), btc.getJSONArray("segments"),
                clip.getJSONObject("beats"), chords, heard)
            report("long, after the kill: ${scores.line}")
            assertTrue(scores.failures.joinToString("\n"), scores.failures.isEmpty())
            // Heard whole, the next asks nothing of the models.
            val again = mutableListOf<String>()
            assertEquals(heard, chords.hear(file, { again += it }, {}))
            assertEquals(emptyList<String>(), again)
        } finally {
            server.close()
        }
    }

    @Test fun everyDecodedFileIsMonoAt22050HzOfTheLengthItStates() {
        val pipeline = Pipeline(models, HeatGauge { Heat.Reading("none", null, null, 80, false, false) })
        // Each file's samples at 22,050 Hz soxr's (about the computer's frames' at its rate, scaled), those BTC reads
        // librosa's ceil(n · ratio) exactly.
        val failures = mutableListOf<String>()
        for (record in decodeRecords) {
            val name = record.getJSONObject("file").getString("fixture").substringAfterLast('/')
            val file = audio(name)
            val points = Checkpoints.of(work, file)
            val pcm = pipeline.pcm(file, points)
            val rate = record.getInt("rate")
            val expected = record.getLong("frames") * Pipeline.RATE.toDouble() / rate
            val within = 1 + decodeGates.getLong("decoded_within_samples") * Pipeline.RATE.toDouble() / rate
            val lengthOff = abs(pcm.duration - record.getDouble("duration")) * rate
            report("$name: ${pcm.samples} samples at 22,050 Hz (about ${"%.1f".format(expected)} of the computer's " +
                "frames), stated ${pcm.duration} s against read_audio's ${record.getDouble("duration")}")
            if (abs(pcm.samples - expected) > within) failures += "$name: ${pcm.samples} samples, not $expected"
            val btc = Stages.btcSamples(record.getLong("frames"), rate)
            if (pcm.btcSamples != btc) failures += "$name: BTC reads ${pcm.btcSamples} samples, not librosa's $btc"
            if (lengthOff > decodeGates.getDouble("length_within_samples")) failures += "$name: length $lengthOff off"
            assertEquals(name, 4 * pcm.samples, points.file(Checkpoints.PCM).length())
            assertTrue(name, points.folder.list()!!.toSet() == setOf(Checkpoints.PCM, Checkpoints.PCM_META))
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    private class Scored(val line: String, val failures: List<String>)

    /** [heard] against the computer's hearing ([argmax], its chords' [segments], its [beats]), by the end-to-end
     * gate. */
    private fun scores(name: String, argmax: IntArray, segments: JSONArray, beats: JSONObject, chords: MlChordModels,
                       heard: Heard): Scored {
        val reference = Labels.spellForKey(Labels.framesToSegments(argmax, Labels.FRAME_SECONDS,
            Labels.vocabulary(OrtModels.CLASSES)))
        // The computer's argmax names the chords its record states.
        assertEquals(name, segments(segments), Labels.recognized(reference))
        val harte = harte(chords, audio(name))
        assertEquals(name, Labels.recognized(harte), heard.chords)
        assertEquals(name, Heard.CONTRACT, heard.contract)
        val failures = mutableListOf<String>()
        val majmin = Scores.wcsr(reference, harte, "majmin")
        val tetrads = Scores.wcsr(reference, harte, "tetrads")
        if (majmin < gate.getDouble("wcsr_majmin_min")) failures += "WCSR majmin $majmin"
        if (tetrads < gate.getDouble("wcsr_tetrads_min")) failures += "WCSR tetrads $tetrads"
        val trim = gate.getDouble("trim")
        val f = listOf("beats" to heard.beats, "downbeats" to heard.downbeats).associate { (key, got) ->
            val want = Scores.trimBeats(doubles(beats.getJSONArray(key)), trim)
            if (want.isEmpty()) failures += "no reference $key after $trim s"
            key to Scores.beatF(want, Scores.trimBeats(got, trim), gate.getDouble("window"))
        }
        for ((key, value) in f) if (value < gate.getDouble("f_measure_min")) failures += "$key F $value"
        return Scored("WCSR majmin $majmin, tetrads $tetrads; beats F ${f["beats"]}, downbeats F ${f["downbeats"]}",
            failures)
    }

    private fun harte(chords: MlChordModels, audio: File) =
        Checkpoints.readChords(chords.checkpoints(audio).read(Checkpoints.CHORDS)!!)

    companion object {
        private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
        private lateinit var models: File
        private var threads = 0
        private lateinit var gate: JSONObject
        private lateinit var gates: JSONObject
        private lateinit var hearings: List<JSONObject>
        private lateinit var clips: List<JSONObject>
        private lateinit var decodeRecords: List<JSONObject>
        private lateinit var decodeGates: JSONObject
        private val work get() = File(context.filesDir, "state/cache/autochords")

        @BeforeClass @JvmStatic fun read() {
            val arguments = InstrumentationRegistry.getArguments()
            val folder = arguments.getString("models")
                ?: fail("no models: run it through android/scripts/device-test.sh --ml") as Nothing
            models = File(folder)
            threads = arguments.getString("threads")?.toInt() ?: 0
            val records = records("models.jsonl")
            gates = records.first { it.optString("kind") == "meta" }.getJSONObject("gates")
            gate = gates.getJSONObject("end_to_end")
            clips = records.filter { it.optString("kind") == "clip" }
            hearings = records.filter { it.optString("kind") == "hearing" }
            val decode = records("decode.jsonl")
            decodeGates = decode.first { it.optString("kind") == "meta" }.getJSONObject("gates")
            decodeRecords = decode.filter { it.optString("kind") == "file" }
            assertEquals(4, clips.size)
        }

        /** The asset [name] as a file of this app's own, which the `:ml` process reads too. */
        fun audio(name: String): File {
            val file = File(context.filesDir, "clips/" + if ('.' in name) name else "$name.wav")
            if (!file.isFile) {
                file.parentFile!!.mkdirs()
                InstrumentationRegistry.getInstrumentation().context.assets.open("autochords/${file.name}").use { i ->
                    file.outputStream().use { i.copyTo(it) }
                }
            }
            return file
        }

        /** The `:ml` process's pid, while it runs. */
        fun mlPid(): Int? = context.getSystemService(ActivityManager::class.java).runningAppProcesses.orEmpty()
            .firstOrNull { it.processName == context.packageName + MlProtocol.PROCESS_SUFFIX }?.pid

        private fun records(name: String): List<JSONObject> = InstrumentationRegistry.getInstrumentation().context
            .assets.open("autochords/$name").bufferedReader(Charsets.UTF_8)
            .useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }

        fun ints(array: JSONArray) = IntArray(array.length()) { array.getInt(it) }

        /** A run-length argmax (`[class, frames]` each) as a frame's class each. */
        fun runs(array: JSONArray): IntArray {
            val out = ArrayList<Int>()
            for (i in 0 until array.length()) {
                val run = array.getJSONArray(i)
                repeat(run.getInt(1)) { out += run.getInt(0) }
            }
            return out.toIntArray()
        }

        /** Each of [frames] frames' label, from segments whose times are [Labels.time]'s of their first frames. */
        fun frameLabels(segments: List<ChordSegment>, frames: Int): List<String> {
            val out = ArrayList<String>(frames)
            var i = 0
            for (s in segments) while (i < frames && Labels.time(i, Labels.FRAME_SECONDS) < s.end) {
                out += s.label
                i++
            }
            while (out.size < frames) out += "?"
            return out
        }

        fun doubles(array: JSONArray) = List(array.length()) { array.getDouble(it) }

        fun segments(array: JSONArray) = List(array.length()) {
            val s = array.getJSONArray(it)
            ChordSegment(s.getDouble(0), s.getDouble(1), s.getString(2))
        }

        fun report(line: String) {
            Log.i("caracole-ml", line)
            InstrumentationRegistry.getInstrumentation().sendStatus(0, Bundle().apply {
                putString(Instrumentation.REPORT_KEY_STREAMRESULT, "$line\n")
            })
        }
    }
}
