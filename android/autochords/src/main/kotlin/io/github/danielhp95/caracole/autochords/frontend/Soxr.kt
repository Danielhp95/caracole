package io.github.danielhp95.caracole.autochords.frontend

/**
 * libsoxr 0.1.3, the resampler python-soxr runs for librosa and the computer's chords from audio, over JNI
 * (`libcaracole_soxr.so`, native/soxr_jni.c): [resample] is python-soxr's `soxr.resample(x, from, to)` of a mono
 * float32 signal, HQ, linear phase, in one call. Held to python-soxr's answers within 1e-6 (SoxrTest,
 * vectors/autochords/soxr.jsonl). The library is the host's build on the JVM's `java.library.path` (hostSoxr), the
 * APK's on the phone.
 */
object Soxr {
    init {
        System.loadLibrary("caracole_soxr")
    }

    /** [x], sampled at [from] Hz, resampled to [to] Hz: about `x.size * to / from` samples, as python-soxr gives.
     * Rates must be finite and over 0 (python-soxr refuses those not over 0; libsoxr's answer to an infinite one is
     * none to rely on). */
    fun resample(x: FloatArray, from: Double, to: Double): FloatArray {
        require(from > 0 && to > 0) { "Sample rate should be over 0" }
        require(from.isFinite() && to.isFinite()) { "Sample rate should be finite" }
        return resampleHq(x, from, to)
    }

    @JvmStatic
    private external fun resampleHq(x: FloatArray, from: Double, to: Double): FloatArray
}
