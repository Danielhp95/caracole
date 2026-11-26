package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.testing.AutochordsReplay
import io.github.danielhp95.caracole.autochords.testing.FrontendRecords
import io.github.danielhp95.caracole.core.testing.Misses
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** [Cqt] against btc.py's log-CQT of the committed clips and excerpts (vectors/autochords/frontend.jsonl), the
 * design's B1 feature gate; and the pieces it stands on: [Fft], and [Stft]'s padding as numpy's. */
class CqtTest {
    @Test
    fun `every clip's and excerpt's log-CQT meets the feature gate`() {
        val gate = FrontendRecords.gate
        val sources = FrontendRecords.sources
        assertEquals(4 + 3, sources.size, "the four clips and three excerpts")
        for (source in sources) {
            val score = FrontendRecords.cqt(source)
            println("CqtTest: $score")
            assertTrue(score.passes(gate), "$score")
        }
    }

    @Test
    fun `the area replays whole`() {
        val misses = Misses(AutochordsReplay.area)
        AutochordsReplay.report = {}
        try {
            AutochordsReplay.replay(misses)
        } finally {
            AutochordsReplay.report = { println(it) }
        }
        misses.assertNone()
    }

    @Test
    fun `audio shorter than one hop is refused, as btc_py refuses it`() {
        assertFailsWith<IllegalArgumentException> { Cqt.logFeatures(FloatArray(Cqt.HOP - 1)) }
        assertEquals(2 * Cqt.BINS, Cqt.logFeatures(FloatArray(Cqt.HOP)).size)
    }

    @Test
    fun `a tail under a hop after the last whole chunk is left out, and a hop's is a chunk of its own`() {
        val long = FrontendRecords.sources.first { it.name == "long" }.samples
        val chunk = Cqt.CHUNK
        val whole = Cqt.logFeatures(long.copyOfRange(0, chunk))
        assertContentEquals(whole, Cqt.logFeatures(long.copyOfRange(0, chunk + Cqt.HOP - 1)))
        val tail = Cqt.logFeatures(long.copyOfRange(chunk, chunk + Cqt.HOP))
        assertContentEquals(whole + tail, Cqt.logFeatures(long.copyOfRange(0, chunk + Cqt.HOP)))
    }

    @Test
    fun `the FFT of real samples is their DFT`() {
        val random = Random(7)
        for (n in listOf(2, 4, 8, 64, 512, 1024)) {
            val x = DoubleArray(n) { random.nextDouble(-1.0, 1.0) }
            val re = DoubleArray(n / 2 + 1)
            val im = DoubleArray(n / 2 + 1)
            Fft(n).real(x, re, im)
            for (k in 0..n / 2) {
                var wantRe = 0.0
                var wantIm = 0.0
                for (t in 0 until n) {
                    wantRe += x[t] * cos(2 * PI * k * t / n)
                    wantIm -= x[t] * sin(2 * PI * k * t / n)
                }
                assertTrue(abs(re[k] - wantRe) < 1e-9 && abs(im[k] - wantIm) < 1e-9, "n=$n bin $k")
            }
        }
    }

    @Test
    fun `reflect padding is numpy's, past the signal's length too`() {
        // np.pad([0., 1., 2.], (5, 5), mode="reflect")
        val want = floatArrayOf(1f, 0f, 1f, 2f, 1f, 0f, 1f, 2f, 1f, 0f, 1f, 2f, 1f)
        assertContentEquals(want, Stft.reflectPad(floatArrayOf(0f, 1f, 2f), 0, 3, 5, 5))
        assertContentEquals(floatArrayOf(7f, 7f, 7f), Stft.reflectPad(floatArrayOf(7f), 0, 1, 1, 1))
    }
}
