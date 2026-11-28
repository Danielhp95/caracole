package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.BeatsGraph
import io.github.danielhp95.caracole.autochords.ChordsGraph
import io.github.danielhp95.caracole.autochords.Stages
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin

/** A heat waited out before a stage ([HeatRules.cool]) is followed by that stage's own step again, so the client,
 * which shows the last words told (MlChordModels' onStep, the job's running detail), never reads "waiting for the
 * phone to cool" while the stage works. */
class PipelineCoolingWordsTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun wav(seconds: Int): File {
        val n = 22050 * seconds
        val b = ByteBuffer.allocate(44 + 2 * n).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(36 + 2 * n).put("WAVE".toByteArray()).put("fmt ".toByteArray())
        b.putInt(16).putShort(1).putShort(1).putInt(22050).putInt(44100).putShort(2).putShort(16)
        b.put("data".toByteArray()).putInt(2 * n)
        for (i in 0 until n) b.putShort((8000 * sin(2 * PI * 220 * i / 22050)).toInt().toShort())
        return tmp.newFile("a.wav").apply { writeBytes(b.array()) }
    }

    /** What a hearing said, the last words told as each graph ran, and the time it slept. */
    private class Heard(val said: List<String>, val asTheChordsRan: String?, val asTheBeatsRan: String?, val slept: Long)

    /** A hearing of 12 s of a tone whose gauge reads [states] in order, the last one for good. */
    private fun hear(vararg states: String): Heard {
        val audio = wav(12)
        val left = ArrayDeque(states.toList())
        val gauge = HeatGauge {
            Heat.Reading(if (left.size > 1) left.removeFirst() else left.first(), null, null, 80, true, false)
        }
        val said = mutableListOf<String>()
        var chords: String? = null
        var beats: String? = null
        val graphs = object : Pipeline.Graphs {
            override fun chords(threads: Int): ChordsGraph = object : ChordsGraph {
                override val padding = 0f
                override fun chords(features: FloatArray, windows: Int): FloatArray {
                    chords = said.last()
                    return FloatArray(windows * Stages.WINDOW * Stages.CLASSES).also {
                        for (i in it.indices step Stages.CLASSES) it[i + 1] = 1f
                    }
                }
                override fun close() {}
            }
            override fun beats(threads: Int): BeatsGraph = object : BeatsGraph {
                override fun beats(spect: FloatArray, frames: Int): Pair<FloatArray, FloatArray> {
                    beats = said.last()
                    return FloatArray(frames) { if (it % 25 == 12) 5f else -5f } to FloatArray(frames) { -5f }
                }
                override fun close() {}
            }
        }
        var slept = 0L
        Pipeline(File("no-models"), gauge, sleep = { slept += it }, graphs = graphs)
            .hear(audio, tmp.newFolder()) { said += it }
        return Heard(said, chords, beats, slept)
    }

    @Test fun theChordsAreHeardUnderTheirOwnWordsAfterAHeatWaitedOut() {
        // The start's battery check, the pcm stage's (go), the chords stage's: severe once (10 s), then cool.
        val h = hear("none", "none", "severe", "none")
        assertEquals("the heat was waited out once", HeatRules.COOL_POLL_MS, h.slept)
        assertEquals(
            listOf(Pipeline.STEPS[0], Pipeline.STEPS[1], HeatRules.COOLING, Pipeline.STEPS[1], Pipeline.STEPS[2]),
            h.said,
        )
        assertEquals(Pipeline.STEPS[1], h.asTheChordsRan)
        assertEquals(Pipeline.STEPS[2], h.asTheBeatsRan)
    }

    @Test fun thePcmIsMadeUnderTheSetUpsWordsAfterAHeatWaitedOut() {
        // The start's battery check, the pcm stage's: severe once (10 s), then cool for good.
        val h = hear("none", "severe", "none")
        assertEquals("the heat was waited out once", HeatRules.COOL_POLL_MS, h.slept)
        assertEquals(
            listOf(Pipeline.STEPS[0], HeatRules.COOLING, Pipeline.STEPS[0], Pipeline.STEPS[1], Pipeline.STEPS[2]),
            h.said,
        )
        assertEquals(Pipeline.STEPS[1], h.asTheChordsRan)
        assertEquals(Pipeline.STEPS[2], h.asTheBeatsRan)
    }

    @Test fun noWaitTellsEachStepOnce() {
        val h = hear("none")
        assertEquals(0L, h.slept)
        assertEquals(Pipeline.STEPS, h.said)
    }
}
