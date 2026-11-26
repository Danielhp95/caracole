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
                    rss: Long? = 400_000, battery: Pair<Long?, Long?> = 1_000_000L to 990_000L,
                    kind: String = BenchInput.REFERENCE, reset: Boolean = true) =
        Run(file = file, kind = kind, model = model, pass = pass, threads = 4, arena = false, screen = screen,
            cold = cold, nanos = (seconds * 1e9).toLong(), duration = duration, samples = samples, reset = reset,
            rssPeakKb = rss, batteryStartUah = battery.first, batteryEndUah = battery.second)

    private val gates = Gates(btcMarginUnder = 1e-3, btcLogitsMaxAbs = 1e-4, fp32LogitsMaxAbs = 1e-3,
        fp16FMin = 0.99, trim = 5.0, window = 0.07)

    private fun report(runs: List<Run>, parity: Parity = Parity(gates, emptyList(), emptyList()),
                       sessions: List<Session> = emptyList(), battery: Battery? = null) =
        BenchReport.of(runs, parity, device, made = "2026-11-25T21:00:00Z", sessions = sessions, battery = battery)

    private fun summary(out: JsonObject, kind: String) =
        out.getValue("summary").jsonObject.getValue(kind).jsonArray.map { it.jsonObject }

    @Test fun aRunsRtfIsItsSecondsOverTheAudiosAndItsPeaksTheLargestSamples() {
        val samples = listOf(Sample(100_000, "none", 0.31f), Sample(300_000, "none", 0.52f),
            Sample(null, "light", null), Sample(200_000, "none", 0.47f))
        val out = report(listOf(run(samples = samples))).getValue("runs").jsonArray.single().jsonObject
        assertEquals("steady", out.str("file"))
        assertEquals(BenchInput.REFERENCE, out.str("kind"))
        assertTrue(out.getValue("reset").jsonPrimitive.boolean)
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
        val summary = summary(report(runs), "references")
        assertEquals(2, summary.size)
        val on = summary.first { it.str("screen") == "on" }
        assertEquals(BenchReport.BEATS_FP16, on.str("model"))
        assertEquals(3, on.getValue("runs").jsonPrimitive.int)
        assertEquals(0.15, on.num("rtf_median"), 1e-9)
        assertEquals(0.2, on.num("rtf_max"), 1e-9)
        assertEquals("the warm runs' steady peak", 1171.9, on.num("rss_steady_mb"), 0.0)
        assertFalse("0.2 > 0.125", on.getValue("speed_ok").jsonPrimitive.boolean)
        assertEquals("no session measured: no hearing's peak, no verdict", JsonNull, on.getValue("memory_ok"))
        val off = summary.first { it.str("screen") == "off" }
        assertEquals(1, off.getValue("runs").jsonPrimitive.int)
        assertTrue(off.getValue("speed_ok").jsonPrimitive.boolean)
    }

    @Test fun gateB0sSummaryIsTheReferencesAloneAndTheClipsAreApart() {
        val runs = listOf(
            run(file = "song", model = BenchReport.BEATS_FP16, seconds = 24.0, duration = 240.0),  // RTF 0.1
            run(file = "song", model = BenchReport.BEATS_FP16, pass = 2, seconds = 26.4, duration = 240.0),
            // A clip's chunk overhead: RTF 0.4, which must not be the gate's.
            run(file = "silence", model = BenchReport.BEATS_FP16, seconds = 4.0, duration = 10.0,
                kind = BenchInput.CLIP),
        )
        val out = report(runs)
        val songs = summary(out, "references").single()
        assertEquals(2, songs.getValue("runs").jsonPrimitive.int)
        assertEquals(0.11, songs.num("rtf_max"), 1e-9)
        assertTrue(songs.getValue("speed_ok").jsonPrimitive.boolean)
        val clips = summary(out, "clips").single()
        assertEquals(0.4, clips.num("rtf_max"), 1e-9)
        assertFalse("the clips' block has no gate", "speed_ok" in clips || "memory_ok" in clips)
    }

    @Test fun aPeakWhoseResetDidntTakeIsNoNumber() {
        val runs = listOf(
            run(model = BenchReport.BEATS_FP16, pass = 2, rss = 1_700_000, reset = false),  // another session's?
            run(model = BenchReport.BEATS_FP16, pass = 3, rss = 800_000),
        )
        val out = report(runs)
        val first = out.getValue("runs").jsonArray[0].jsonObject
        assertFalse(first.getValue("reset").jsonPrimitive.boolean)
        assertEquals(JsonNull, first.getValue("rss_peak_mb"))
        val songs = summary(out, "references").single()
        assertEquals("the reset runs' peak alone (781.25, half to even)", 781.2, songs.num("rss_steady_mb"), 0.0)
        // None reset: no steady peak.
        val none = summary(report(listOf(run(model = BenchReport.BEATS_FP16, pass = 2, reset = false))),
            "references").single()
        assertEquals(JsonNull, none.getValue("rss_steady_mb"))
    }

    private fun session(peak: Long?, fresh: Boolean = true, round: String = "on", pid: Int? = 4242,
                        failure: String? = null, stopped: String? = null, complete: Boolean = true,
                        outOfMemory: Boolean = false) =
        Session(BenchReport.BEATS_FP16, 4, false, round, 0.7, peak, null, null, failure, stopped, pid = pid,
            fresh = fresh, complete = complete, outOfMemory = outOfMemory)

    @Test fun aSessionThatDidntFinishItsHearingGivesNoMemoryVerdictAndOneOutOfMemoryAFalseOne() {
        val warm = listOf(run(model = BenchReport.BEATS_FP16, pass = 2, rss = 800_000))
        fun gated(vararg sessions: Session) = summary(report(warm, sessions = sessions.toList()), "references").single()
        for (unfinished in listOf(
            session(900_000, failure = "OrtException: some error", complete = false),
            session(900_000, stopped = "stopped by the owner (Stop)", complete = false),
            session(900_000, stopped = "the phone's thermal status reached critical", complete = false),
            session(900_000, complete = false),
        )) {
            val g = gated(session(900_000), unfinished)
            assertEquals(unfinished.toString(), JsonNull, g.getValue("memory_ok"))
            assertEquals(JsonNull, g.getValue("rss_hearing_mb"))
            assertTrue(g.str("memory_note"), g.str("memory_note").contains("sessions[].failure"))
        }
        // Out of memory, said by the runtime or by Android: false, whatever the peak read before it.
        val oom = gated(session(900_000), session(700_000, failure = "OutOfMemoryError: …", complete = false,
            outOfMemory = true))
        assertFalse(oom.getValue("memory_ok").jsonPrimitive.boolean)
        assertTrue(oom.str("memory_note").contains("out of memory"))
        val notFresh = gated(session(900_000, fresh = false))
        assertTrue(notFresh.str("memory_note").contains("fresh"))
        assertEquals(JsonNull, gated(session(900_000)).let { it["memory_note"] ?: JsonNull })
        val gates = report(warm).getValue("summary").jsonObject.getValue("gates").jsonObject
        assertEquals(1024.0, gates.num("memory_mb"), 0.0)
        assertEquals(0.125, gates.num("rtf_max"), 0.0)
    }

    @Test fun gateB0sMemoryIsAHearingsWholePeakItsLoadAndColdRunIn() {
        val warm = listOf(run(model = BenchReport.BEATS_FP16, pass = 2, rss = 800_000),
            run(model = BenchReport.BEATS_FP16, pass = 3, rss = 810_000))
        // The load and the first inference peaked at 1.2 GB; the warm runs stayed at 0.8.
        val over = summary(report(warm, sessions = listOf(session(1_200_000))), "references").single()
        assertEquals(1171.9, over.num("rss_hearing_mb"), 0.0)
        assertEquals(791.0, over.num("rss_steady_mb"), 0.0)
        assertFalse("the load's peak is the hearing's", over.getValue("memory_ok").jsonPrimitive.boolean)
        val under = summary(report(warm, sessions = listOf(session(900_000))), "references").single()
        assertTrue(under.getValue("memory_ok").jsonPrimitive.boolean)
        // A session whose process may not have been fresh, or that gave no peak: no verdict, never a pass.
        for (doubt in listOf(session(900_000, fresh = false), session(null))) {
            val unsure = summary(report(warm, sessions = listOf(session(900_000), doubt)), "references").single()
            assertEquals(doubt.toString(), JsonNull, unsure.getValue("rss_hearing_mb"))
            assertEquals(doubt.toString(), JsonNull, unsure.getValue("memory_ok"))
        }
        // Another round's session is not this group's.
        val other = summary(report(warm, sessions = listOf(session(900_000), session(2_000_000, round = "off"))),
            "references").single()
        assertTrue(other.getValue("memory_ok").jsonPrimitive.boolean)
        val shown = report(warm, sessions = listOf(session(900_000, fresh = false, pid = 77)))
            .getValue("sessions").jsonArray.single().jsonObject
        assertEquals(77, shown.getValue("pid").jsonPrimitive.int)
        assertFalse(shown.getValue("fresh").jsonPrimitive.boolean)
    }

    @Test fun aSummaryLeftEmptyByFirstRunsAloneSaysSo() {
        val out = report(listOf(run(cold = true), run(cold = true, kind = BenchInput.CLIP)))
        val summary = out.getValue("summary").jsonObject
        assertTrue(summary.getValue("references").jsonArray.isEmpty())
        assertTrue(summary.str("references_note").contains("first run"))
        assertTrue(summary.str("clips_note").contains("first run"))
        val full = report(listOf(run(pass = 2))).getValue("summary").jsonObject
        assertFalse("references_note" in full)
        assertFalse("no clip run at all: nothing to say", "clips_note" in full)
    }

    @Test fun aLaterSessionsParityThatDiffersFromTheFirstsIsReportedNeverDropped() {
        val first = BtcParity("steady", 4, false, 130, 1.0, emptyList(), 1e-5f)
        val later = BtcParity("steady", 4, false, 130, 0.99, listOf(0.5f), 1e-5f)
        fun result(round: String, btc: BtcParity) = SessionResult(
            Session(BenchReport.BTC, 4, false, round, 0.3, 200_000, null, null, null, null, pid = 1, fresh = true),
            listOf(run(screen = round)), listOf(btc), emptyList())
        val same = BenchReport.ofSessions(listOf(result("on", first), result("off", first)), gates, device, "t")
            .getValue("parity").jsonObject
        assertTrue(same.getValue("differs").jsonArray.isEmpty())
        val out = BenchReport.ofSessions(listOf(result("on", first), result("off", later)), gates, device, "t")
            .getValue("parity").jsonObject
        assertEquals(1, out.getValue("btc").jsonArray.size)
        val differs = out.getValue("differs").jsonArray.single().jsonObject
        assertEquals("steady", differs.str("file"))
        assertEquals(0, differs.getValue("first_session").jsonPrimitive.int)
        assertEquals(1, differs.getValue("session").jsonPrimitive.int)
        assertEquals(0.99, differs.getValue("other").jsonObject.num("agreement"), 0.0)
        assertFalse("a later session's failing parity fails it", out.getValue("pass").jsonPrimitive.boolean)
    }

    @Test fun theSessionsAndTheWholeBatteryAreSaidApart() {
        val sessions = listOf(
            Session(model = BenchReport.BEATS_FP16, threads = 4, arena = true, round = "on", loadSeconds = 1.2346,
                rssPeakKb = 1_640_000, batteryStartUah = 3_000_000, batteryEndUah = 2_950_000, failure = null,
                stopped = null),
            Session(model = BenchReport.BEATS_FP32, threads = 2, arena = false, round = "off", loadSeconds = null,
                rssPeakKb = null, batteryStartUah = null, batteryEndUah = null,
                failure = "the session's process died", stopped = "the phone's thermal status reached critical"),
        )
        val out = report(listOf(run()), sessions = sessions,
            battery = Battery(startUah = 3_000_000, endUah = 2_800_000, startPercent = 90, endPercent = 82,
                plugged = false))
        val (a, b) = out.getValue("sessions").jsonArray.map { it.jsonObject }
        assertEquals(1.235, a.num("load_seconds"), 0.0)
        assertEquals(1601.6, a.num("rss_peak_mb"), 0.0)
        assertEquals(-50_000L, a.getValue("battery_uah").jsonPrimitive.long)
        assertEquals("on", a.str("round"))
        assertEquals(JsonNull, a.getValue("failure"))
        assertEquals("the session's process died", b.str("failure"))
        assertEquals("the phone's thermal status reached critical", b.str("stopped"))
        assertEquals(JsonNull, b.getValue("load_seconds"))
        val battery = out.getValue("battery").jsonObject
        assertEquals(-200_000L, battery.getValue("change_uah").jsonPrimitive.long)
        assertEquals(90, battery.getValue("start_percent").jsonPrimitive.int)
        assertFalse(battery.getValue("plugged").jsonPrimitive.boolean)
    }

    @Test fun aSessionsResultCrossesFromItsProcessUnchanged() {
        val r = run(samples = listOf(Sample(100_000, "none", 0.25f), Sample(null, "light", null)), reset = false,
            battery = null to 5L, kind = BenchInput.CLIP)
        val btc = BtcParity("steady", 4, true, 130, 0.99, listOf(0.0005f), 1.5e-5f)
        val beat = BeatParity("long", BenchReport.BEATS_FP16, 4, true, 0.39f, 1.0, null)
        val session = Session(BenchReport.BEATS_FP16, 4, true, "off", 2.5, 900_000, 1, 2, null, "hot", pid = 99,
            fresh = true, complete = true, outOfMemory = true)
        val sent = SessionResult(session, listOf(r), listOf(btc), listOf(beat), ended = false, nextSeconds = 240.5)
        val back = BenchCodec.decode(BenchCodec.encode(sent))
        assertEquals(sent, back)
        assertEquals(session, back.session)
        assertEquals(listOf(r), back.runs)
        assertEquals(listOf(btc), back.btc)
        assertEquals(listOf(beat), back.beats)
    }

    @Test fun theSessionsReportSaysEachFilesParityOnceUnderEachSetting() {
        val btc = BtcParity("steady", 4, false, 1, 1.0, emptyList(), 0f)
        fun result(round: String) = SessionResult(
            Session(BenchReport.BTC, 4, false, round, 0.3, 200_000, null, null, null, null),
            listOf(run(screen = round)), listOf(btc), emptyList())
        val out = BenchReport.ofSessions(listOf(result("on"), result("off")), gates, device, "2026-11-25T21:00:00Z")
        assertEquals(2, out.getValue("sessions").jsonArray.size)
        assertEquals(2, out.getValue("runs").jsonArray.size)
        assertEquals(1, out.getValue("parity").jsonObject.getValue("btc").jsonArray.size)
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
        assertEquals(setOf("bench", "made", "device", "soc", "android", "runtime", "app", "battery", "sessions", "runs",
            "summary", "parity"), out.keys)
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
