package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.testing.FrontendRecords
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** [Mel] against beat_this's log-mel of the committed clips (vectors/autochords/frontend.jsonl, stored as float16),
 * the design's B1 feature gate. */
class MelTest {
    @Test
    fun `every clip's log-mel meets the feature gate`() {
        val gate = FrontendRecords.gate
        val clips = FrontendRecords.sources.filter { it.mel != null }
        assertEquals(4, clips.size)
        for (clip in clips) {
            val score = FrontendRecords.mel(clip)
            println("MelTest: $score")
            assertTrue(score.passes(gate), "$score")
            assertTrue(score.silent > 0 || clip.name != "silence", "silence.wav's silence is silent")
        }
    }

    @Test
    fun `a log-mel made a chunk at a time is the whole signal's bit for bit`() {
        // long.wav's 40 s: chunks of 1500 frames and an odd one, the first and last frames reflected at the ends.
        val y = FrontendRecords.sources.first { it.name == "long" }.samples
        val whole = Mel.logMel(y)
        val frames = Mel.frames(y.size)
        for (chunk in listOf(1500, 333)) {
            val pieced = FloatArray(whole.size)
            var at = 0
            while (at < frames) {
                val until = minOf(frames, at + chunk)
                Mel.logMel(y.size, { y[it] }, at, until).copyInto(pieced, at * Mel.MELS)
                at = until
            }
            assertTrue(whole.contentEquals(pieced), "in chunks of $chunk frames")
        }
    }

    @Test
    fun `a frame a hop, centred`() {
        for (n in listOf(Mel.N_FFT / 2 + 1, 441 * 3, 441 * 3 + 440, 22050)) {
            assertEquals((1 + n / Mel.HOP) * Mel.MELS, Mel.logMel(FloatArray(n)).size, "$n samples")
        }
    }

    @Test
    fun `audio no longer than half a window is refused, as torch's reflect padding refuses it`() {
        assertFailsWith<IllegalArgumentException> { Mel.logMel(FloatArray(Mel.N_FFT / 2)) }
    }
}
