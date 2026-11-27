package io.github.danielhp95.caracole.autochords

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * beat_this's minimal postprocessor (`beat_this.model.postprocessor.Postprocessor(type="minimal")`, as File2Beats runs
 * it with `dbn=False`): a frame is a peak where its logit is the largest within 3 frames either side (`max_pool1d(7,
 * 1, 3)`) and above 0; a run of adjacent peaks becomes its mean (`deduplicate_peaks(width=1)`, the mean updated as
 * Python updates it); frames become seconds at [FPS]; each downbeat moves to its nearest beat (the first of two as
 * near), and the downbeats are sorted, each once.
 */
object Peaks {
    /** beat_this's frames a second (Postprocessor's `fps`). */
    const val FPS = 50

    /** The beats and downbeats, in seconds, of a piece's [beat] and [downbeat] logits, one a frame. */
    fun of(beat: FloatArray, downbeat: FloatArray): Pair<List<Double>, List<Double>> {
        val beats = deduplicated(maxima(beat)).map { it / FPS }
        val moved = deduplicated(maxima(downbeat)).map { it / FPS }.map { d ->
            if (beats.isEmpty()) d else {
                var nearest = 0
                for (i in 1 until beats.size) if (abs(beats[i] - d) < abs(beats[nearest] - d)) nearest = i
                beats[nearest]
            }
        }
        val downbeats = ArrayList<Double>()
        for (d in moved.sorted()) if (downbeats.isEmpty() || downbeats.last() != d) downbeats += d
        return beats to downbeats
    }

    /** The frames whose logit equals the largest within 3 frames either side and is above 0. */
    private fun maxima(logits: FloatArray): List<Int> = logits.indices.filter { t ->
        var most = Float.NEGATIVE_INFINITY
        for (u in max(0, t - 3)..min(logits.size - 1, t + 3)) most = max(most, logits[u])
        logits[t] == most && logits[t] > 0f
    }

    /** `deduplicate_peaks(width=1)`: peaks each at most a frame from the one before, their running mean. */
    private fun deduplicated(frames: List<Int>): List<Double> {
        if (frames.isEmpty()) return emptyList()
        val out = ArrayList<Double>()
        var p = frames[0].toDouble()
        var c = 1
        for (k in 1 until frames.size) {
            val p2 = frames[k]
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
}
