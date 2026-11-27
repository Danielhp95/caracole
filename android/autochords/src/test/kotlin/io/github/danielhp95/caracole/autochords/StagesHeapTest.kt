package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.frontend.Soxr
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * [Stages] hold no song whole: a song of [SECONDS] at 48 kHz mono (as the decoder and the mixdown leave it, a file)
 * resampled, its chords and its beats heard (the graphs faked: [Zeros]), in a JVM of its own whose heap ([HEAP_MB]) is
 * smaller than the song's samples and their resampled copy, which the old one-call pipeline held at once: that one
 * (`whole`, its control) runs out of memory there; the stages don't.
 */
class StagesHeapTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test(timeout = 300_000)
    fun `a song longer than the heap is heard, where holding it whole runs out of memory`() {
        val mono = tmp.newFile("mono.f32")
        write48k(mono)
        assertTrue(mono.length() > HEAP_MB * 1024L * 1024, "the song is ${mono.length() / 1024 / 1024} MB")
        val whole = child("whole", mono)
        assertTrue(whole.second.contains("OutOfMemoryError"), "the control: ${whole.second}")
        val streamed = child("stages", mono)
        assertEquals(0, streamed.first, streamed.second)
        assertTrue(streamed.second.contains("heard"), streamed.second)
        // BTC heard the whole song: its last chord ends at its end, 900 s, to a frame.
        assertTrue(Regex("to (899|900)\\.\\d+ s").containsMatchIn(streamed.second), streamed.second)
        println("StagesHeapTest: ${streamed.second.trim()}")
    }

    private fun write48k(file: File) {
        val block = ByteBuffer.allocate(4 * 48000).order(ByteOrder.LITTLE_ENDIAN)
        file.outputStream().buffered().use { out ->
            for (s in 0 until SECONDS) {
                block.clear()
                for (i in 0 until 48000) block.putFloat((0.3 * sin(2 * PI * 220.0 * (s * 48000 + i) / 48000)).toFloat())
                out.write(block.array())
            }
        }
    }

    /** `StagesHeapMain MODE MONO WORK` in a JVM of [HEAP_MB]: its exit status and its output. */
    private fun child(mode: String, mono: File): Pair<Int, String> {
        val java = File(System.getProperty("java.home"), "bin/java").path
        val process = ProcessBuilder(java, "-Xmx${HEAP_MB}m", "-cp", System.getProperty("java.class.path"),
            "-Djava.library.path=${System.getProperty("java.library.path")}",
            "io.github.danielhp95.caracole.autochords.StagesHeapMain", mode, mono.path, tmp.newFolder().path)
            .redirectErrorStream(true).start()
        val out = process.inputStream.readBytes().toString(Charsets.UTF_8)
        return process.waitFor() to out
    }

    companion object {
        const val SECONDS = 900
        const val HEAP_MB = 40
    }
}

/** The graphs' answers, zeros: nothing of a model's memory, the stages' alone. */
private object Zeros : ChordsGraph, BeatsGraph {
    override val padding = 0f
    override fun chords(features: FloatArray, windows: Int) = FloatArray(windows * Stages.WINDOW * Stages.CLASSES)
    override fun beats(spect: FloatArray, frames: Int) = FloatArray(frames) to FloatArray(frames)
    override fun close() {}
}

/** StagesHeapTest's child: `whole` resamples as the old pipeline did (the song and its copy in arrays at once);
 * `stages` hears it through [Stages]. */
object StagesHeapMain {
    @JvmStatic fun main(args: Array<String>) {
        val (mode, path, work) = args
        val mono = File(path)
        val pcm = File(work, "pcm.f32")
        val started = System.nanoTime()
        if (mode == "whole") {
            val b = Stages.mapped(mono) { FloatArray(it.remaining()).also { a -> it.get(a) } }
            println("resampled ${Soxr.resample(b, 48000.0, Stages.RATE.toDouble()).size}")
            return
        }
        val n = Stages.resample(mono, 48000, pcm)
        val chords = Stages.chords(pcm, Stages.btcSamples(mono.length() / 4, 48000), Zeros)
        val (beats, _) = Stages.beats(pcm, Zeros)
        val rt = Runtime.getRuntime()
        println("heard ${mono.length() / 4} samples at 48 kHz, $n at 22,050 Hz: ${chords.size} chords to " +
            "${chords.last().end} s, ${beats.size} beats, in ${(System.nanoTime() - started) / 1_000_000} ms, " +
            "the heap at most ${rt.maxMemory() / 1024 / 1024} MB")
    }
}
