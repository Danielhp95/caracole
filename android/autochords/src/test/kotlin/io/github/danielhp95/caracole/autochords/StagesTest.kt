package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.frontend.Cqt
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.test.Test
import kotlin.test.assertEquals

/** What each model reads of a resampled song: BTC librosa's `fix_length` of it, beat_this soxr's own length. */
class StagesTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun f32(file: File, samples: FloatArray) = file.apply {
        val b = ByteBuffer.allocate(4 * samples.size).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach { b.putFloat(it) }
        writeBytes(b.array())
    }

    @Test
    fun `BTC reads librosa's length, ceil of n times the ratio, where soxr gives a sample fewer`() {
        // 1,234,567 samples at 48 kHz: soxr's 567,129, librosa's 567,130.
        val mono = f32(tmp.newFile(), FloatArray(1_234_567) { ((it % 97) - 48) / 100f })
        val pcm = tmp.newFile()
        assertEquals(567_129L, Stages.resample(mono, 48000, pcm))
        assertEquals(567_130L, Stages.btcSamples(1_234_567, 48000))
        assertEquals(1_234_567L, Stages.btcSamples(1_234_567, Stages.RATE))
        assertEquals(66_150L, Stages.btcSamples(144_000, 48000))
    }

    @Test
    fun `past soxr's last sample BTC reads zeros, as librosa pads`() {
        // A tail of a hop and some samples after a whole chunk; read 600 samples past the file's end.
        val n = Cqt.CHUNK + Cqt.MIN_AUDIO + 7
        val samples = FloatArray(n) { ((it % 31) - 15) / 40f }
        val pcm = f32(tmp.newFile(), samples)
        val seen = ArrayList<Float>()
        val graph = object : ChordsGraph {
            override val padding = 0f
            override fun chords(features: FloatArray, windows: Int): FloatArray {
                features.forEach { seen += it }
                return FloatArray(windows * Stages.WINDOW * Stages.CLASSES)
            }
            override fun close() {}
        }
        Stages.chords(pcm, n + 600L, graph)
        val padded = samples.copyOf(n + 600)
        val want = Cqt.logFeatures(padded.copyOfRange(0, Cqt.CHUNK)) +
            Cqt.logFeatures(padded.copyOfRange(Cqt.CHUNK, n + 600))
        assertEquals(want.toList(), seen.subList(0, want.size))
        // And with one sample fewer than the file, BTC reads it cut, as librosa cuts.
        seen.clear()
        Stages.chords(pcm, n - 1L, graph)
        val cut = Cqt.logFeatures(samples.copyOfRange(0, Cqt.CHUNK)) +
            Cqt.logFeatures(samples.copyOfRange(Cqt.CHUNK, n - 1))
        assertEquals(cut.toList(), seen.subList(0, cut.size))
    }
}
