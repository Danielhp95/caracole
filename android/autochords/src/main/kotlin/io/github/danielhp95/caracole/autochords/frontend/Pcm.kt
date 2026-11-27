package io.github.danielhp95.caracole.autochords.frontend

import java.io.EOFException
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * A WAV's or an AIFF's PCM read with no codec, each sample the float32 libsndfile gives (soundfile's, which
 * autochords/audio.py `load_mono` reads through): an integer sample of `b` bits times 2^-(b-1) (an 8-bit WAV's,
 * unsigned, less 128 first), a float one as it is (a double made a float). The chords-on-the-phone design's §3.6:
 * the phone's Decoder reads these with no MediaCodec.
 *
 * - WAV: RIFF `WAVE`, its `fmt ` of PCM (1), IEEE float (3), or WAVE_FORMAT_EXTENSIBLE (0xFFFE) of either subformat;
 *   integers of 8, 16, 24 or 32 bits, floats of 32 or 64; its `data` chunk (a size past the file's end, as a recorder
 *   cut off leaves it, read to the end, whole frames).
 * - AIFF: FORM `AIFF`, or `AIFC` uncompressed (`NONE`, big-endian; `sowt`, little-endian; `fl32`/`FL32` and
 *   `fl64`/`FL64`, big-endian floats); its `COMM` (channels, frames, bits, the 80-bit rate) and `SSND`.
 *
 * Anything else (RF64 among them, which is no RIFF), [format] gives null: a codec's to read. A WAV or an AIFF whose
 * header is cut short, or names no channel, more than [MOST_CHANNELS], or a width libsndfile reads none of, is
 * [Unreadable], never a block sized by what it says. A `data` chunk of no bytes is no frames, as libsndfile reads it.
 * [read] streams the samples a block at a time, interleaved, so that a long file is never held.
 */
object Pcm {
    /** A WAV's or an AIFF's header that can't be read: cut short, or naming what no PCM is. */
    class Unreadable(message: String) : IOException(message)

    /** The most channels a header may name: past it, no audio caracole reads (a 7.1 file is 8). */
    const val MOST_CHANNELS = 32

    /** What a file's header says: [dataAt] and [frames] are where its samples begin and how many whole frames of
     * [channels] the file holds there. */
    class Format(
        val container: String, val rate: Int, val channels: Int, val bits: Int, val float: Boolean,
        val bigEndian: Boolean, val dataAt: Long, val frames: Long,
    ) {
        val bytesPerSample: Int get() = (bits + 7) / 8
        val blockAlign: Int get() = bytesPerSample * channels
        val seconds: Double get() = frames.toDouble() / rate
    }

    const val BLOCK_FRAMES = 4096

    /** [file]'s format, or null for a file that is no WAV or AIFF of PCM read here. */
    fun format(file: File): Format? = RandomAccessFile(file, "r").use {
        try {
            format(it)
        } catch (e: EOFException) {
            throw Unreadable("its header is cut short")
        }
    }

    /** Every sample of [file] interleaved, a block of [BLOCK_FRAMES] frames (the last one fewer) at a time to [block]
     * with its count of samples ([FloatArray] reused between calls). */
    fun read(file: File, format: Format, block: (FloatArray, Int) -> Unit) {
        RandomAccessFile(file, "r").use { f ->
            f.seek(format.dataAt)
            val bytes = ByteArray(BLOCK_FRAMES * format.blockAlign)
            val out = FloatArray(BLOCK_FRAMES * format.channels)
            var left = format.frames
            while (left > 0) {
                val frames = minOf(left, BLOCK_FRAMES.toLong()).toInt()
                f.readFully(bytes, 0, frames * format.blockAlign)
                val n = frames * format.channels
                convert(bytes, n, format, out)
                block(out, n)
                left -= frames
            }
        }
    }

