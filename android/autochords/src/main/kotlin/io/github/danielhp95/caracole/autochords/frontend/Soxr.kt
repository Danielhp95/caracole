package io.github.danielhp95.caracole.autochords.frontend

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

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

    /**
     * [input], little-endian float32 samples at [from] Hz, resampled to [to] Hz into [output], a block at a time:
     * [resample]'s answer sample for sample (the same soxr_t, fed the same pieces, [piece], drained [ROOM] samples a
     * call, flushed until it gives nothing, cut to the one-shot's room, `n · to / from + 1`), so no song is held
     * whole: its buffers are a piece's and [ROOM]'s, whatever its length. The samples written.
     */
    fun resample(input: File, from: Double, to: Double, output: File): Long {
        require(from > 0 && to > 0) { "Sample rate should be over 0" }
        require(from.isFinite() && to.isFinite()) { "Sample rate should be finite" }
        val n = input.length() / 4
        val room = (n.toDouble() * to / from + 1).toLong()
        val piece = piece(from, to)
        val inBlock = FloatArray(piece)
        val outBlock = FloatArray(ROOM)
        val inBytes = ByteBuffer.allocate(4 * piece).order(ByteOrder.LITTLE_ENDIAN)
        val outBytes = ByteBuffer.allocate(4 * ROOM).order(ByteOrder.LITTLE_ENDIAN)
        var written = 0L
        val handle = streamOpen(from, to)
        try {
            FileChannel.open(input.toPath(), StandardOpenOption.READ).use { source ->
                FileChannel.open(output.toPath(), StandardOpenOption.WRITE, StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING).use { sink ->
                    fun put(count: Int) {
                        val kept = minOf(count.toLong(), room - written).toInt()
                        if (kept <= 0) return
                        outBytes.clear()
                        outBytes.asFloatBuffer().put(outBlock, 0, kept)
                        outBytes.limit(4 * kept)
                        while (outBytes.hasRemaining()) sink.write(outBytes)
                        written += kept
                    }
                    var at = 0L
                    while (true) {
                        val flushing = at >= n
                        val take = if (flushing) 0 else minOf(piece.toLong(), n - at).toInt()
                        if (!flushing) {
                            inBytes.clear()
                            inBytes.limit(4 * take)
                            while (inBytes.hasRemaining()) if (source.read(inBytes) < 0) break
                            inBytes.flip()
                            inBytes.asFloatBuffer().get(inBlock, 0, take)
                        }
                        var done = streamProcess(handle, if (flushing) null else inBlock, take, outBlock)
                        while (true) {
                            put(done)
                            if (if (flushing) done == 0 else done < ROOM) break
                            done = streamProcess(handle, if (flushing) null else inBlock, 0, outBlock)
                        }
                        if (flushing) break
                        at += take
                    }
                }
            }
        } finally {
            streamClose(handle)
        }
        return written
    }

    /** The samples a call of the stream may write: its output block. */
    const val ROOM = 8192

    /** caracole_soxr.c's input piece, python-soxr's: max(1000, 48000 · from / to) samples. */
    fun piece(from: Double, to: Double): Int = maxOf(1000.0, 48000 * from / to).toInt()

    @JvmStatic
    private external fun resampleHq(x: FloatArray, from: Double, to: Double): FloatArray

    @JvmStatic
    private external fun streamOpen(from: Double, to: Double): Long

    /** [x]'s first [n] samples fed (x null: the flush), at most [y]'s size written into [y]; how many. */
    @JvmStatic
    private external fun streamProcess(handle: Long, x: FloatArray?, n: Int, y: FloatArray): Int

    @JvmStatic
    private external fun streamClose(handle: Long)
}
