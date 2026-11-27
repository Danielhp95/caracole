package io.github.danielhp95.caracole.ml

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

/**
 * Interleaved PCM mixed down to mono as librosa's `to_mono` does it (numpy's `mean` over the channels of float32
 * samples: the channels summed in order in float32, the sum divided by their count in float32), so a lossless file's
 * mono is the computer's to the bit. beat_this's own loader means the channels the same way.
 */
object Mixdown {
    /** [pcm], interleaved frames of [channels], as mono. */
    fun mono(pcm: FloatArray, channels: Int): FloatArray {
        require(channels > 0 && pcm.size % channels == 0) { "${pcm.size} samples aren't whole frames of $channels" }
        if (channels == 1) return pcm.copyOf()
        val count = channels.toFloat()
        return FloatArray(pcm.size / channels) { t ->
            var sum = pcm[t * channels]
            for (c in 1 until channels) sum += pcm[t * channels + c]
            sum / count
        }
    }

    /** The file [pcm] of interleaved little-endian float32 frames of [channels] (Decoder's), as mono into [into], a
     * block at a time; the frames written. */
    fun mono(pcm: File, channels: Int, into: File): Long {
        val frameBytes = 4 * channels
        val inBuffer = ByteBuffer.allocate(BLOCK_FRAMES * frameBytes).order(ByteOrder.LITTLE_ENDIAN)
        val outBuffer = ByteBuffer.allocate(BLOCK_FRAMES * 4).order(ByteOrder.LITTLE_ENDIAN)
        var frames = 0L
        FileChannel.open(pcm.toPath(), StandardOpenOption.READ).use { source ->
            require(source.size() % frameBytes == 0L) { "$pcm isn't whole frames of $channels" }
            FileChannel.open(into.toPath(), StandardOpenOption.WRITE, StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING).use { sink ->
                val block = FloatArray(BLOCK_FRAMES * channels)
                while (true) {
                    inBuffer.clear()
                    while (inBuffer.hasRemaining() && source.read(inBuffer) >= 0) Unit
                    inBuffer.flip()
                    val n = inBuffer.remaining() / 4
                    if (n == 0) break
                    inBuffer.asFloatBuffer().get(block, 0, n)
                    val mono = mono(block.copyOf(n), channels)
                    outBuffer.clear()
                    outBuffer.asFloatBuffer().put(mono)
                    outBuffer.limit(mono.size * 4)
                    while (outBuffer.hasRemaining()) sink.write(outBuffer)
                    frames += mono.size
                }
            }
        }
        return frames
    }

    private const val BLOCK_FRAMES = 8192
}
