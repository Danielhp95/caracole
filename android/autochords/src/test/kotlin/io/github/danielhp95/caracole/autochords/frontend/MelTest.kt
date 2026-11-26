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
