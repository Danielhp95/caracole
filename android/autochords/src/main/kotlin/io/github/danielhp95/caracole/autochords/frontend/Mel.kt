package io.github.danielhp95.caracole.autochords.frontend

import kotlin.math.ln1p
import kotlin.math.sqrt

/**
 * beat_this's input: its `LogMelSpect` of mono 22,050 Hz audio, `[frames, 128]` row-major, held to the computer's by
 * the design's B1 feature gate (vectors/autochords/frontend.jsonl, MelTest).
 *
 * torchaudio's `MelSpectrogram` as beat_this sets it, from frontend.json ([FrontendData.Mel]): `torch.stft` of
 * [N_FFT] samples every [HOP], times its periodic Hann window, centred with reflect padding ([Stft.torch]), each
 * frame's |spectrum| times its norm (`normalized="frame_length"`), power 1, through the slaney filterbank; then
 * `log1p(1000 · x)`. torch computes in float32; here the window's product, the FFT, the filterbank's sums and the log
 * are float64, the result rounded to float32 once.
 */
object Mel {
    private val data get() = FrontendData.mel

    /** The mel bands a frame. */
    val MELS: Int get() = data.filterbank.rows

    /** The STFT's window, and its hop, in samples at 22,050 Hz. */
    val N_FFT: Int get() = data.nFft
    val HOP: Int get() = data.hop

    /** The log-mel of [y], mono at 22,050 Hz, longer than half a window: `[1 + y.size / HOP, MELS]`, row-major. */
    fun logMel(y: FloatArray): FloatArray {
        val d = data
        require(d.padMode == "reflect") { "an STFT of padding ${d.padMode}" }
        val fb = d.filterbank
        require(fb.cols == d.nFft / 2 + 1 && fb.im == null)
        val mels = fb.rows
        val stft = Stft(d.nFft, d.hop)
        val magnitudes = DoubleArray(fb.cols)
        val out = FloatArray((1 + y.size / d.hop) * mels)
        stft.torch(y, d.window) { f, re, im ->
            for (k in magnitudes.indices) magnitudes[k] = sqrt(re[k] * re[k] + im[k] * im[k]) * d.norm
            for (m in 0 until mels) {
                var sum = 0.0
                for (i in fb.indptr[m] until fb.indptr[m + 1]) sum += fb.re[i] * magnitudes[fb.indices[i]]
                out[f * mels + m] = ln1p(d.logMultiplier * sum).toFloat()
            }
        }
        return out
    }
}
