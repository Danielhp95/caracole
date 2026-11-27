package io.github.danielhp95.caracole.ml

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import io.github.danielhp95.caracole.autochords.frontend.Pcm
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

/** What [Decoder.decode] wrote: [frames] frames of [channels] at [rate] Hz; [durationS], the length the file states
 * (its container's, else the frames'), the one the sheet is laid over; [codec], the decoder that ran (null: PCM, read
 * with no codec, [Pcm]); [delay] and [padding], the encoder's frames the container stated and were trimmed; the
 * decoder's output, [encoding] ("float" or "16-bit"). */
data class Decoded(
    val rate: Int, val frames: Long, val channels: Int, val durationS: Double?, val codec: String? = null,
    val delay: Int = 0, val padding: Int = 0, val encoding: String = "float",
)

/** An audio file the phone can't decode: its words say why. */
class UndecodableAudio(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * An audio file decoded as the computer decodes it (autochords/audio.py `load_mono` at the file's own rate: the
 * chords-on-the-phone design's §3.6 and its B1 decode gate, DecoderTest), into interleaved little-endian float32 PCM
 * written to a file, a buffer at a time, so that no song is held whole (its memory is its buffers', whatever the
 * song's length):
 *
 * - a WAV or an AIFF of PCM is read by [Pcm], with no codec, sample for sample libsndfile's;
 * - anything else through [MediaExtractor] and a software decoder ([softwareDecoder]: Android's own `c2.android.*`,
 *   never a vendor's, so two phones decode alike), asked for float PCM (16-bit where it gives only that, each sample
 *   over 32,768 as libsndfile's); a FLAC Android's extractor decodes itself (`audio/raw`), its PCM passed through as
 *   it gives it;
 * - the encoder's delay and padding the container states ([MediaFormat]'s `encoder-delay` and `encoder-padding`: an
 *   MP4's edit list, LAME's Xing header) trimmed here, as FFmpeg and libsndfile trim them, and taken out of the
 *   codec's format, which some versions' codecs trim by themselves;
 * - an MP3 whose first frame states none (no Xing or VBRI header) kept whole, as FFmpeg keeps it: Android's MP3
 *   decoder always drops its own delay, the first [MP3_DECODER_DELAY] samples it decodes, so it is given a frame of
 *   silence first ([silentFrame]), whose samples it drops, and the silence it pads at the end is cut;
 * - an AAC with no loudness normalization or dynamic range control, which Android's AAC decoder applies by default;
 * - what the decoder gives past the container's stated length cut there, within [TAIL_WITHIN] (the last Ogg page's
 *   samples past its granule position, which libsndfile cuts).
 *
 * [Decoded.durationS] is the container's length; where it is more than [GUESS_OFF] seconds from the frames decoded
 * (an MP3 with no Xing or VBRI header, whose length an extractor may guess from its first frame, as mutagen did before
 * mpeg_frames.py), the frames' length, as music.py `read_audio` counts its frames.
 */
object Decoder {
    /** How far the container's length may be from the decoded frames' before it is a guess: audio.py's
     * `DISAGREES_S`. */
    const val GUESS_OFF = 0.5

    /** The most a decoder may give past the stated length and be cut back to it: an Ogg page's last packet. */
    const val TAIL_WITHIN = 0.05

    private const val TIMEOUT_US = 10_000L

    /** Android's software MP3 decoder's delay (PV MP3's `kPVMP3DecoderDelay`), which it drops itself. */
    const val MP3_DECODER_DELAY = 529

    /** The decoders that drop it: Android's own, Codec2's and OMX's. */
    private val DROPS_MP3_DELAY = setOf("c2.android.mp3.decoder", "OMX.google.mp3.decoder")

    fun decode(file: File, into: File): Decoded {
        if (!file.isFile) throw UndecodableAudio("no audio file: $file")
        Pcm.format(file)?.let { return pcm(file, it, into) }
        return coded(file, into)
    }

    private fun pcm(file: File, format: Pcm.Format, into: File): Decoded {
        FloatWriter(into).use { out -> Pcm.read(file, format) { block, n -> out.write(block, n) } }
        return Decoded(format.rate, format.frames, format.channels, format.seconds)
    }

    private fun coded(file: File, into: File): Decoded {
        val extractor = MediaExtractor()
        try {
            try {
                extractor.setDataSource(file.path)
            } catch (e: IOException) {
                throw UndecodableAudio("not audio the phone reads: ${e.message}", e)
            }
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME).orEmpty().startsWith("audio/")
            } ?: throw UndecodableAudio("no audio track")
            extractor.selectTrack(track)
            val format = extractor.getTrackFormat(track)
            val mime = format.getString(MediaFormat.KEY_MIME)!!
            val name = softwareDecoder(mime) ?: throw UndecodableAudio("no software decoder of $mime here")
            val stated = if (format.containsKey(MediaFormat.KEY_DURATION)) format.getLong(MediaFormat.KEY_DURATION)
            else null
            val delay = intOf(format, "encoder-delay")
            val padding = intOf(format, "encoder-padding")
            // Trimmed here, never by the codec: the platform's codecs of some versions trim what the format names
            // themselves (Android 15's emulator does), others not; each would be trimmed twice.
            format.removeKey("encoder-delay")
            format.removeKey("encoder-padding")
            // A codec asked for float PCM where it gives it; never audio/raw's (a FLAC, which Android's extractor
            // decodes itself), whose encoding is the extractor's, passed through.
            if (mime != MediaFormat.MIMETYPE_AUDIO_RAW) {
                format.setInteger(MediaFormat.KEY_PCM_ENCODING, android.media.AudioFormat.ENCODING_PCM_FLOAT)
            }
            if (mime == MediaFormat.MIMETYPE_AUDIO_AAC) aacAsDecoded(format)
            val codec = MediaCodec.createByCodecName(name)
            try {
                codec.configure(format, null, null, 0)
                codec.start()
                return FloatWriter(into).use { out ->
                    // Android's software MP3 decoder drops its own delay, the first 529 samples it decodes, and pads
                    // as many silent ones at the end. A file whose header states the encoder's delay is trimmed by
                    // it with those 529 already gone, as libsndfile trims it. One that states none FFmpeg keeps
                    // whole, those 529 first (a loud first frame's pre-echo, never silence): so the decoder is given
                    // a frame of digital silence first (silentFrame), whose samples are the ones it drops and the
                    // rest of them skipped, and the 529 silent ones it pads cut.
                    val silence = if (mime == MediaFormat.MIMETYPE_AUDIO_MPEG && delay == 0 && padding == 0 &&
                        name in DROPS_MP3_DELAY) silentFrame(extractor) else null
                    val skip = if (silence != null) silence.second - MP3_DECODER_DELAY else delay
                    val cut = if (silence != null) MP3_DECODER_DELAY else padding
                    val (rate, channels, encoding) = drain(extractor, codec, out, skip, silence?.first)
                    var frames = out.samples / channels - cut
                    if (frames < 0) frames = 0
                    val statedFrames = stated?.let { Math.round(it * rate / 1e6) }
                    if (statedFrames != null && frames > statedFrames && frames - statedFrames <= TAIL_WITHIN * rate) {
                        frames = statedFrames
                    }
                    out.cut(frames * channels)
                    val seconds = frames.toDouble() / rate
                    val container = stated?.let { it / 1e6 }
                    val duration = if (container != null && kotlin.math.abs(container - seconds) <= GUESS_OFF) container
                    else seconds
                    Decoded(rate, frames, channels, duration, name, delay, padding, encoding)
                }
            } catch (e: MediaCodec.CodecException) {
                throw UndecodableAudio("$name couldn't decode it: ${e.diagnosticInfo}", e)
            } catch (e: IllegalStateException) {
                throw UndecodableAudio("$name couldn't decode it: ${e.message}", e)
            } finally {
                codec.release()
            }
        } finally {
            extractor.release()
        }
    }

    /** Feeds [first] (where given), then every sample of the track, through [codec], skipping the first [delay]
     * frames it gives; the output's rate, channels and encoding. */
    private fun drain(extractor: MediaExtractor, codec: MediaCodec, out: FloatWriter, delay: Int,
                      first: ByteArray?): Triple<Int, Int, String> {
        val info = MediaCodec.BufferInfo()
        var inputDone = false
        var rate = 0
        var channels = 0
        var float = false
        var skip = delay.toLong()
        var primed = first == null
        while (true) {
            if (!inputDone) {
                val i = codec.dequeueInputBuffer(TIMEOUT_US)
                if (i >= 0 && !primed) {
                    codec.getInputBuffer(i)!!.put(first!!)
                    codec.queueInputBuffer(i, 0, first.size, 0, 0)
                    primed = true
                } else if (i >= 0) {
                    val buffer = codec.getInputBuffer(i)!!
                    val n = extractor.readSampleData(buffer, 0)
                    if (n < 0) {
                        codec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        inputDone = true
                    } else {
                        codec.queueInputBuffer(i, 0, n, extractor.sampleTime, 0)
                        extractor.advance()
                    }
                }
            }
            val o = codec.dequeueOutputBuffer(info, TIMEOUT_US)
            if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                val f = codec.outputFormat
                rate = f.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                channels = f.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                float = intOf(f, MediaFormat.KEY_PCM_ENCODING) == android.media.AudioFormat.ENCODING_PCM_FLOAT
            } else if (o >= 0) {
                if (channels == 0) {
                    val f = codec.getOutputFormat(o)
                    rate = f.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                    channels = f.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    float = intOf(f, MediaFormat.KEY_PCM_ENCODING) == android.media.AudioFormat.ENCODING_PCM_FLOAT
                }
                val buffer = codec.getOutputBuffer(o)!!.order(ByteOrder.nativeOrder())
                buffer.position(info.offset).limit(info.offset + info.size)
                val bytesPerFrame = (if (float) 4 else 2) * channels
                val skipped = minOf(skip, (info.size / bytesPerFrame).toLong()).toInt()
                skip -= skipped
                buffer.position(info.offset + skipped * bytesPerFrame)
                out.write(buffer, float)
                codec.releaseOutputBuffer(o, false)
                if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
            }
        }
        if (channels == 0 || rate == 0) throw UndecodableAudio("the decoder gave no audio")
        return Triple(rate, channels, if (float) "float" else "16-bit")
    }

    /**
     * A Layer III frame of digital silence of the track's first frame's kind (its version, rate, bitrate, padding and
     * channel mode, no CRC: so of its size), and the samples it decodes to (1,152 for MPEG-1, 576 for MPEG-2 and
     * 2.5); null where the track's first sample is no Layer III frame. Its side information is all zeros: no granule
     * holds a bit, so it decodes to zeros and leaves the decoder's state as it began, zeros, and the frame after it
     * reads no reservoir it lacks (a stream's first frame begins its main data in itself).
     */
    internal fun silentFrame(extractor: MediaExtractor): Pair<ByteArray, Int>? {
        val head = ByteBuffer.allocate(64 * 1024)
        if (extractor.readSampleData(head, 0) < 4) return null
        return silentFrame(byteArrayOf(head.get(0), head.get(1), head.get(2), head.get(3)))
    }

    internal fun silentFrame(header: ByteArray): Pair<ByteArray, Int>? {
        val b1 = header[1].toInt() and 0xFF
        val b2 = header[2].toInt() and 0xFF
        if (header[0].toInt() and 0xFF != 0xFF || b1 and 0xE0 != 0xE0) return null
        val version = (b1 shr 3) and 3
        val layer = (b1 shr 1) and 3
        val index = b2 shr 4
        val rateBits = (b2 shr 2) and 3
        if (layer != 1 || version == 1 || index == 0 || index == 15 || rateBits == 3) return null  // 1: Layer III
        val mpeg1 = version == 3
        val kbps = (if (mpeg1) MPEG1_L3_KBPS else MPEG2_L3_KBPS)[index - 1]
        val rates = when (version) { 3 -> intArrayOf(44100, 48000, 32000); 2 -> intArrayOf(22050, 24000, 16000)
            else -> intArrayOf(11025, 12000, 8000) }
        val hz = rates[rateBits]
        val pad = (b2 shr 1) and 1
        val size = (if (mpeg1) 144 else 72) * kbps * 1000 / hz + pad
        val frame = ByteArray(size)
        frame[0] = 0xFF.toByte()
        frame[1] = (b1 or 1).toByte()  // no CRC
        frame[2] = header[2]
        frame[3] = header[3]
        return frame to if (mpeg1) 1152 else 576
    }

    private val MPEG1_L3_KBPS = intArrayOf(32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
    private val MPEG2_L3_KBPS = intArrayOf(8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)

    /** An AAC decoded as it is coded, as FFmpeg decodes it: no loudness normalization, no dynamic range control
     * (Android's AAC decoder applies both by default, toward a phone speaker's level). */
    private fun aacAsDecoded(format: MediaFormat) {
        format.setInteger(MediaFormat.KEY_AAC_DRC_TARGET_REFERENCE_LEVEL, -1)
        format.setInteger(MediaFormat.KEY_AAC_DRC_HEAVY_COMPRESSION, 0)
        format.setInteger(MediaFormat.KEY_AAC_DRC_BOOST_FACTOR, 0)
        format.setInteger(MediaFormat.KEY_AAC_DRC_ATTENUATION_FACTOR, 0)
        if (Build.VERSION.SDK_INT >= 28) format.setInteger(MediaFormat.KEY_AAC_DRC_EFFECT_TYPE, -1)
    }

    /** The software decoder of [mime], Android's own (`c2.android.*` first), or null for none. */
    fun softwareDecoder(mime: String): String? {
        val decoders = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { info ->
            !info.isEncoder && info.supportedTypes.any { it.equals(mime, ignoreCase = true) } && software(info)
        }.map { it.name }
        return decoders.firstOrNull { it.startsWith("c2.android.") } ?: decoders.firstOrNull()
    }

    private fun software(info: MediaCodecInfo): Boolean =
        if (Build.VERSION.SDK_INT >= 29) info.isSoftwareOnly && !info.isVendor
        else info.name.startsWith("OMX.google.") || info.name.startsWith("c2.android.")

    private fun intOf(format: MediaFormat, key: String): Int =
        if (format.containsKey(key)) format.getInteger(key) else 0

    /** Interleaved little-endian float32 into a file, a buffer at a time. */
    private class FloatWriter(file: File) : AutoCloseable {
        private val channel = FileChannel.open(file.toPath(), StandardOpenOption.WRITE, StandardOpenOption.CREATE,
            StandardOpenOption.TRUNCATE_EXISTING)
        private val bytes = ByteBuffer.allocate(1 shl 16).order(ByteOrder.LITTLE_ENDIAN)
        var samples = 0L
            private set

        fun write(block: FloatArray, n: Int) {
            for (i in 0 until n) put(block[i])
        }

        /** A decoder's output buffer of float or 16-bit samples, in the platform's order. */
        fun write(buffer: ByteBuffer, float: Boolean) {
            if (float) while (buffer.remaining() >= 4) put(buffer.float)
            else while (buffer.remaining() >= 2) put(buffer.short * (1f / 32768f))
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
}
