package io.github.danielhp95.caracole.autochords.frontend

import kotlin.math.ceil
import kotlin.math.min

/**
 * Short-time Fourier transforms of float32 samples, centred, in float64, frame by frame: [librosa]'s framing
 * (librosa 1.0's `stft` with `center=True`, which pads only the slices its first and last frames read) and [torch]'s
 * (`torch.stft` with `center=True`, the whole signal padded). Both pad by reflection, as numpy's `pad(mode="reflect")`
 * does ([reflectPad]). Each frame's spectrum goes to `take(frame, re, im)`, its arrays reused for the next.
 */
class Stft(val nFft: Int, val hop: Int) {
    private val fft = Fft(nFft)
    private val frame = DoubleArray(nFft)
    private val re = DoubleArray(nFft / 2 + 1)
    private val im = DoubleArray(nFft / 2 + 1)

    init {
        require(hop > 0) { "a hop over 0" }
    }

    /** librosa 1.0's frames of [y] (`window="ones"`, `pad_mode="reflect"`): the frames that start before the signal
     * from its head's slice padded, those that end past it from its tail's, the rest from [y] itself. The count. */
    fun librosa(y: FloatArray, take: (Int, DoubleArray, DoubleArray) -> Unit): Int {
        val h = nFft / 2
        val startK = ceil(h.toDouble() / hop).toInt()
        val tailK = Math.floorDiv(y.size + h - nFft, hop) + 1
        var index = 0
        fun emit(source: FloatArray, at: Int) {
            for (j in 0 until nFft) frame[j] = source[at + j].toDouble()
            fft.real(frame, re, im)
            take(index++, re, im)
        }
        if (tailK <= startK) {
            val padded = reflectPad(y, 0, y.size, h, h)
            for (f in 0 until frames(padded.size)) emit(padded, f * hop)
            return index
        }
        val start = startK * hop - h
        val preEnd = (startK - 1) * hop - h + nFft + 1
        require(preEnd > 0)
        val pre = reflectPad(y, 0, min(preEnd, y.size), h, 0)
        for (f in 0 until min(startK, frames(pre.size))) emit(pre, f * hop)
        for (f in 0 until frames(y.size - start)) emit(y, start + f * hop)
        if (tailK * hop - h + nFft <= y.size + h) {
            val post = reflectPad(y, tailK * hop - h, y.size, 0, h)
            for (f in 0 until frames(post.size)) emit(post, f * hop)
        }
        return index
    }

    /** torch.stft's frames of [y] times [window] (`pad_mode="reflect"`), as many as `1 + y.size / hop`: reflection
     * needs more samples than half a window, as torch's padding does. The count. */
    fun torch(y: FloatArray, window: FloatArray, take: (Int, DoubleArray, DoubleArray) -> Unit): Int =
        torch(y.size, { y[it] }, window, 0, 1 + y.size / hop, take)

    /** A signal's samples by index, unboxed (a `(Int) -> Float` would box each sample read). */
    fun interface Samples {
        fun at(i: Int): Float
    }

    /** The same frames [from] until [until] of a signal of [n] samples, each sample read by [sample]: frame for
     * frame the whole signal's (each frame's arithmetic its own), so a long signal is framed a chunk at a time. */
    fun torch(n: Int, sample: Samples, window: FloatArray, from: Int, until: Int,
              take: (Int, DoubleArray, DoubleArray) -> Unit): Int {
        val h = nFft / 2
        require(window.size == nFft)
        require(n > h) { "torch's reflect padding of $h needs more than $h samples, not $n" }
        val count = 1 + n / hop
        require(from in 0..until && until <= count) { "frames $from until $until of $count" }
        for (f in from until until) {
            val at = f * hop - h
            if (at >= 0 && at + nFft <= n) {
                for (j in 0 until nFft) frame[j] = sample.at(at + j).toDouble() * window[j]
            } else {
                for (j in 0 until nFft) frame[j] = sample.at(reflected(at + j, n)).toDouble() * window[j]
            }
            fft.real(frame, re, im)
            take(f, re, im)
        }
        return count
    }

    /** librosa's `util.frame`'s count of frames in [n] samples, which refuses fewer than a frame. */
    private fun frames(n: Int): Int {
        require(n >= nFft) { "input is too short (n=$n) for frame_length=$nFft" }
        return 1 + (n - nFft) / hop
    }

    companion object {
        /** numpy's `pad(x[from:to], (left, right), mode="reflect")`: its even reflection about either end, repeated
         * past the slice's length, and a slice of one sample repeated. */
        fun reflectPad(x: FloatArray, from: Int, to: Int, left: Int, right: Int): FloatArray {
            val n = to - from
            require(n > 0) { "nothing to pad" }
            return FloatArray(n + left + right) { x[from + reflected(it - left, n)] }
        }

        /** Index [i] of a signal of [n] samples, reflected into it with period 2(n - 1). */
        fun reflected(i: Int, n: Int): Int {
            if (i in 0 until n) return i
            if (n == 1) return 0
            val period = 2 * (n - 1)
            val m = Math.floorMod(i, period)
            return if (m >= n) period - m else m
        }
    }
}
