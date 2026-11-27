package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.BeatsGraph
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordsGraph
import io.github.danielhp95.caracole.autochords.Stages
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin

/** [Pipeline]'s checkpoints on the JVM, a 22,050 Hz WAV (no codec, no resampler) through graphs that count their
 * stages: what is whole is never heard again, what won't parse or is cut short is made again. */
class PipelineCheckpointsTest {
    @get:Rule val tmp = TemporaryFolder()

    private class Counted : Pipeline.Graphs {
        var chords = 0
        var beats = 0
        override fun chords(threads: Int): ChordsGraph {
            chords++
            return object : ChordsGraph {
                override val padding = 0f
                override fun chords(features: FloatArray, windows: Int) =
                    FloatArray(windows * Stages.WINDOW * Stages.CLASSES).also {
                        for (i in it.indices step Stages.CLASSES) it[i + 1] = 1f
                    }
                override fun close() {}
            }
        }
        override fun beats(threads: Int): BeatsGraph {
            beats++
            return object : BeatsGraph {
                override fun beats(spect: FloatArray, frames: Int) =
                    FloatArray(frames) { if (it % 25 == 12) 5f else -5f } to FloatArray(frames) { -5f }
                override fun close() {}
            }
        }
    }

    private val cool = HeatGauge { Heat.Reading("none", null, null, 80, true, false) }

    private fun wav(seconds: Int): File {
        val n = 22050 * seconds
        val b = ByteBuffer.allocate(44 + 2 * n).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(36 + 2 * n).put("WAVE".toByteArray()).put("fmt ".toByteArray())
        b.putInt(16).putShort(1).putShort(1).putInt(22050).putInt(44100).putShort(2).putShort(16)
        b.put("data".toByteArray()).putInt(2 * n)
        for (i in 0 until n) b.putShort((8000 * sin(2 * PI * 220 * i / 22050)).toInt().toShort())
        return tmp.newFile("a.wav").apply { writeBytes(b.array()) }
    }

    @Test fun theStagesAreHeardOnceThePcmGoesWithTheBeatsAndWhatWontParseIsMadeAgain() {
        val audio = wav(12)
        val work = tmp.newFolder("work")
        val graphs = Counted()
        val pipeline = Pipeline(File("no-models"), cool, graphs = graphs)
        val first = pipeline.hear(audio, work) {}
        assertEquals(1 to 1, graphs.chords to graphs.beats)
        assertEquals(12.0, first.heard.duration, 0.0)
        val points = first.points
        assertFalse("the samples go once the beats are kept", points.has(Checkpoints.PCM))
        assertTrue(points.has(Checkpoints.PCM_META))
        assertEquals(first.heard, pipeline.hear(audio, work) {}.heard)
        assertEquals(1 to 1, graphs.chords to graphs.beats)

        // An empty heard.json (a power cut after its rename): made again from the chords and beats kept, no model.
        points.file(Checkpoints.HEARD).writeText("")
        assertEquals(first.heard, pipeline.hear(audio, work) {}.heard)
        assertEquals(1 to 1, graphs.chords to graphs.beats)

        // A cut chords.json and no heard.json: the pcm decoded again for BTC alone.
        points.delete(Checkpoints.HEARD)
        points.file(Checkpoints.CHORDS).writeText("{\"harte\":[[0.0,")
        val steps = mutableListOf<String>()
        assertEquals(first.heard, pipeline.hear(audio, work) { steps += it }.heard)
        assertEquals(2 to 1, graphs.chords to graphs.beats)
        assertEquals(listOf(Pipeline.STEPS[0], Pipeline.STEPS[1]), steps)
    }

    @Test fun aPcmShorterThanItsMetaIsDecodedAgainNeverHeardCut() {
        val audio = wav(12)
        val work = tmp.newFolder("work")
        val pipeline = Pipeline(File("no-models"), cool, graphs = Counted())
        val points = Checkpoints.of(work, audio)
        val meta = pipeline.pcm(audio, points)
        assertEquals(12L * 22050, meta.samples)
        assertEquals(meta.samples, meta.btcSamples)
        val pcm = points.file(Checkpoints.PCM)
        pcm.writeBytes(pcm.readBytes().copyOf(4 * 22050))  // a power cut: a short file under its name
        assertFalse(points.pcmWhole(meta))
        val heard = pipeline.hear(audio, work) {}.heard
        assertEquals(Pipeline(File("no-models"), cool, graphs = Counted()).hear(wav2(audio), tmp.newFolder()) {}.heard,
            heard)
    }

    /** A copy of [audio] under another name: the same samples, a folder of its own. */
    private fun wav2(audio: File) = File(tmp.root, "b.wav").apply { writeBytes(audio.readBytes()) }

    @Test fun aCancelStopsTheHearingAtItsNextChunk() {
        val audio = wav(12)
        var stop = false
        val graphs = Counted()
        val pipeline = Pipeline(File("no-models"), cool, graphs = graphs, cancelled = { stop })
        assertThrows(Pipeline.Cancelled::class.java) {
            pipeline.hear(audio, tmp.newFolder()) { if (it == Pipeline.STEPS[1]) stop = true }
        }
        assertEquals(0, graphs.chords)
    }

    @Test fun theStagesShapesAreTheModelsOwn() {
        assertEquals(OrtModels.WINDOW, Stages.WINDOW)
        assertEquals(OrtModels.CLASSES, Stages.CLASSES)
        assertEquals(OrtModels.RUNTIME.isNotEmpty(), true)
    }
}
