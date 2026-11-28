package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordSegment
import io.github.danielhp95.caracole.autochords.Heard
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Stages
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** [EndToEnd]: B1's gate read from the records' meta, a `hearing` record read as the corpus and a folder write it,
 * one file scored against it and all of them over all. */
class EndToEndTest {
    private val corpus = File(System.getProperty("user.dir"), "../../tests/conformance/vectors/autochords/models.jsonl")
        .readLines().drop(1)

    @Test fun theGatesAreTheRecordsMetasNeverTyped() {
        val g = EndToEnd.Gates.of(corpus.first())
        assertEquals(EndToEnd.Gates(0.99, 0.98, 0.99, 0.07, 5.0), g)
    }

    @Test fun theCorpussHearingRecordsAreReadTheirArgmaxNamingTheirChords() {
        val records = corpus.filter { "\"kind\": \"hearing\"" in it || "\"kind\":\"hearing\"" in it }
        assertEquals(2, records.size)
        for (text in records) {
            val h = EndToEnd.Hearing.read(text)
            assertTrue(h.name, h.name == "hearing.mp3" || h.name == "hearing.m4a")
            assertEquals(h.btcFrames, h.argmax.size)
            assertNull(h.sha256)
            // The computer's argmax names the chords its record states (common names, recognize's).
            assertEquals(h.segments, Labels.recognized(h.harte))
        }
    }

    private val heard = { harte: List<ChordSegment>, beats: List<Double>, duration: Double ->
        Heard(Heard.CONTRACT, duration, Labels.recognized(harte), beats, beats.filterIndexed { i, _ -> i % 4 == 0 })
    }

    @Test fun aHearingAsTheComputersPassesAndOneThatPartsSaysWhere() {
        val frames = 1080
        val argmax = IntArray(frames) { if (it < 540) 2 else 51 }
        val beats = (1..190).map { it * 0.5 }
        val record = """{"kind": "hearing", "file": {"name": "x.mp3", "sha256": "ab"}, "duration": 100.0,
            "btc": {"samples": 2205000, "frames": $frames, "argmax": [[2, 540], [51, 540]], "segments": []},
            "beats": {"frames": 5001, "beats": $beats, "downbeats": ${beats.filterIndexed { i, _ -> i % 4 == 0 }}}}"""
        val h = EndToEnd.Hearing.read(record)
        assertEquals("ab", h.sha256)
        val g = EndToEnd.Gates.of(corpus.first())
        val pcm = Checkpoints.Pcm(100.0, 2205000, 2205000)
        val same = EndToEnd.score(h, h.harte, heard(h.harte, beats, 100.0), pcm, g)
        assertEquals(1.0, same.majmin, 1e-12)
        assertEquals(1.0, same.beatsF!!, 0.0)
        assertEquals(frames, same.btcFrames)
        assertEquals(0, same.differ.count)
        assertTrue(same.failures(g).toString(), same.pass(g))

        // The phone's last tenth another chord, its length a frame longer, half its beats gone.
        val phone = IntArray(frames + 1) { if (it < 972) argmax[it] else 99 }
        val other = Labels.spellForKey(Labels.framesToSegments(phone, Labels.FRAME_SECONDS,
            Labels.vocabulary(Stages.CLASSES)))
        val parted = EndToEnd.score(h, other, heard(other, beats.filterIndexed { i, _ -> i % 2 == 0 }, 100.0),
            Checkpoints.Pcm(100.0, 2205000, 2205100), g)
        assertEquals(frames + 1, parted.btcFrames)
        assertEquals(109, parted.differ.count)
        assertEquals(109, parted.differ.tenths.sum())
        assertTrue(parted.differ.tenths.toString(), parted.differ.tenths.take(8).all { it == 0 })
        assertEquals(Labels.time(972, Labels.FRAME_SECONDS), parted.differ.runs.single().first, 0.0)
        val said = parted.failures(g)
        assertTrue(said.toString(), said.any { it.startsWith("WCSR majmin") })
        assertTrue(said.toString(), said.any { it.startsWith("beats F") })
        assertTrue(said.toString(), "BTC heard ${frames + 1} frames, the computer $frames" in said)
        assertTrue(said.toString(), "BTC read 2205100 samples, the computer 2205000" in said)

        val all = EndToEnd.overAll(listOf(same, parted), g)
        assertFalse(all["pass"]!!.jsonPrimitive.boolean)
        assertEquals((1.0 + parted.beatsF!!) / 2, all["beats_f_mean"]!!.jsonPrimitive.double, 1e-6)
        assertEquals(parted.majmin, all["wcsr_majmin_least"]!!.jsonPrimitive.double, 1e-6)
        assertTrue(EndToEnd.overAll(listOf(same), g)["pass"]!!.jsonPrimitive.boolean)
    }

    private val g = EndToEnd.Gates(0.99, 0.98, 0.99, 0.07, 5.0)

    private fun scored(file: String = "x", duration: Double = 100.0, computerDuration: Double? = duration,
                       mel: Int = 501, majmin: Double = 1.0, beatsF: Double? = 1.0) =
        EndToEnd.Scored(file, majmin, 1.0, beatsF, 1.0, 10, 10, 2205, 2205, mel, 501, duration, computerDuration,
            EndToEnd.Differ(10, 0, List(10) { 0 }, emptyList()))

    @Test fun aReferenceWithNoBeatsAfterTheTrimIsNoPass() {
        val record = """{"kind": "hearing", "file": {"name": "x.mp3"}, "duration": 10.0,
            "btc": {"samples": 220500, "frames": 108, "argmax": [[2, 108]], "segments": []},
            "beats": {"frames": 501, "beats": [1.0, 2.0, 4.5], "downbeats": [1.0]}}"""
        val h = EndToEnd.Hearing.read(record)
        val s = EndToEnd.score(h, h.harte, heard(h.harte, listOf(1.0, 2.0, 4.5), 10.0),
            Checkpoints.Pcm(10.0, 220500, 220500), g)
        assertNull(s.beatsF)
        assertNull(s.downbeatsF)
        assertTrue(s.failures(g).toString(), "no reference beats after 5.0 s" in s.failures(g))
        assertFalse(s.pass(g))
    }

    @Test fun aMelOrADurationThatIsntTheComputersFails() {
        assertEquals(listOf("beat_this read 502 frames, the computer 501"), scored(mel = 502).failures(g))
        assertEquals(listOf("its length 100.0 s, read_audio's 100.5 s"),
            scored(computerDuration = 100.5).failures(g))
        assertTrue(scored(computerDuration = null).pass(g))
    }

    @Test fun overAllOfNoFilesPassesNothingAndItsMeansWeighByLength() {
        val none = EndToEnd.overAll(emptyList(), g)
        assertFalse(none["pass"]!!.jsonPrimitive.boolean)
        assertEquals(kotlinx.serialization.json.JsonNull, none["wcsr_majmin_mean"])
        val all = EndToEnd.overAll(listOf(scored(duration = 300.0, majmin = 1.0),
            scored(duration = 100.0, majmin = 0.96)), g)
        assertEquals(0.99, all["wcsr_majmin_mean"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(0.96, all["wcsr_majmin_least"]!!.jsonPrimitive.double, 0.0)
        assertEquals(400.0, all["seconds"]!!.jsonPrimitive.double, 0.0)
    }
}