    /** Every sample of [file] interleaved, whole: for a short file. */
    fun samples(file: File, format: Format): FloatArray {
        val all = FloatArray(Math.toIntExact(format.frames * format.channels))
        var at = 0
        read(file, format) { block, n ->
            System.arraycopy(block, 0, all, at, n)
            at += n
        }
        return all
    }

    private fun convert(bytes: ByteArray, n: Int, format: Format, out: FloatArray) {
        val b = ByteBuffer.wrap(bytes).order(if (format.bigEndian) ByteOrder.BIG_ENDIAN else ByteOrder.LITTLE_ENDIAN)
        when {
            format.float && format.bits == 32 -> for (i in 0 until n) out[i] = b.getFloat(4 * i)
            format.float -> for (i in 0 until n) out[i] = b.getDouble(8 * i).toFloat()
            format.bits == 8 && !format.bigEndian && format.container == WAV ->
                for (i in 0 until n) out[i] = ((bytes[i].toInt() and 0xFF) - 128).toFloat() * (1f / 128f)
            format.bits == 8 -> for (i in 0 until n) out[i] = bytes[i].toFloat() * (1f / 128f)
            format.bits == 16 -> for (i in 0 until n) out[i] = b.getShort(2 * i).toFloat() * (1f / 32768f)
            format.bits == 24 -> for (i in 0 until n) {
                val at = 3 * i
                val (hi, mid, lo) = if (format.bigEndian) Triple(bytes[at], bytes[at + 1], bytes[at + 2])
                else Triple(bytes[at + 2], bytes[at + 1], bytes[at])
                val s = (hi.toInt() shl 16) or ((mid.toInt() and 0xFF) shl 8) or (lo.toInt() and 0xFF)
                out[i] = s.toFloat() * (1f / 8388608f)
            }
            else -> for (i in 0 until n) out[i] = b.getInt(4 * i).toFloat() * (1f / 2147483648f)
        }
    }

    const val WAV = "WAV"
    const val AIFF = "AIFF"

    private fun format(f: RandomAccessFile): Format? {
        val length = f.length()
        if (length < 12) return null
        val head = ByteArray(12).also { f.readFully(it) }
        return when {
            named(head, 0, "RIFF") && named(head, 8, "WAVE") -> wav(f, length)
            named(head, 0, "FORM") && (named(head, 8, "AIFF") || named(head, 8, "AIFC")) ->
                aiff(f, length, named(head, 8, "AIFC"))
            else -> null
        }
    }

    private fun wav(f: RandomAccessFile, length: Long): Format? {
        var at = 12L
        var fmt: ByteBuffer? = null
        while (at + 8 <= length) {
            val head = chunk(f, at, ByteOrder.LITTLE_ENDIAN)
            val size = head.getInt(4).toLong() and 0xFFFFFFFFL
            val body = at + 8
            when {
                named(head.array(), 0, "fmt ") -> {
                    if (size < 16) return null
                    fmt = read(f, body, minOf(size, 40L).toInt(), ByteOrder.LITTLE_ENDIAN)
                }
                named(head.array(), 0, "data") -> {
                    val b = fmt ?: return null
                    var tag = b.getShort(0).toInt() and 0xFFFF
                    val channels = b.getShort(2).toInt() and 0xFFFF
                    val rate = b.getInt(4)
                    val bits = b.getShort(14).toInt() and 0xFFFF
                    if (tag == 0xFFFE) tag = if (b.capacity() >= 26) b.getShort(24).toInt() and 0xFFFF else return null
                    val float = when (tag) {
                        1 -> false
                        3 -> true
                        else -> return null
                    }
                    if (float && bits != 32 && bits != 64 || !float && bits !in setOf(8, 16, 24, 32)) {
                        throw Unreadable("samples of $bits bits${if (float) ", floating point" else ""}")
                    }
                    return made(WAV, rate, channels, bits, float, bigEndian = false, body, minOf(size, length - body))
                }
            }
            at = body + size + (size and 1)
        }
        return null
    }

