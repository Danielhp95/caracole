package io.github.danielhp95.caracole.autochords.frontend

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * The discrete Fourier transform of [n] real samples (a power of 2), in float64: their [n] / 2 + 1 non-negative
 * frequencies, `X[k] = Σ x[t] e^(-2πikt/n)`, unscaled, as numpy's and scipy's `rfft` give them. One complex FFT of
 * half the size, radix 2, iterative and in place, then its split into the real transform; its twiddles are
 * `cos` and `sin` of each angle, never a recurrence. An instance holds its buffers: one thread at a time.
 */
class Fft(val n: Int) {
    init {
        require(n >= 2 && n and (n - 1) == 0) { "an FFT of a power of 2, not $n" }  // first: the arrays need it
    }

    private val half = n / 2
    private val bits = Integer.numberOfTrailingZeros(maxOf(half, 1))
    private val reverse = IntArray(half) { Integer.reverse(it) ushr (32 - bits) }
    private val cosHalf = DoubleArray(maxOf(half / 2, 1)) { cos(2 * PI * it / half) }
    private val sinHalf = DoubleArray(maxOf(half / 2, 1)) { sin(2 * PI * it / half) }
    private val cosN = DoubleArray(half + 1) { cos(2 * PI * it / n) }
    private val sinN = DoubleArray(half + 1) { sin(2 * PI * it / n) }
    private val zr = DoubleArray(half)
    private val zi = DoubleArray(half)

    /** [x]'s first [n] samples' transform into [re] and [im], each of [n] / 2 + 1. */
    fun real(x: DoubleArray, re: DoubleArray, im: DoubleArray) {
        // The even samples as the real parts, the odd ones as the imaginary, in bit-reversed order.
        for (m in 0 until half) {
            val r = if (half > 1) reverse[m] else 0
            zr[r] = x[2 * m]
            zi[r] = x[2 * m + 1]
        }
        var size = 2
        while (size <= half) {
            val step = half / size
            val span = size / 2
            var start = 0
            while (start < half) {
                for (j in 0 until span) {
                    val wr = cosHalf[j * step]
                    val wi = -sinHalf[j * step]
                    val a = start + j
                    val b = a + span
                    val tr = wr * zr[b] - wi * zi[b]
                    val ti = wr * zi[b] + wi * zr[b]
                    zr[b] = zr[a] - tr
                    zi[b] = zi[a] - ti
                    zr[a] += tr
                    zi[a] += ti
                }
                start += size
            }
            size *= 2
        }
        // X[k] = E[k] + e^(-2πik/n) O[k], E and O the even and odd samples' transforms, from Z[k] and Z[half - k]*.
        for (k in 0..half) {
            val a = zr[k % half]
            val b = zi[k % half]
            val c = zr[(half - k) % half]
            val d = zi[(half - k) % half]
            val er = (a + c) / 2
            val ei = (b - d) / 2
            val or = (b + d) / 2
            val oi = -(a - c) / 2
            val wr = cosN[k]
            val wi = -sinN[k]
            re[k] = er + wr * or - wi * oi
            im[k] = ei + wr * oi + wi * or
        }
    }
}
