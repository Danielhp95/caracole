package io.github.danielhp95.caracole.ml

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Chords bench's report from fixed timings, samples and logits: what it computes (RTF, peaks, the battery's
 * change, the summary Gate B0 reads, parity against the computer's), and its shape, with nothing of the phone's but
 * its model, SoC and Android. */
class BenchReportTest {
    private val device = Device(device = "Sony XQ-DQ72", soc = "QTI SM8550", android = "14 (API 34)",
        app = "0.4.0-debug")

    private fun run(file: String = "steady", model: String = BenchReport.BTC, pass: Int = 1, cold: Boolean = false,
                    seconds: Double = 2.5, duration: Double = 10.0, screen: String = "on",
                    samples: List<Sample> = listOf(Sample(100_000, "none", 0.2f)),
                    rss: Long? = 400_000, battery: Pair<Long?, Long?> = 1_000_000L to 990_000L) =
        Run(file = file, model = model, pass = pass, threads = 4, arena = false, screen = screen, cold = cold,
            nanos = (seconds * 1e9).toLong(), duration = duration, samples = samples, rssPeakKb = rss,
            batteryStartUah = battery.first, batteryEndUah = battery.second)

    private val gates = Gates(btcMarginUnder = 1e-3, btcLogitsMaxAbs = 1e-4, fp32LogitsMaxAbs = 1e-3,
        fp16FMin = 0.99, trim = 5.0, window = 0.07)

    private fun report(runs: List<Run>, parity: Parity = Parity(gates, emptyList(), emptyList())) =
        BenchReport.of(runs, parity, device, made = "2026-11-25T21:00:00Z")

    @Test fun aRunsRtfIsItsSecondsOverTheAudiosAndItsPeaksTheLargestSamples() {
        val samples = listOf(Sample(100_000, "none", 0.31f), Sample(300_000, "none", 0.52f),
            Sample(null, "light", null), Sample(200_000, "none", 0.47f))
        val out = report(listOf(run(samples = samples))).getValue("runs").jsonArray.single().jsonObject
        assertEquals("steady", out.str("file"))
        assertEquals(BenchReport.BTC, out.str("model"))
        assertEquals(2.5, out.num("seconds"), 0.0)
        assertEquals(10.0, out.num("duration"), 0.0)
        assertEquals(0.25, out.num("rtf"), 0.0)
        assertEquals(293.0, out.num("pss_peak_mb"), 0.0)  // 300,000 kB
        assertEquals(390.6, out.num("rss_peak_mb"), 0.0)  // 400,000 kB
        assertEquals(listOf("none", "light"), out.getValue("thermal").jsonArray.map { it.jsonPrimitive.content })
        assertEquals(0.52, out.num("headroom_max"), 1e-6)
        assertEquals(-10_000L, out.getValue("battery_uah").jsonPrimitive.long)
        assertEquals(4, out.getValue("threads").jsonPrimitive.int)
        assertFalse(out.getValue("arena").jsonPrimitive.boolean)
        assertEquals("on", out.str("screen"))
        assertEquals(1, out.getValue("pass").jsonPrimitive.int)
        assertFalse(out.getValue("cold").jsonPrimitive.boolean)
    }

    @Test fun whatThePhoneDoesntSayIsNullNeverAGuess() {
        val out = report(listOf(run(samples = listOf(Sample(null, Heat.UNKNOWN, null)), rss = null,
            battery = null to 990_000L))).getValue("runs").jsonArray.single().jsonObject
        assertEquals(JsonNull, out.getValue("pss_peak_mb"))
        assertEquals(JsonNull, out.getValue("rss_peak_mb"))
        assertEquals(JsonNull, out.getValue("headroom_max"))
        assertEquals(JsonNull, out.getValue("battery_uah"))
        assertEquals(listOf(Heat.UNKNOWN), out.getValue("thermal").jsonArray.map { it.jsonPrimitive.content })
    }