    private fun aiff(f: RandomAccessFile, length: Long, compressed: Boolean): Format? {
        var at = 12L
        var comm: ByteBuffer? = null
        var commSize = 0L
        while (at + 8 <= length) {
            val head = chunk(f, at, ByteOrder.BIG_ENDIAN)
            val size = head.getInt(4).toLong() and 0xFFFFFFFFL
            val body = at + 8
            when {
                named(head.array(), 0, "COMM") -> {
                    if (size < 18) return null
                    commSize = size
                    comm = read(f, body, minOf(size, 22L).toInt(), ByteOrder.BIG_ENDIAN)
                }
                named(head.array(), 0, "SSND") -> {
                    val c = comm ?: return null
                    val channels = c.getShort(0).toInt() and 0xFFFF
                    val frames = c.getInt(2).toLong() and 0xFFFFFFFFL
                    var bits = c.getShort(6).toInt() and 0xFFFF
                    val rate = extended(c, 8) ?: throw Unreadable("a rate no 80-bit float of whole hertz")
                    var bigEndian = true
                    var float = false
                    if (compressed) {
                        if (commSize < 22) return null
                        val kind = ByteArray(4).also { c.position(18); c.get(it) }
                        when {
                            named(kind, 0, "NONE") || named(kind, 0, "twos") -> {}
                            named(kind, 0, "sowt") -> bigEndian = false
                            named(kind, 0, "fl32") || named(kind, 0, "FL32") -> { float = true; bits = 32 }
                            named(kind, 0, "fl64") || named(kind, 0, "FL64") -> { float = true; bits = 64 }
                            else -> return null
                        }
                    }
                    if (!float && bits !in 1..32) throw Unreadable("samples of $bits bits")
                    val offset = read(f, body, 4, ByteOrder.BIG_ENDIAN).getInt(0).toLong() and 0xFFFFFFFFL
                    val dataAt = body + 8 + offset
                    val bytes = (bits + 7) / 8 * channels.toLong()
                    if (bytes == 0L) throw Unreadable("$channels channels")
                    val there = maxOf(0L, minOf(size - 8 - offset, length - dataAt))
                    return made(AIFF, rate, channels, ((bits + 7) / 8) * 8, float, bigEndian, dataAt,
                        minOf(there, frames * bytes))
                }
            }
            at = body + size + (size and 1)
        }
        return null
    }

    private fun made(container: String, rate: Int, channels: Int, bits: Int, float: Boolean, bigEndian: Boolean,
                     dataAt: Long, bytes: Long): Format? {
        if (channels !in 1..MOST_CHANNELS) throw Unreadable("$channels channels")
        if (rate <= 0) throw Unreadable("a rate of $rate")
        val align = (bits + 7) / 8 * channels
        return Format(container, rate, channels, bits, float, bigEndian, dataAt, bytes / align)
    }

    /** An AIFF's sample rate, an IEEE 754 80-bit extended float, as a whole number of Hz (null for none). */
    private fun extended(b: ByteBuffer, at: Int): Int? {
        val exponent = (b.getShort(at).toInt() and 0x7FFF) - 16383
        val mantissa = b.getLong(at + 2)
        if (exponent < 0 || exponent > 30) return null
        return (mantissa ushr (63 - exponent)).toInt()
    }

    private fun chunk(f: RandomAccessFile, at: Long, order: ByteOrder): ByteBuffer = read(f, at, 8, order)

    private fun read(f: RandomAccessFile, at: Long, n: Int, order: ByteOrder): ByteBuffer {
        val bytes = ByteArray(n)
        f.seek(at)
        f.readFully(bytes)
        return ByteBuffer.wrap(bytes).order(order)
    }

    private fun named(bytes: ByteArray, at: Int, id: String): Boolean =
        id.indices.all { bytes[at + it] == id[it].code.toByte() }
}
