package io.github.danielhp95.caracole.ml

import ai.onnxruntime.OrtEnvironment
import android.app.Instrumentation
import android.content.pm.PackageManager
import android.os.Bundle
import android.system.Os
import android.util.Half
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Base64
import kotlin.math.abs
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The design's B0 gates (§4.2) on this device's ONNX Runtime, over the computer's own records
 * (tests/conformance/vectors/autochords/models.jsonl, its inputs in frontend.jsonl), every threshold read from the
 * records' meta (`gates`), none typed here:
 *
 * - BTC: every frame's argmax the computer's, but where its stored top-two margin is under `margin_under`; its logits
 *   within `logits_max_abs`;
 * - beat_this's fp32 file: its logits within `logits_max_abs`;
 * - beat_this's fp16-stored file: no logit bound (`logits_max_abs` null), its beats and downbeats at an F-measure of
 *   `f_measure_min` or more against the computer's, within `window`, after the first `trim` seconds; a clip with no
 *   reference beat after the trim fails, never passes for nothing.
 *
 * The models are those `nix build .#chord-models` makes, pushed by `android/scripts/device-test.sh --ml` into the
 * folder the argument `models` names; models.json, :ml's resource (caracole/autochords/, with BTC's graph), pins each
 * file, and the APK carries no weights. It reports what it measured on its stream: each model's load and each clip's
 * run, and each model's peak RSS.
 */
@RunWith(AndroidJUnit4::class)
class ModelParityTest {
    @Test fun theFilesAreTheOnesModelsJsonPins() {
        for ((name, pin) in listOf(
            OrtModels.BTC_GRAPH to pins.getJSONObject("btc").getJSONObject("graph"),
            OrtModels.BTC_WEIGHTS to pins.getJSONObject("btc").getJSONObject("weights"),
            OrtModels.BEATS_FP32 to pins.getJSONObject("beats").getJSONObject("fp32"),
            OrtModels.BEATS_FP16 to pins.getJSONObject("beats").getJSONObject("fp16"),
        )) {
            assertEquals(pin.getString("name"), name)
            val file = File(models, name)
            assertEquals(name, pin.getLong("bytes"), file.length())
            assertEquals(name, pin.getString("sha256"), sha256(file))
        }
        // :ml carries the graph on its classpath (caracole/autochords/, the debug build's alone): the one pinned.
        val graph = javaClass.classLoader!!.getResourceAsStream("caracole/autochords/${OrtModels.BTC_GRAPH}")!!
            .use { it.readBytes() }
        assertEquals(pins.getJSONObject("btc").getJSONObject("graph").getString("sha256"), sha256(graph))
        val btc = pins.getJSONObject("btc")
        assertEquals(btc.getInt("window"), OrtModels.WINDOW)
        assertEquals(btc.getInt("bins"), OrtModels.BINS)
        assertEquals(btc.getInt("classes"), OrtModels.CLASSES)
        assertEquals(pins.getJSONObject("beats").getInt("bins"), OrtModels.MELS)
        assertEquals("mean", btc.getString("pad"))
    }

