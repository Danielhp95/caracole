package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.Peaks
import io.github.danielhp95.caracole.autochords.Scores
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** [BeatThis] is :autochords' ports (Chunks, Peaks, Scores) around the graph, which the corpus holds to beat_this
 * and mir_eval: its logits are each chunk's, put together keep_first; its peaks and F are theirs. */
class BeatThisTest {
    @Test
    fun `logits are each chunk's predictions put together, the earlier chunk's kept where two overlap`() {
        val frames = 3000
        val bins = 2
        // The spectrogram's frame f is f + 1 in each bin, so a chunk's model can say which frame each of its own is.
        val spect = FloatArray(frames * bins) { (it / bins + 1).toFloat() }
        var calls = 0
        val (beat, downbeat) = BeatThis.logits(spect, frames, bins, 1500, 6) { piece, length ->
            val k = calls++
            FloatArray(length) { piece[it * bins] + 10000f * k } to FloatArray(length) { -piece[it * bins] }
        }
        assertEquals(3, calls)
        // The chunks run in order (k their index); keep_first: frames 0..1487 chunk 0's, 1488..2975 chunk 1's, the
        // rest chunk 2's (which starts at 1506, so chunk 1's frames over it are kept).
        for (f in 0 until frames) {
            val k = if (f < 1488) 0 else if (f < 2976) 1 else 2
            assertEquals(f + 1 + 10000f * k, beat[f], "frame $f")
            assertEquals(-(f + 1).toFloat(), downbeat[f], "frame $f")
        }
    }

    @Test
    fun `peaks and F are Peaks' and Scores', at beat_this's 50 frames a second alone`() {
        val beat = FloatArray(40) { -2f }.also { it[10] = 1f; it[30] = 1f }
        val downbeat = FloatArray(40) { -2f }.also { it[11] = 1f }
        assertEquals(Peaks.of(beat, downbeat), BeatThis.peaks(beat, downbeat, 50))
        assertFailsWith<IllegalArgumentException> { BeatThis.peaks(beat, downbeat, 100) }
        val ref = listOf(4.0, 5.5, 6.0)
        val est = listOf(4.0, 5.55, 6.2)
        assertEquals(Scores.beatF(Scores.trimBeats(ref), Scores.trimBeats(est)),
                     BeatThis.fMeasure(BeatThis.trimmed(ref, 5.0), BeatThis.trimmed(est, 5.0), 0.07))
        assertContentEquals(listOf(5.5, 6.0), BeatThis.trimmed(ref, 5.0))
    }
}
