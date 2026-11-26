package io.github.danielhp95.caracole.ml

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * What ModelParityTest and the debug build's Chords bench ([Bench]) need around beat_this's graph to read the
 * computer's records, ported from the Python it ran (beat_this 1.1.0, mir_eval 0.8.2): the piece cut into chunks and
 * the logits put together again ([logits], `inference.split_predict_aggregate` with `avoid_short_end` and
 * `keep_first`, as `Spect2Frames` runs it), the minimal postprocessor ([peaks], `Postprocessor(type="minimal")`) and
 * the beats' F-measure ([fMeasure], `mir_eval.beat`'s, after its `trim_beats`). The design's `autochords.Chunks` and
 * `Peaks` (E8) are their ports for the app, held to the corpus on the JVM; these are B0's measuring tools, and
 * ModelParityTest holds [peaks] to the computer's beats over its own logits before either trusts it.
 */
internal object BeatThis {
    /** The beat and downbeat logits of a log-mel of [frames] × [bins], chunk by chunk through [model] (a chunk's
     * spectrogram and its frames to its two logits). */
    fun logits(spect: FloatArray, frames: Int, bins: Int, chunk: Int, border: Int,
               model: (FloatArray, Int) -> Pair<FloatArray, FloatArray>): Pair<FloatArray, FloatArray> {
        require(spect.size == frames * bins)
        val step = chunk - 2 * border
        val starts = (-border until frames - border step step).toMutableList()
        if (frames > step) starts[starts.size - 1] = frames - (chunk - border)
        val beat = FloatArray(frames) { -1000f }
        val downbeat = FloatArray(frames) { -1000f }
        // keep_first: the later chunks first, so an earlier one's frames are written over them.
        for (start in starts.asReversed()) {
            val lo = max(start, 0)
            val hi = min(start + chunk, frames)
            val left = max(0, -start)
            val right = max(0, min(border, start + chunk - frames))
            val length = left + (hi - lo) + right
            val piece = FloatArray(length * bins)
            System.arraycopy(spect, lo * bins, piece, left * bins, (hi - lo) * bins)
            val (b, d) = model(piece, length)
            check(b.size == length && d.size == length)
            val from = start + border
            val until = min(start + chunk - border, frames)
            check(until - from == length - 2 * border) { "a chunk's logits don't fill its place" }
            System.arraycopy(b, border, beat, from, until - from)
            System.arraycopy(d, border, downbeat, from, until - from)
        }
        return beat to downbeat
    }

    /** The beats and downbeats, in seconds, of a piece's logits at [fps] frames a second. */
    fun peaks(beat: FloatArray, downbeat: FloatArray, fps: Int): Pair<List<Double>, List<Double>> {
        val beats = deduplicated(maxima(beat)).map { it / fps }
        val downbeats = deduplicated(maxima(downbeat)).map { it / fps }
            .map { d -> if (beats.isEmpty()) d else beats[beats.indices.minBy { abs(beats[it] - d) }] }
        return beats to downbeats.distinct().sorted()
    }

    /** The frames whose logit is the largest within 3 frames either side (max_pool1d(7, 1, 3)) and above 0. */
    private fun maxima(logits: FloatArray): List<Int> = logits.indices.filter { t ->
        var most = Float.NEGATIVE_INFINITY
        for (u in max(0, t - 3)..min(logits.size - 1, t + 3)) most = max(most, logits[u])
        logits[t] == most && logits[t] > 0f
    }

    /** `deduplicate_peaks(width=1)`: a run of adjacent frames, its mean, as Python updates it. */
    private fun deduplicated(frames: List<Int>): List<Double> {
        if (frames.isEmpty()) return emptyList()
        val out = mutableListOf<Double>()
        var p = frames[0].toDouble()
        var c = 1
        for (p2 in frames.drop(1)) {
            if (p2 - p <= 1) {
                c += 1
                p += (p2 - p) / c
            } else {
                out += p
                p = p2.toDouble()
                c = 1
            }
        }
        out += p
        return out
    }

    /** `trim_beats`: the beats at [trim] seconds or after. */
    fun trimmed(beats: List<Double>, trim: Double): List<Double> = beats.filter { it >= trim }

    /** `mir_eval.beat.f_measure`: the largest matching of reference to estimated beats within [window] seconds, as
     * precision and recall, 0 for an empty side. */
    fun fMeasure(reference: List<Double>, estimated: List<Double>, window: Double): Double {
        if (reference.isEmpty() || estimated.isEmpty()) return 0.0
        // _fast_hit_windows: a reference beat in [est − window, est + window].
        val hits = estimated.map { e ->
            reference.indices.filter { reference[it] >= e - window && reference[it] <= e + window }
        }
        val matchOf = IntArray(reference.size) { -1 }
        fun augment(e: Int, seen: BooleanArray): Boolean {
            for (r in hits[e]) {
                if (seen[r]) continue
                seen[r] = true
                if (matchOf[r] < 0 || augment(matchOf[r], seen)) {
                    matchOf[r] = e
                    return true
                }
            }
            return false
        }
        val matched = estimated.indices.count { augment(it, BooleanArray(reference.size)) }
        val precision = matched.toDouble() / estimated.size
        val recall = matched.toDouble() / reference.size
        if (precision == 0.0 && recall == 0.0) return 0.0
        return 2 * precision * recall / (precision + recall)
    }
}