    @Test fun theSummaryGroupsTheWarmRunsBySettingAndScreen() {
        val runs = listOf(
            run(model = BenchReport.BEATS_FP16, cold = true, seconds = 9.0),  // the session's load: left out
            run(model = BenchReport.BEATS_FP16, pass = 2, seconds = 1.0, rss = 900_000),
            run(model = BenchReport.BEATS_FP16, pass = 3, seconds = 1.5, rss = 950_000),
            run(model = BenchReport.BEATS_FP16, pass = 4, seconds = 2.0, rss = 1_200_000),
            run(model = BenchReport.BEATS_FP16, pass = 2, seconds = 1.0, screen = "off"),
        )
        val summary = report(runs).getValue("summary").jsonArray.map { it.jsonObject }
        assertEquals(2, summary.size)
        val on = summary.first { it.str("screen") == "on" }
        assertEquals(BenchReport.BEATS_FP16, on.str("model"))
        assertEquals(3, on.getValue("runs").jsonPrimitive.int)
        assertEquals(0.15, on.num("rtf_median"), 1e-9)
        assertEquals(0.2, on.num("rtf_max"), 1e-9)
        assertEquals(1171.9, on.num("rss_peak_mb"), 0.0)
        assertFalse("0.2 > 0.125", on.getValue("speed_ok").jsonPrimitive.boolean)
        assertFalse("1171.9 MB > 1024", on.getValue("memory_ok").jsonPrimitive.boolean)
        val off = summary.first { it.str("screen") == "off" }
        assertEquals(1, off.getValue("runs").jsonPrimitive.int)
        assertTrue(off.getValue("speed_ok").jsonPrimitive.boolean)
    }

    @Test fun btcParityCountsOnlyTheDisagreementsWhereTheComputerWasSure() {
        val classes = OrtModels.CLASSES
        val want = FloatArray(3 * classes)
        want[0 * classes + 5] = 4f
        want[1 * classes + 7] = 2f; want[1 * classes + 8] = 1.9995f  // margin 0.0005: a near tie
        want[2 * classes + 9] = 3f
        val got = want.copyOf()
        got[1 * classes + 8] = 2.00002f  // the near tie goes the other way
        val near = BtcParity.of("steady", 4, false, got, want, BtcParity.margins(want, 3), 3)
        assertEquals(3, near.frames)
        assertEquals(2.0 / 3, near.agreement, 1e-12)
        assertEquals(0, near.differOverMargin(gates))
        assertEquals(0.00052f, near.logitsMaxAbs, 1e-6f)
        assertFalse("its logits moved by more than 1e-4", near.pass(gates))

        val sure = got.copyOf()
        sure[1 * classes + 8] = 1.9995f
        sure[2 * classes + 9] = 0f; sure[2 * classes + 10] = 1f  // frame 2: a margin of 3 overturned
        val wrong = BtcParity.of("steady", 4, false, sure, want, BtcParity.margins(want, 3), 3)
        assertEquals(1, wrong.differOverMargin(gates))
        assertFalse(wrong.pass(gates))

        val same = BtcParity.of("steady", 4, false, want.copyOf(), want, BtcParity.margins(want, 3), 3)
        assertEquals(1.0, same.agreement, 0.0)
        assertTrue(same.pass(gates))
    }

