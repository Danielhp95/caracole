package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.Chunks
import io.github.danielhp95.caracole.autochords.Peaks
import io.github.danielhp95.caracole.autochords.Scores

/**
 * What ModelParityTest and the debug build's Chords bench ([Bench]) need around beat_this's graph to read the
 * computer's records, each :autochords' port (held to beat_this and mir_eval by the corpus, vectors/autochords/
 * chunks, peaks and scores.jsonl): the piece cut into chunks and the logits put together again ([logits],
 * [Chunks.split] and [Chunks.aggregate]), the minimal postprocessor ([peaks], [Peaks.of]) and the beats' F-measure
 * ([fMeasure], [Scores.beatF]; [trimmed], [Scores.trimBeats]). No copy of them is kept here.
 */
internal object BeatThis {
    /** The beat and downbeat logits of a log-mel of [frames] × [bins], chunk by chunk through [model] (a chunk's
     * spectrogram and its frames to its two logits). */
    fun logits(spect: FloatArray, frames: Int, bins: Int, chunk: Int, border: Int,
               model: (FloatArray, Int) -> Pair<FloatArray, FloatArray>): Pair<FloatArray, FloatArray> {
        require(spect.size == frames * bins)
        val chunks = Chunks.split(frames, chunk, border)
        val beats = ArrayList<FloatArray>(chunks.size)
        val downbeats = ArrayList<FloatArray>(chunks.size)
        for (c in chunks) {
            val piece = FloatArray(c.length * bins)
            System.arraycopy(spect, c.from * bins, piece, c.left * bins, (c.to - c.from) * bins)
            val (b, d) = model(piece, c.length)
            check(b.size == c.length && d.size == c.length)
            beats += b
            downbeats += d
        }
        val starts = chunks.map { it.start }
        return Chunks.aggregate(beats, starts, frames, chunk, border) to
            Chunks.aggregate(downbeats, starts, frames, chunk, border)
    }

    /** The beats and downbeats, in seconds, of a piece's logits at [fps] frames a second: beat_this's own, 50. */
    fun peaks(beat: FloatArray, downbeat: FloatArray, fps: Int): Pair<List<Double>, List<Double>> {
        require(fps == Peaks.FPS) { "beat_this's postprocessor runs at ${Peaks.FPS} frames a second, not $fps" }
        return Peaks.of(beat, downbeat)
    }

    /** `trim_beats`: the beats at [trim] seconds or after. */
    fun trimmed(beats: List<Double>, trim: Double): List<Double> = Scores.trimBeats(beats, trim)

    /** `mir_eval.beat.f_measure` within [window] seconds, 0 for an empty side. */
    fun fMeasure(reference: List<Double>, estimated: List<Double>, window: Double): Double =
        Scores.beatF(reference, estimated, window)
}
