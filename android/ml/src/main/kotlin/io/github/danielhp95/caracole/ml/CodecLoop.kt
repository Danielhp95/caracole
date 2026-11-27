package io.github.danielhp95.caracole.ml

import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

/** An audio file the phone can't decode: its words say why. */
class UndecodableAudio(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * The PCM encodings a decoder's output may name (MediaFormat's `pcm-encoding`, AudioFormat's codes), each read to the
 * float32 libsndfile gives for the same depth: an integer of `b` bits times 2^-(b-1) (8-bit unsigned, less 128 first),
 * a float as it is. A format that names none is 16-bit (MediaCodec's default); any other code is refused, never read
 * as 16-bit ([of]).
 */
enum class PcmEncoding(val code: Int, val bytes: Int, val words: String) {
    PCM_16(2, 2, "16-bit"), PCM_8(3, 1, "8-bit"), FLOAT(4, 4, "float"), PCM_24_PACKED(21, 3, "24-bit"),
    PCM_32(22, 4, "32-bit");

    companion object {
        fun of(code: Int?): PcmEncoding = if (code == null) PCM_16 else entries.firstOrNull { it.code == code }
            ?: throw UndecodableAudio("the decoder gives samples of an encoding caracole doesn't read ($code)")
    }
}

/** What a decoder's output says it holds: its rate, channels and `pcm-encoding` (null, none named). */
data class OutFormat(val rate: Int, val channels: Int, val encoding: Int?)

/** The codec's side of [CodecLoop], MediaCodec's calls by their meaning, so the loop runs on the JVM's tests too. */
interface CodecPort {
    /** An input buffer's index, or a negative number for none free within [timeoutUs]. */
    fun dequeueInput(timeoutUs: Long): Int
    fun inputBuffer(index: Int): ByteBuffer
    fun queueInput(index: Int, size: Int, timeUs: Long, endOfStream: Boolean)

    /** An output buffer's index (its [OutBuffer] filled in), [TRY_AGAIN], [FORMAT_CHANGED] or [BUFFERS_CHANGED]. */
    fun dequeueOutput(timeoutUs: Long, into: OutBuffer): Int
    fun outputFormat(): OutFormat
    fun outputFormat(index: Int): OutFormat
    fun outputBuffer(index: Int): ByteBuffer
    fun releaseOutput(index: Int)

    companion object {
        const val TRY_AGAIN = -1  // MediaCodec.INFO_TRY_AGAIN_LATER
        const val FORMAT_CHANGED = -2  // INFO_OUTPUT_FORMAT_CHANGED
        const val BUFFERS_CHANGED = -3  // INFO_OUTPUT_BUFFERS_CHANGED
    }
}

/** An output buffer's bytes ([offset], [size]) and whether it is the stream's last. */
class OutBuffer {
    var offset = 0
    var size = 0
    var endOfStream = false
}

/** The extractor's side: the track's next sample into a buffer (its bytes, negative at the end), its time, and on. */
interface SamplePort {
    fun read(into: ByteBuffer): Int
    fun timeUs(): Long
    fun advance()
}

/**
 * How the decoded samples are trimmed to the computer's: [skip] frames off the start (the encoder's delay), then
 * [keep] frames at most (an MP4's edit list, an Ogg's last granule, exactly, as FFmpeg and libsndfile trim them), or,
 * with no [keep], [cutEnd] frames off the end (the padding a header states). Nothing is cut to a length a container
 * merely states: a length a little short (an extractor's guess) would cut real audio.
 *
 * Its counts are in [rate]'s samples (an MP4's `mdhd` timescale, an Ogg's rate), or the output's where it names none.
 * Applied to a decoder's output, they are first made the output's ([at]): the same where the rates agree, rescaled
 * where the output's rate is a whole multiple of the samples (a decoder that doubles an AAC's rate, its SBR implicit,
 * gives twice as many), and else [fallback], the format's stated delay and padding: never a count of one rate applied
 * to samples of another.
 */
data class Trim(val skip: Long, val keep: Long? = null, val cutEnd: Long = 0, val rate: Int? = null,
                val fallback: Trim? = null) {
    /** The frames kept of [afterSkip], those the decoder gave after [skip] (this Trim being the output's: [at]). */
    fun frames(afterSkip: Long): Long = maxOf(0L, keep?.let { minOf(it, afterSkip) } ?: (afterSkip - cutEnd))

    /** This Trim in samples of [outRate]: rescaled exactly, else [fallback]'s (none: no trim). */
    fun at(outRate: Int): Trim {
        if (rate == null || rate == outRate) return Trim(skip, keep, cutEnd)
        fun scaled(n: Long): Long? = try {
            Math.multiplyExact(n, outRate.toLong()).takeIf { it % rate == 0L }?.div(rate)
        } catch (e: ArithmeticException) {
            null
        }
        val s = scaled(skip)
        val k = keep?.let(::scaled)
        val c = scaled(cutEnd)
        if (s != null && c != null && (keep == null || k != null)) return Trim(s, k, c)
        return (fallback ?: Trim(0)).at(outRate)
    }

    companion object {
        /** An MP4's one media edit: from [mediaTime] in the media's samples (of [rate]), [kept] of them. */
        fun edit(mediaTime: Long, kept: Long, rate: Int? = null, fallback: Trim? = null) =
            Trim(skip = mediaTime, keep = kept, rate = rate, fallback = fallback)

        /** A delay and a padding the format states (a LAME tag's, an MP4 with no edit list's, else none), in samples
         * of [rate], the extractor's (none, or 0 where the format names none: the output's). */
        fun stated(delay: Int, padding: Int, rate: Int? = null) =
            Trim(skip = delay.toLong(), cutEnd = padding.toLong(), rate = rate?.takeIf { it > 0 })
    }
}

/** [block]'s answer, a container's boxes or pages read; any failure there (a field that leads nowhere, an I/O error)
 * [UndecodableAudio], naming [what]. */
fun <T> readContainer(what: String, block: () -> T): T = try {
    block()
} catch (e: IOException) {
    throw UndecodableAudio("$what can't be read: ${e.message}", e)
} catch (e: RuntimeException) {
    throw UndecodableAudio("$what can't be read: ${e.message}", e)
}

/**
 * MediaCodec's loop over a track, its decisions plain code: the input fed (a [first] buffer before the track's, where
 * given), every output buffer read in its encoding ([PcmEncoding]) to float32 and written, the first frames [skip]
 * says for the output's rate passed over (decided at each of the output's formats until the codec gives a sample); it
 * ends at the codec's end of stream. It never hangs and never mixes layouts:
 *
 * - after the input's end, [IDLE_MOST] answers in a row with no output and no end of stream is a decoder that stopped
 *   ([UndecodableAudio]), and so is [STALL_NS] of the clock with neither an input taken nor an output given;
 * - a rate or a channel count that changes once the codec gave samples (skipped or written) is refused (the samples
 *   before are of another layout); an encoding that changes is read in its own.
 */
class CodecLoop(private val nanos: () -> Long = System::nanoTime) {
    class Result(val rate: Int, val channels: Int, val encoding: PcmEncoding)

    fun run(codec: CodecPort, source: SamplePort, out: FloatWriter, skip: (rate: Int) -> Long, first: ByteArray?):
        Result {
        val info = OutBuffer()
        var inputDone = false
        var primed = first == null
        var format: OutFormat? = null
        var encoding = PcmEncoding.PCM_16
        var toSkip = -1L
        var given = 0L  // the frames the codec gave, skipped or written
        var idle = 0
        var progress = nanos()
        while (true) {
            if (!inputDone) {
                val i = codec.dequeueInput(TIMEOUT_US)
                if (i >= 0) {
                    val buffer = codec.inputBuffer(i)
                    if (!primed) {
                        buffer.put(first!!)
                        codec.queueInput(i, first.size, 0, false)
                        primed = true
                    } else {
                        val n = source.read(buffer)
                        if (n < 0) {
                            codec.queueInput(i, 0, 0, true)
                            inputDone = true
                        } else {
                            codec.queueInput(i, n, source.timeUs(), false)
                            source.advance()
                        }
                    }
                    progress = nanos()
                }
            }
            val o = codec.dequeueOutput(TIMEOUT_US, info)
            when {
                o == CodecPort.FORMAT_CHANGED -> {
                    val f = codec.outputFormat()
                    format = settled(format, f, given)
                    encoding = PcmEncoding.of(f.encoding)
                    // Decided again at each format before the first sample: the rate it is decided for is the one
                    // the samples come at.
                    if (given == 0L) toSkip = skip(f.rate)
                }
                o >= 0 -> {
                    if (format == null) {
                        val f = codec.outputFormat(o)
                        format = settled(null, f, given)
                        encoding = PcmEncoding.of(f.encoding)
                    }
                    if (toSkip < 0) toSkip = skip(format.rate)
                    val buffer = codec.outputBuffer(o).duplicate().order(ByteOrder.nativeOrder())
                    buffer.position(info.offset).limit(info.offset + info.size)
                    val frameBytes = encoding.bytes * format.channels
                    val frames = (info.size / frameBytes).toLong()
                    val passed = minOf(toSkip, frames).toInt()
                    toSkip -= passed
                    given += frames
                    buffer.position(info.offset + passed * frameBytes)
                    out.write(buffer, encoding)
                    codec.releaseOutput(o)
                    idle = 0
                    progress = nanos()
                    if (info.endOfStream) break
                }
                else -> if (inputDone && ++idle > IDLE_MOST) {
                    throw UndecodableAudio("the decoder stopped giving audio before the end of the file")
                }
            }
            if (nanos() - progress > STALL_NS) throw UndecodableAudio("the decoder stopped: nothing for a while")
        }
        val f = format ?: throw UndecodableAudio("the decoder gave no audio")
        return Result(f.rate, f.channels, encoding)
    }

    /** [now], the output's format, as the one settled: [before]'s, unless the codec gave no sample yet (none
     * skipped, none written: the skip, decided at a rate, is then decided again). */
    private fun settled(before: OutFormat?, now: OutFormat, given: Long): OutFormat {
        if (now.rate <= 0 || now.channels <= 0) throw UndecodableAudio("the decoder named no rate or channels")
        if (before != null && given > 0 && (before.rate != now.rate || before.channels != now.channels)) {
            throw UndecodableAudio("the decoder changed from ${before.rate} Hz, ${before.channels} channels to " +
                "${now.rate} Hz, ${now.channels} channels partway")
        }
        return now
    }

    companion object {
        const val TIMEOUT_US = 10_000L

        /** Answers with nothing after the input's end before the decoder is given up: 3 s at [TIMEOUT_US]. */
        const val IDLE_MOST = 300

        /** The clock with neither an input taken nor an output given before the decoder is given up. */
        const val STALL_NS = 30_000_000_000L
    }
}

/** Interleaved little-endian float32 into a file, a buffer at a time. */
class FloatWriter(file: File) : AutoCloseable {
    private val channel = FileChannel.open(file.toPath(), StandardOpenOption.WRITE, StandardOpenOption.CREATE,
        StandardOpenOption.TRUNCATE_EXISTING)
    private val bytes = ByteBuffer.allocate(1 shl 16).order(ByteOrder.LITTLE_ENDIAN)
    var samples = 0L
        private set

    fun write(block: FloatArray, n: Int) {
        for (i in 0 until n) put(block[i])
    }

    /** A decoder's output buffer of [encoding]'s samples, in the platform's order. */
    fun write(buffer: ByteBuffer, encoding: PcmEncoding) {
        when (encoding) {
            PcmEncoding.FLOAT -> while (buffer.remaining() >= 4) put(buffer.float)
            PcmEncoding.PCM_16 -> while (buffer.remaining() >= 2) put(buffer.short * (1f / 32768f))
            PcmEncoding.PCM_8 ->
                while (buffer.hasRemaining()) put(((buffer.get().toInt() and 0xFF) - 128) * (1f / 128f))
            PcmEncoding.PCM_32 -> while (buffer.remaining() >= 4) put(buffer.int.toFloat() * (1f / 2147483648f))
            PcmEncoding.PCM_24_PACKED -> {
                val little = buffer.order() == ByteOrder.LITTLE_ENDIAN
                while (buffer.remaining() >= 3) {
                    val a = buffer.get().toInt()
                    val b = buffer.get().toInt()
                    val c = buffer.get().toInt()
                    val s = if (little) (c shl 16) or ((b and 0xFF) shl 8) or (a and 0xFF)
                    else (a shl 16) or ((b and 0xFF) shl 8) or (c and 0xFF)
                    put(s.toFloat() * (1f / 8388608f))
                }
            }
        }
    }

    private fun put(x: Float) {
        if (!bytes.hasRemaining()) flush()
        bytes.putFloat(x)
        samples += 1
    }

    private fun flush() {
        bytes.flip()
        while (bytes.hasRemaining()) channel.write(bytes)
        bytes.clear()
    }

    /** The file cut to its first [samples]. */
    fun cut(samples: Long) {
        flush()
        channel.truncate(4 * samples)
        this.samples = minOf(this.samples, samples)
    }

    override fun close() {
        flush()
        channel.close()
    }
}