    @Test fun beatParityIsTheFMeasureOfThePeaksAfterTheTrim() {
        // 10 s at 50 fps: a beat every half second from 5 s on, a downbeat every two.
        val beat = FloatArray(500) { -5f }
        val downbeat = FloatArray(500) { -5f }
        val wantBeats = (0 until 10).map { 5.0 + it * 0.5 }
        for (t in wantBeats) beat[(t * 50).toInt()] = 3f
        for (t in wantBeats.filterIndexed { i, _ -> i % 4 == 0 }) downbeat[(t * 50).toInt()] = 3f
        val wantDownbeats = wantBeats.filterIndexed { i, _ -> i % 4 == 0 }

        val same = BeatParity.of("steady", BenchReport.BEATS_FP16, 4, false, beat, downbeat, beat, downbeat,
            wantBeats, wantDownbeats, fps = 50, gates = gates)
        assertEquals(0f, same.logitsMaxAbs, 0f)
        assertEquals(1.0, same.beatsF!!, 0.0)
        assertEquals(1.0, same.downbeatsF!!, 0.0)
        assertTrue(same.pass(gates))

        val missing = beat.copyOf()
        missing[(7.0 * 50).toInt()] = -5f  // one beat of ten lost: F = 2 · 1 · 0.9 / 1.9
        val lost = BeatParity.of("steady", BenchReport.BEATS_FP16, 4, false, missing, downbeat, beat, downbeat,
            wantBeats, wantDownbeats, fps = 50, gates = gates)
        assertEquals(2 * 0.9 / 1.9, lost.beatsF!!, 1e-12)
        assertFalse(lost.pass(gates))
        // fp16 has no logit bound; fp32's is 1e-3, which a lost peak's 8 breaks.
        val fp32 = BeatParity.of("steady", BenchReport.BEATS_FP32, 4, false, missing, downbeat, beat, downbeat,
            wantBeats, wantDownbeats, fps = 50, gates = gates)
        assertEquals(8f, fp32.logitsMaxAbs, 0f)
        assertFalse(fp32.pass(gates))

        val early = BeatParity.of("short", BenchReport.BEATS_FP16, 4, false, beat, downbeat, beat, downbeat,
            listOf(1.0, 2.0), listOf(1.0), fps = 50, gates = gates)
        assertNull("no reference beat after the trim: no F, never a pass for nothing", early.beatsF)
        assertFalse(early.pass(gates))
    }

    @Test fun theReportSaysTheDeviceTheRuntimeAndParityAndNothingElseOfThePhone() {
        val classes = OrtModels.CLASSES
        val want = FloatArray(classes).also { it[3] = 1f }
        val parity = Parity(gates, listOf(BtcParity.of("steady", 4, false, want.copyOf(), want,
            BtcParity.margins(want, 1), 1)), emptyList())
        val out = report(listOf(run()), parity)
        assertEquals(setOf("bench", "made", "device", "soc", "android", "runtime", "app", "runs", "summary", "parity"),
            out.keys)
        assertEquals(BenchReport.FORMAT, out.getValue("bench").jsonPrimitive.int)
        assertEquals("2026-11-25T21:00:00Z", out.str("made"))
        assertEquals("Sony XQ-DQ72", out.str("device"))
        assertEquals("QTI SM8550", out.str("soc"))
        assertEquals("14 (API 34)", out.str("android"))
        assertEquals(OrtModels.RUNTIME, out.str("runtime"))
        assertEquals("onnxruntime 1.32.0", out.str("runtime"))
        val p = out.getValue("parity").jsonObject
        assertTrue(p.getValue("pass").jsonPrimitive.boolean)
        assertEquals(1e-3, p.getValue("gates").jsonObject.num("btc_margin_under"), 0.0)
        val btc = p.getValue("btc").jsonArray.single().jsonObject
        assertEquals(1.0, btc.num("agreement"), 0.0)
        assertEquals(0, btc.getValue("differ_over_margin").jsonPrimitive.int)
        assertTrue(btc.getValue("pass").jsonPrimitive.boolean)
        assertEquals(JsonArray(emptyList()), p.getValue("beats"))
        // An empty bench passes nothing.
        assertFalse(report(emptyList()).getValue("parity").jsonObject.getValue("pass").jsonPrimitive.boolean)
    }

    private fun JsonObject.str(key: String) = getValue(key).jsonPrimitive.content
    private fun JsonObject.num(key: String) = getValue(key).jsonPrimitive.double
}
