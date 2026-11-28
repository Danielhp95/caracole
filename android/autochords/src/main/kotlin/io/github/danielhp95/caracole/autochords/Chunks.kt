package io.github.danielhp95.caracole.autochords

import kotlin.math.max
import kotlin.math.min

/**
 * beat_this's chunking of a long log-mel (`beat_this.inference.split_piece` with `avoid_short_end`, and
 * `aggregate_prediction` with `keep_first`, as `split_predict_aggregate` runs them for Spect2Frames): chunks of [SIZE]
 * frames, overlapping by [BORDER], the first and last padded by it, the last moved back to end at the piece's end;
 * then each chunk's predictions less their borders, an earlier chunk's kept where two overlap.
 */
object Chunks {
    /** Spect2Frames' chunk and border. */
    const val SIZE = 1500
    const val BORDER = 6

    /** One chunk: the piece's frames [from, to) with [left] and [right] frames of zeros either side; [start] its place
     * in the piece (negative for the first, padded). */
    class Chunk(val start: Int, val from: Int, val to: Int, val left: Int, val right: Int) {
        val length: Int get() = left + (to - from) + right
    }

    /** A piece of [frames] frames cut as `split_piece(spect, size, border, avoid_short_end=True)` cuts it. */
    fun split(frames: Int, size: Int = SIZE, border: Int = BORDER): List<Chunk> {
        val step = size - 2 * border
        val starts = (-border until frames - border step step).toMutableList()
        if (frames > step) starts[starts.size - 1] = frames - (size - border)
        return starts.map { start ->
            Chunk(start, max(start, 0), min(start + size, frames), max(0, -start),
                  max(0, min(border, start + size - frames)))
        }
    }

    /** The piece's [frames] predictions from each chunk's ([predictions], by chunk, one a frame of it, at [starts]),
     * as `aggregate_prediction(…, overlap_mode="keep_first")` puts them together: −1000 where no chunk gives one. */
    fun aggregate(predictions: List<FloatArray>, starts: List<Int>, frames: Int, size: Int = SIZE,
                  border: Int = BORDER): FloatArray {
        require(predictions.size == starts.size) { "${predictions.size} chunks' predictions for ${starts.size} starts" }
        val piece = FloatArray(frames) { -1000f }
        // keep_first: the later chunks first, so an earlier one's frames are written over theirs.
        for (k in starts.indices.reversed()) {
            val p = predictions[k]
            val kept = if (border > 0) max(0, p.size - 2 * border) else p.size
            val from = starts[k] + border
            val until = min(starts[k] + size - border, frames)
            require(from >= 0 && until - from == kept) { "chunk $k's ${p.size} predictions don't fill its place" }
            System.arraycopy(p, if (border > 0) border else 0, piece, from, kept)
        }
        return piece
    }
}
