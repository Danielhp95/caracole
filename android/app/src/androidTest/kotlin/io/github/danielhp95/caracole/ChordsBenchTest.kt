package io.github.danielhp95.caracole

import android.app.ActivityManager
import android.content.ComponentName
import android.content.pm.PackageManager
import android.os.Process
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.ml.AndroidProbe
import io.github.danielhp95.caracole.ml.Bench
import io.github.danielhp95.caracole.ml.BenchInput
import io.github.danielhp95.caracole.ml.BenchInputs
import io.github.danielhp95.caracole.ml.BenchReport
import io.github.danielhp95.caracole.ml.Device
import io.github.danielhp95.caracole.ml.OrtModels
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The debug build's Chords bench on the emulator (the design's §9.1, B0): its engine over the committed clips the
 * debug build carries, on both beat files and both memory settings, writing a report of BenchReport's shape whose
 * parity passes; a reference of the owner's (autochords_reference's JSON, its decoded samples and all) read as the
 * computer wrote it and run; and Settings' Chords bench row opening the bench in its process of its own. The models
 * are those `android/scripts/device-test.sh --ml` pushes (`-e models`): the APK carries none.
 */
@RunWith(AndroidJUnit4::class)
class ChordsBenchTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext

    private fun models(): File = File(InstrumentationRegistry.getArguments().getString("models")
        ?: fail("no models: run it through android/scripts/device-test.sh --ml") as Nothing)

    private fun bench(clips: BenchInputs.Clips, lines: MutableList<String>): Bench {
        val pins = BenchModels.pins()
        val beats = pins.getJSONObject("beats")
        return Bench(models(), pins.getJSONObject("btc").getDouble("mean").toFloat(), beats.getInt("fps"),
            beats.getInt("chunk"), beats.getInt("border"), clips.gates, AndroidProbe(context)) { lines += it }
    }

    @Test fun theCommittedClipsRunAndTheReportHasItsShape() {
        val clips = BenchClips.read(context)
        assertEquals(listOf("steady", "tempo-change", "silence", "long"), clips.inputs.map { it.name })
        val lines = mutableListOf<String>()
        val bench = bench(clips, lines)
        val plan = Bench.Plan(listOf(BenchReport.BTC, BenchReport.BEATS_FP16, BenchReport.BEATS_FP32), listOf(1),
            listOf(false, true), passes = 1)
        val file = File(context.cacheDir, "caracole-bench-test.json")
        var saves = 0
        bench.run(plan, clips.inputs.map { clip -> Bench.Source(clip.name) { clip } }, { false }) {
            saves += 1
            file.writeText(bench.report(Device.here(BuildConfig.VERSION_NAME), "2026-11-25T21:00:00Z").toString())
        }
        lines.forEach(::println)
        assertEquals("a save after each model's session", 6, saves)

        val report = Json.parseToJsonElement(file.readText()).jsonObject
        for (key in listOf("device", "soc", "android", "runtime")) assertTrue(key, report.str(key).isNotBlank())
        assertEquals(OrtModels.RUNTIME, report.str("runtime"))
        val runs = report.getValue("runs").jsonArray.map { it.jsonObject }
        assertEquals(4 * 6, runs.size)
        for (run in runs) {
            for (key in listOf("file", "model", "seconds", "rtf", "pss_peak_mb", "rss_peak_mb", "thermal",
                "battery_uah", "threads", "arena", "screen", "pass", "cold")) assertTrue("$key in $run", key in run)
            assertTrue(run.toString(), run.num("seconds") > 0)
            assertEquals(run.num("seconds") / run.num("duration"), run.num("rtf"), 1e-3)
            assertTrue("the emulator gives a PSS: $run", run.num("pss_peak_mb") > 0)
            assertTrue(run.getValue("thermal").jsonArray.isNotEmpty())
        }
        assertEquals(setOf(false, true), runs.map { it.getValue("arena").jsonPrimitive.boolean }.toSet())
        assertEquals(6, runs.count { it.getValue("cold").jsonPrimitive.boolean })
        val parity = report.getValue("parity").jsonObject
        assertEquals(4 * 2, parity.getValue("btc").jsonArray.size)
        assertEquals(4 * 2 * 2, parity.getValue("beats").jsonArray.size)
        assertTrue("parity: $parity", parity.getValue("pass").jsonPrimitive.boolean)
        assertTrue(report.getValue("summary").jsonArray.isNotEmpty())
    }

    @Test fun aReferenceOfTheOwnersIsReadAsTheComputerWroteItAndRun() {
        val clips = BenchClips.read(context)
        val steady = clips.inputs.first { it.name == "steady" }
        val file = File(context.cacheDir, "steady.json")
        file.writeText(reference(steady, duration = 12.0))
        val read = file.inputStream().use { BenchInputs.reference("steady.json", it, 50) }
        assertEquals("steady.json", read.name)
        assertEquals(12.0, read.duration, 0.0)
        assertArrayEquals(steady.cqt, read.cqt, 0f)
        assertArrayEquals(steady.btcLogits, read.btcLogits, 0f)
        assertArrayEquals(steady.mel, read.mel, 0f)
        assertArrayEquals(steady.beat, read.beat, 0f)
        assertEquals(steady.beats, read.beats)
        assertEquals(steady.downbeats, read.downbeats)
        // The margins it works out of the logits are the ones the computer stored.
        assertArrayEquals(steady.margins, read.margins, 1e-5f)
        // No length (mutagen gave none): the mel's frames at 50 a second.
        val unmeasured = File(context.cacheDir, "nolength.json").apply { writeText(reference(steady, duration = null)) }
        val length = unmeasured.inputStream().use { BenchInputs.reference("nolength.json", it, 50).duration }
        assertEquals(601 / 50.0, length, 0.0)

        val lines = mutableListOf<String>()
        val bench = bench(clips, lines)
        bench.run(Bench.Plan(listOf(BenchReport.BTC, BenchReport.BEATS_FP16), listOf(1), listOf(false), passes = 2),
            listOf(Bench.Source("steady.json") {
                file.inputStream().use { BenchInputs.reference("steady.json", it, 50) }
            }), { false }) {}
        val report = bench.report(Device.here(BuildConfig.VERSION_NAME), "2026-11-25T21:00:00Z")
        assertEquals(4, report.getValue("runs").jsonArray.size)
        val parity = report.getValue("parity").jsonObject
        assertTrue("parity: $parity", parity.getValue("pass").jsonPrimitive.boolean)
        assertEquals(listOf("steady.json"), parity.getValue("btc").jsonArray.map { it.jsonObject.str("file") })
    }

    @Test fun settingsChordsBenchRowOpensTheBenchInAProcessOfItsOwn() {
        @Suppress("DEPRECATION")
        val info = context.packageManager.getActivityInfo(ComponentName(context, ChordsBenchActivity::class.java),
            PackageManager.GET_META_DATA)
        assertEquals("${context.packageName}:bench", info.processName)
        assertTrue(!info.exported)
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            var row: Button? = null
            scenario.onActivity { settings ->
                row = buttons(settings.window.decorView).firstOrNull { it.text == SettingsActivity.CHORDS_BENCH }
            }
            assertTrue("Settings shows the Chords bench row in a debug build", row != null)
            instrumentation.runOnMainSync { row!!.performClick() }
            val manager = context.getSystemService(ActivityManager::class.java)
            val deadline = System.currentTimeMillis() + 20_000
            var bench: ActivityManager.RunningAppProcessInfo? = null
            while (bench == null && System.currentTimeMillis() < deadline) {
                bench = manager.runningAppProcesses.orEmpty().firstOrNull { it.processName == info.processName }
                if (bench == null) Thread.sleep(200)
            }
            assertTrue("the bench's process started", bench != null)
            assertTrue("never this process", bench!!.pid != Process.myPid())
            Process.killProcess(bench.pid)
        }
    }

    private fun buttons(view: View): List<Button> = when (view) {
        is Button -> listOf(view)
        is ViewGroup -> (0 until view.childCount).flatMap { buttons(view.getChildAt(it)) }
        else -> emptyList()
    }

    /** A reference as tests/helpers/autochords_reference.py writes one (its keys sorted, every array float32), of a
     * clip's arrays, with 6 MB of decoded samples the reader must pass over. */
    private fun reference(clip: BenchInput, duration: Double?): String = JSONObject().apply {
        put("beat_logits", JSONObject().put("beat", array(clip.beat, listOf(clip.melFrames)))
            .put("downbeat", array(clip.downbeat, listOf(clip.melFrames))))
        put("beats", org.json.JSONArray(clip.beats))
        put("decoded", array(FloatArray(1_500_000) { it / 1e6f }, listOf(1_500_000)))
        put("downbeats", org.json.JSONArray(clip.downbeats))
        put("duration", duration ?: JSONObject.NULL)
        put("features", array(clip.cqt, listOf(clip.btcFrames, OrtModels.BINS)))
        put("file", "steady.flac")
        put("logits", array(clip.btcLogits, listOf(clip.btcFrames, OrtModels.CLASSES)))
        put("mel", array(clip.mel, listOf(clip.melFrames, OrtModels.MELS)))
        put("segments", org.json.JSONArray())
    }.toString()

    private fun array(values: FloatArray, shape: List<Int>): JSONObject {
        val bytes = ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        bytes.asFloatBuffer().put(values)
        return JSONObject().put("base64", Base64.getEncoder().encodeToString(bytes.array()))
            .put("dtype", "float32").put("shape", org.json.JSONArray(shape))
    }

    private fun JsonObject.str(key: String) = getValue(key).jsonPrimitive.content
    private fun JsonObject.num(key: String) = getValue(key).jsonPrimitive.double
}
