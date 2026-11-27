package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.core.py.Py
import java.io.File
import java.io.RandomAccessFile
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/**
 * mpeg_frames.py on the phone: an MP3's length counted from its frames, for one whose first frame names no length
 * (no Xing or Info header with a count of frames, no VBRI), where a reader that doesn't count them guesses the file's
 * size over its first frame's bitrate. Rule for rule the computer's: ID3v2 tags skipped at the start (stacked, a
 * footer by its flag), an ID3v1 tag and an APE tag left out at the end; the first frame right at the start (zero
 * bytes passed over) of a file with no tag, else within [FIRST_WITHIN] after the tags, one another of its stream
 * follows; each frame's samples over its own rate, summed by rate in the order the rates came, junk between frames
 * passed over to the next frame another follows. A file whose first frame names its length, or that isn't MPEG audio,
 * is none ([countedLength] null), as is an empty one. The file is mapped, never read whole into the heap.
 */
object MpegFrames {
    const val FIRST_WITHIN = 64 * 1024

    private val KBPS_1 = mapOf(
        1 to intArrayOf(32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
        2 to intArrayOf(32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
        3 to intArrayOf(32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    )
    private val KBPS_2 = mapOf(
        1 to intArrayOf(32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
        2 to intArrayOf(8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    )
    private val RATES = mapOf(3 to intArrayOf(44100, 48000, 32000), 2 to intArrayOf(22050, 24000, 16000),
                              0 to intArrayOf(11025, 12000, 8000))

    /** What the frames say: their samples over the rate, the length a reader that doesn't count them takes, and how
     * many (mpeg_frames.Count). */
    data class Count(val seconds: Double, val guessed: Double, val frames: Int)

    private class Frame(val size: Int, val samples: Int, val rate: Int, val kbps: Int, val stream: Triple<Int, Int, Int>)

    /** The frames of [file] whose first frame names no length, or null (mpeg_frames.count). */
    fun count(file: File): Count? = RandomAccessFile(file, "r").use { f ->
        if (f.length() == 0L) return null
        val buf = f.channel.map(FileChannel.MapMode.READ_ONLY, 0, f.length())
        count(Bytes(buf))
    }

    /** mpeg_frames.counted_length: [count]'s seconds, or null. */
    fun countedLength(file: File): Double? = count(file)?.seconds

    /** [count] of bytes in memory (a test's). */
    fun count(bytes: ByteArray): Count? = if (bytes.isEmpty()) null else count(Bytes(bytes))

    private class Bytes(private val mapped: MappedByteBuffer?, private val array: ByteArray?) {
        constructor(b: MappedByteBuffer) : this(b, null)
        constructor(b: ByteArray) : this(null, b)

        val size: Int = mapped?.capacity() ?: array!!.size
        operator fun get(at: Int): Int = (if (mapped != null) mapped.get(at) else array!![at]).toInt() and 0xFF
        fun has(at: Int, text: String): Boolean =
            at >= 0 && at + text.length <= size && text.indices.all { get(at + it) == text[it].code }

        /** bytes.find(0xFF, from, to): the first 0xFF at or after [from] and before [to], or -1. */
        fun find(from: Int, to: Int): Int {
            var at = maxOf(0, from)
            while (at < minOf(to, size)) {
                if (get(at) == 0xFF) return at
                at++
            }
            return -1
        }

        fun bigEndian(at: Int, n: Int): Long = (0 until n).fold(0L) { v, k -> (v shl 8) or get(at + k).toLong() }
        fun littleEndian(at: Int, n: Int): Long = (n - 1 downTo 0).fold(0L) { v, k -> (v shl 8) or get(at + k).toLong() }
    }

    /** mpeg_frames._header: the frame a header's second and third bytes describe, or null. */
    private fun header(b1: Int, b2: Int): Frame? {
        if (b1 and 0xE0 != 0xE0) return null
        val version = (b1 shr 3) and 3
        val layer = (b1 shr 1) and 3
        val index = b2 shr 4
        val rateBits = (b2 shr 2) and 3
        val pad = (b2 shr 1) and 1
        if (version == 1 || layer == 0 || index == 0 || index == 15 || rateBits == 3) return null
        val mpeg1 = version == 3
        val number = 4 - layer
        val kbps = (if (mpeg1) KBPS_1.getValue(number) else KBPS_2.getValue(if (number == 1) 1 else 2))[index - 1]
        val rate = RATES.getValue(version)[rateBits]
        val (size, samples) = when {
            number == 1 -> (12 * kbps * 1000 / rate + pad) * 4 to 384
            number == 3 && !mpeg1 -> 72 * kbps * 1000 / rate + pad to 576
            else -> 144 * kbps * 1000 / rate + pad to 1152
        }
        return Frame(size, samples, rate, kbps, Triple(version, layer, rate))
    }

    private fun frame(buf: Bytes, at: Int): Frame? {
        if (at + 4 > buf.size || buf[at] != 0xFF) return null
        return header(buf[at + 1], buf[at + 2])
    }

    private fun namesItsLength(buf: Bytes, at: Int, first: Frame): Boolean {
        val mono = buf[at + 3] shr 6 == 3
        val side = if (first.stream.first == 3) (if (mono) 17 else 32) else (if (mono) 9 else 17)
        val xing = at + 4 + side
        if (buf.has(xing, "Xing") || buf.has(xing, "Info")) {
            return xing + 8 <= buf.size && buf.bigEndian(xing + 4, 4) and 1L != 0L
        }
        return buf.has(at + 36, "VBRI")
    }

    private fun audioBounds(buf: Bytes): Pair<Int, Int> {
        var start = 0
        while (start + 10 <= buf.size && buf.has(start, "ID3")) {
            val size = (buf[start + 6] shl 21) or (buf[start + 7] shl 14) or (buf[start + 8] shl 7) or buf[start + 9]
            start += 10 + size + (if (buf[start + 5] and 0x10 != 0) 10 else 0)
        }
        var end = buf.size
        if (end - 128 >= start && buf.has(end - 128, "TAG")) end -= 128
        if (end - 32 >= start && buf.has(end - 32, "APETAGEX")) {
            val size = buf.littleEndian(end - 20, 4)
            val header = if (buf.littleEndian(end - 12, 4) and 0x80000000L != 0L) 32 else 0
            end = maxOf(start.toLong(), end - size - header).toInt()
        }
        return start to end
    }

    private fun follows(buf: Bytes, at: Int, end: Int, stream: Triple<Int, Int, Int>?): Frame? {
        val frame = frame(buf, at) ?: return null
        if ((stream != null && frame.stream != stream) || at + frame.size > end) return null
        if (at + frame.size == end) return frame
        val after = frame(buf, at + frame.size)
        return if (after != null && after.stream == frame.stream) frame else null
    }

    private fun first(buf: Bytes, start: Int, end: Int): Int {
        val bound = minOf(end, start + FIRST_WITHIN)
        if (start == 0) {
            var at = start
            while (at < bound && buf[at] == 0) at++
            return if (at < bound && follows(buf, at, end, null) != null) at else -1
        }
        var at = buf.find(start, bound)
        while (at >= 0 && follows(buf, at, end, null) == null) at = buf.find(at + 1, bound)
        return at
    }

    private fun count(buf: Bytes): Count? {
        val (start, end) = audioBounds(buf)
        if (start >= buf.size) return null
        var at = first(buf, start, end)
        if (at < 0) return null
        val first = frame(buf, at)!!
        if (namesItsLength(buf, at, first)) return null
        val guessed = 8.0 * (buf.size - at) / (first.kbps * 1000)
        val samples = LinkedHashMap<Int, Long>()  // by rate, in the order they came, as Python's dict
        var frames = 0
        var stream = first.stream
        while (at + 4 <= end) {
            val frame = if (buf[at] == 0xFF) frame(buf, at) else null
            if (frame != null && at + frame.size <= end &&
                (frame.stream == stream || follows(buf, at, end, null) != null)) {
                stream = frame.stream
                samples[frame.rate] = (samples[frame.rate] ?: 0L) + frame.samples
                frames++
                at += frame.size
                continue
            }
            at = resync(buf, at + 1, end)
            if (at < 0) break
        }
        // sum(n / rate …): Python's builtin sum of floats, in the order the rates came
        return Count(Py.fsum(samples.map { (rate, n) -> n.toDouble() / rate }), guessed, frames)
    }

    private fun resync(buf: Bytes, from: Int, end: Int): Int {
        var at = from
        while (true) {
            at = buf.find(at, end)
            if (at < 0 || follows(buf, at, end, null) != null) return at
            at++
        }
    }
}
