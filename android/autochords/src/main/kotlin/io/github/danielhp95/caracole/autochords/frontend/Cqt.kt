package io.github.danielhp95.caracole.autochords.frontend

import kotlin.math.ceil
import kotlin.math.ln
import kotlin.math.sqrt

/**
 * BTC's input: btc.py's `cqt_features`, the log-CQT of mono 22,050 Hz audio, `[frames, 144]` row-major, held to the
 * computer's by the design's B1 feature gate (vectors/autochords/frontend.jsonl, CqtTest).
 *
 * btc.py's rule: the audio 10 s ([CHUNK] samples) at a time, a tail after the last whole chunk only when it is a
 * hop ([HOP]) or more (or the whole audio), and audio under a hop refused; then `log(|C| + floor)`. Each chunk is
 * librosa 1.0's `cqt` as frontend.json's steps say it ran ([FrontendData.Cqt]): a resample (soxr HQ by [Soxr], its
 * length fixed to `ceil(n · ratio)`, zeros past soxr's, then divided by √ratio, kept in float32 as librosa keeps it);
 * or an octave (librosa's STFT of the samples as they now are, [Stft.librosa], each frame's spectrum times the
 * octave's sparse basis, |·|). The octaves fill the bins from the top, all cut to the fewest frames, and each bin is
 * divided by the root of its length. The samples between resamples are float32, as librosa's; the STFT, the bases'
 * sums, the scale and the log are float64 here (librosa's are float64 for the STFT, complex64 for the rest), and
 * the result is rounded to float32 once.
 */
object Cqt {
    private val data get() = FrontendData.cqt

    /** BTC's bins a frame. */
    val BINS: Int get() = data.bins

    /** The CQT's hop at 22,050 Hz, and the least audio and the least tail btc.py keeps. */
    val HOP: Int get() = data.minTail

    /** btc.py's chunk, in samples. */
    val CHUNK: Int get() = data.chunk

    /** The log-CQT of [y], mono at 22,050 Hz: `[frames, BINS]`, row-major. */
    fun logFeatures(y: FloatArray): FloatArray {
        val d = data
        require(y.size >= d.minTail) { "audio is too short to recognize chords in" }
        val parts = ArrayList<FloatArray>()
        var start = 0
        while (y.size > start + d.chunk) {
            parts += chunk(y.copyOfRange(start, start + d.chunk), d)
            start += d.chunk
        }
        if (y.size - start >= d.minTail || parts.isEmpty()) parts += chunk(y.copyOfRange(start, y.size), d)
        val out = FloatArray(parts.sumOf { it.size })
        var at = 0
        for (part in parts) {
            part.copyInto(out, at)
            at += part.size
        }
        return out
    }

    /** One chunk's log-CQT, `[frames, bins]`. */
    private fun chunk(samples: FloatArray, d: FrontendData.Cqt): FloatArray {
        var y = samples
        val octaves = ArrayList<Response>()
        for (step in d.steps) {
            when (step) {
                is FrontendData.Resample -> y = resample(y, step)
                is FrontendData.Octave -> octaves += response(y, step)
            }
        }
        val frames = octaves.minOf { it.frames }
        val out = FloatArray(frames * d.bins)
        var end = d.bins
        for (octave in octaves) {
            val rows = octave.rows
            require(rows <= end) { "frontend.json's octaves hold more bins than ${d.bins}" }
            val first = end - rows
            for (f in 0 until frames) {
                for (r in 0 until rows) {
                    val bin = first + r
                    val value = octave.magnitudes[f * rows + r] / sqrt(d.lengths[bin])
                    out[f * d.bins + bin] = ln(value + d.floor).toFloat()
                }
            }
            end = first
        }
        require(end == 0) { "frontend.json's octaves leave $end bins empty" }
        return out
    }

    /** librosa's `audio.resample` of [y] as the step names it. */
    private fun resample(y: FloatArray, step: FrontendData.Resample): FloatArray {
        require(step.resType == "soxr_hq") { "a resample librosa ran as ${step.resType}, not soxr_hq" }
        val ratio = step.to / step.from
        var out = Soxr.resample(y, step.from, step.to)
        if (step.fix) out = out.copyOf(ceil(y.size * ratio).toInt())
        if (step.scale) {
            val root = sqrt(ratio)
            for (i in out.indices) out[i] = (out[i] / root).toFloat()
        }
        return out
    }

    /** An octave's [frames] × [rows] magnitudes, row-major. */
    private class Response(val frames: Int, val rows: Int, val magnitudes: DoubleArray)

    /** librosa's `__cqt_response`: each frame's |spectrum · basis|. */
    private fun response(y: FloatArray, octave: FrontendData.Octave): Response {
        require(octave.window == "ones" && octave.padMode == "reflect") {
            "an STFT of window ${octave.window} and padding ${octave.padMode}"
        }
        val basis = octave.basis
        require(basis.cols == octave.nFft / 2 + 1 && basis.im != null)
        val rows = basis.rows
        val most = (y.size + octave.nFft) / octave.hop + 2
        val out = DoubleArray(most * rows)
        val imag = basis.im
        val frames = Stft(octave.nFft, octave.hop).librosa(y) { f, re, im ->
            for (r in 0 until rows) {
                var sumRe = 0.0
                var sumIm = 0.0
                for (i in basis.indptr[r] until basis.indptr[r + 1]) {
                    val c = basis.indices[i]
                    val br = basis.re[i]
                    val bi = imag[i]
                    sumRe += br * re[c] - bi * im[c]
                    sumIm += br * im[c] + bi * re[c]
                }
                out[f * rows + r] = sqrt(sumRe * sumRe + sumIm * sumIm)
            }
        }
        return Response(frames, rows, out)
    }
}