    @Test fun theRuntimeIsTheOneBuiltAgainstWithItsTelemetryOff() {
        OrtModels(models, threads).use { ort ->
            assertEquals(OrtModels.RUNTIME, "onnxruntime " + OrtEnvironment.getEnvironment().version)
            assertEquals("1", Os.getenv("ORT_DISABLE_TELEMETRY"))
            assertEquals(pins.getJSONObject("btc").getDouble("mean").toFloat(), ort.padding)
        }
        // This test package carries :ml's manifest, which removes the runtime's TelemetryInitializer.
        val context = InstrumentationRegistry.getInstrumentation().context
        @Suppress("DEPRECATION")
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PROVIDERS)
        val providers = info.providers.orEmpty().map { it.name }
        assertEquals(emptyList<String>(), providers.filter { it.startsWith("ai.onnxruntime.") })
    }

    @Test fun btcGivesTheComputersChords() {
        val gate = gates.getJSONObject("btc")
        val loaded = System.nanoTime()
        measured("btc") { OrtModels(models, threads).use { ort ->
            val padding = ort.padding
            var first = true
            for (clip in clips) {
                val frontend = inputs.getValue(clip.getString("clip"))
                val cqt = floats(frontend.getJSONObject("cqt"))
                val btc = clip.getJSONObject("btc")
                val frames = btc.getInt("frames")
                assertEquals(clip.getString("clip"), frames * OrtModels.BINS, cqt.size)
                val windows = (frames + OrtModels.WINDOW - 1) / OrtModels.WINDOW
                val features = FloatArray(windows * OrtModels.WINDOW * OrtModels.BINS) { padding }
                System.arraycopy(cqt, 0, features, 0, cqt.size)
                val started = System.nanoTime()
                val logits = ort.chords(features, windows)
                if (first) report("btc: loaded and first run ${seconds(loaded)} s")
                first = false
                report("btc ${clip.getString("clip")}: $windows windows in ${seconds(started)} s")
                val want = floats(btc.getJSONObject("logits"))
                val argmax = ints(btc.getJSONArray("argmax"))
                val margin = btc.getJSONArray("margin")
                var most = 0f
                val differ = mutableListOf<Int>()
                for (t in 0 until frames) {
                    var best = 0
                    for (k in 0 until OrtModels.CLASSES) {
                        val i = t * OrtModels.CLASSES + k
                        most = maxOf(most, abs(logits[i] - want[i]))
                        if (logits[i] > logits[t * OrtModels.CLASSES + best]) best = k
                    }
                    if (best != argmax[t]) differ += t
                }
                report("btc ${clip.getString("clip")}: logits within $most; argmax differs at $differ")
                for (t in differ) {
                    assertTrue("${clip.getString("clip")} frame $t",
                        margin.getDouble(t) < gate.getDouble("margin_under"))
                }
                assertTrue("${clip.getString("clip")}: $most", most <= gate.getDouble("logits_max_abs"))
            }
        } }
    }

    @Test fun beatThisFp32GivesTheComputersLogits() {
        val gate = gates.getJSONObject("beats_fp32")
        measured("beats fp32") { OrtModels(models, threads, OrtModels.BEATS_FP32).use { ort ->
            for ((clip, beat, downbeat) in beatLogits(ort, "fp32")) {
                val record = clip.getJSONObject("beats")
                var most = 0f
                for ((got, name) in listOf(beat to "beat", downbeat to "downbeat")) {
                    val want = floats(record.getJSONObject(name))
                    assertEquals(want.size, got.size)
                    for (i in want.indices) most = maxOf(most, abs(got[i] - want[i]))
                }
                report("beats fp32 ${clip.getString("clip")}: logits within $most")
                assertTrue("${clip.getString("clip")}: $most", most <= gate.getDouble("logits_max_abs"))
            }
        } }
    }

    @Test fun beatThisFp16GivesTheComputersBeats() {
        val gate = gates.getJSONObject("beats_fp16")
        assertTrue(gate.isNull("logits_max_abs"))
        measured("beats fp16") { OrtModels(models, threads, OrtModels.BEATS_FP16).use { ort ->
            for ((clip, beat, downbeat) in beatLogits(ort, "fp16")) {
                val name = clip.getString("clip")
                val (beats, downbeats) = BeatThis.peaks(beat, downbeat, fps)
                for ((key, got) in listOf("beats" to beats, "downbeats" to downbeats)) {
                    val reference = BeatThis.trimmed(doubles(clip.getJSONObject("beats").getJSONArray(key)),
                        gate.getDouble("trim"))
                    assertTrue("$name: no reference $key after ${gate.getDouble("trim")} s", reference.isNotEmpty())
                    val f = BeatThis.fMeasure(reference, BeatThis.trimmed(got, gate.getDouble("trim")),
                        gate.getDouble("window"))
                    report("beats fp16 $name: $key F = $f")
                    assertTrue("$name $key: F = $f", f >= gate.getDouble("f_measure_min"))
                }
            }
        } }
    }

    /** The postprocessor ported for the fp16 gate gives the computer's beats from the computer's own logits, so the
     * F-measure above compares what beat_this would find. */
    @Test fun thePeaksOfTheComputersLogitsAreItsBeats() {
        for (clip in clips) {
            val record = clip.getJSONObject("beats")
            val (beats, downbeats) = BeatThis.peaks(floats(record.getJSONObject("beat")),
                floats(record.getJSONObject("downbeat")), fps)
            assertEquals(clip.getString("clip"), doubles(record.getJSONArray("beats")), beats)
            assertEquals(clip.getString("clip"), doubles(record.getJSONArray("downbeats")), downbeats)
        }
        assertEquals(1.0, BeatThis.fMeasure(listOf(5.0, 5.5, 6.0), listOf(5.06, 5.5, 6.05), 0.07), 0.0)
        assertEquals(0.8, BeatThis.fMeasure(listOf(5.0, 5.5, 6.0), listOf(5.0, 5.5), 0.07), 1e-12)
        assertEquals(0.0, BeatThis.fMeasure(listOf(5.0), emptyList(), 0.07), 0.0)
    }

    private data class Run(val clip: JSONObject, val beat: FloatArray, val downbeat: FloatArray)

    private fun beatLogits(ort: OrtModels, file: String): List<Run> {
        val beats = pins.getJSONObject("beats")
        val loaded = System.nanoTime()
        var first = true
        return clips.map { clip ->
            val name = clip.getString("clip")
            val mel = halves(inputs.getValue(name).getJSONObject("mel"))
            val frames = mel.size / OrtModels.MELS
            val started = System.nanoTime()
            val (beat, downbeat) = BeatThis.logits(mel, frames, OrtModels.MELS, beats.getInt("chunk"),
                beats.getInt("border")) { chunk, length -> ort.beats(chunk, length) }
            if (first) report("beats $file: loaded and first clip ${seconds(loaded)} s")
            first = false
            report("beats $file $name: $frames frames in ${seconds(started)} s, " +
                "peak RSS so far ${status("VmHWM") / 1024} MB")
            Run(clip, beat, downbeat)
        }
    }

    companion object {
        private lateinit var models: File
        private var threads = 1
        private lateinit var pins: JSONObject
        private lateinit var gates: JSONObject
        private var fps = 0
        private lateinit var clips: List<JSONObject>
        private lateinit var inputs: Map<String, JSONObject>

        @BeforeClass @JvmStatic fun read() {
            val arguments = InstrumentationRegistry.getArguments()
            val folder = arguments.getString("models")
                ?: fail("no models: run it through android/scripts/device-test.sh --ml") as Nothing
            models = File(folder)
            threads = arguments.getString("threads")?.toInt() ?: 1
            pins = JSONObject(ModelParityTest::class.java.classLoader!!
                .getResourceAsStream("caracole/autochords/models.json")!!.bufferedReader(Charsets.UTF_8).readText())
            fps = pins.getJSONObject("beats").getInt("fps")
            val meta = records("models.jsonl").first { it.optString("kind") == "meta" }
            gates = meta.getJSONObject("gates")
            clips = records("models.jsonl").filter { it.optString("kind") == "clip" }
            inputs = records("frontend.jsonl").filter { it.optString("kind") == "clip" }
                .associateBy { it.getString("clip") }
            assertTrue(clips.isNotEmpty())
            report("models in $models, $threads thread(s)")
        }

        /** [block] run with the process's peak RSS reset first (`/proc/self/clear_refs`), its resident memory before
         * and its peak while it ran reported: the test's own records (a few MB) and runtime included. */
        fun measured(what: String, block: () -> Unit) {
            val before = status("VmRSS")
            File("/proc/self/clear_refs").writeText("5")
            block()
            report("$what: resident before ${before / 1024} MB, peak RSS ${status("VmHWM") / 1024} MB")
        }

        /** A line of `/proc/self/status`, in kB. */
        fun status(key: String): Long = File("/proc/self/status").readLines().first { it.startsWith("$key:") }
            .substringAfter(':').trim().removeSuffix("kB").trim().toLong()

        private fun asset(name: String) = InstrumentationRegistry.getInstrumentation().context.assets
            .open("autochords/$name").bufferedReader(Charsets.UTF_8)

        /** A corpus file's records, a line at a time (its first line the header). */
        private fun records(name: String): List<JSONObject> =
            asset(name).useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }

        private fun bytes(array: JSONObject): ByteBuffer =
            ByteBuffer.wrap(Base64.getDecoder().decode(array.getString("base64"))).order(ByteOrder.LITTLE_ENDIAN)

        fun floats(array: JSONObject): FloatArray {
            assertEquals("float32", array.getString("dtype"))
            val buffer = bytes(array).asFloatBuffer()
            return FloatArray(buffer.remaining()).also { buffer.get(it) }
        }

        /** A float16 array (the mel, as the computer's beat logits were computed over it), as float32. */
        fun halves(array: JSONObject): FloatArray {
            assertEquals("float16", array.getString("dtype"))
            val buffer = bytes(array).asShortBuffer()
            return FloatArray(buffer.remaining()) { Half.toFloat(buffer.get(it)) }
        }

        fun ints(array: JSONArray) = IntArray(array.length()) { array.getInt(it) }

        fun doubles(array: JSONArray) = List(array.length()) { array.getDouble(it) }

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val chunk = ByteArray(1 shl 20)
                while (true) {
                    val n = input.read(chunk)
                    if (n < 0) break
                    digest.update(chunk, 0, n)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        fun seconds(since: Long) = "%.2f".format((System.nanoTime() - since) / 1e9)

        /** A line on the instrumentation's stream (am instrument's output) and the log. */
        fun report(line: String) {
            Log.i("caracole-ml", line)
            InstrumentationRegistry.getInstrumentation().sendStatus(0, Bundle().apply {
                putString(Instrumentation.REPORT_KEY_STREAMRESULT, "$line\n")
            })
        }
    }
}
