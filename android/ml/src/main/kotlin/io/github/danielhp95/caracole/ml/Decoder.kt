package io.github.danielhp95.caracole.ml

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import io.github.danielhp95.caracole.autochords.frontend.Mp4
import io.github.danielhp95.caracole.autochords.frontend.MpegHeader
import io.github.danielhp95.caracole.autochords.frontend.Ogg
import io.github.danielhp95.caracole.autochords.frontend.Pcm
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer

/**
 * What [Decoder.decode] wrote: [frames] frames of [channels] at [rate] Hz; [codec], the decoder that ran (null: PCM,
 * read with no codec, [Pcm]); the frames trimmed off its start ([delay]) and its end ([padding]); the decoder's output,
 * [encoding] ([PcmEncoding.words], "float" for PCM read with no codec).
 *
 * [durationS] is the length music.py `read_audio` states for the same file, by the computer's own rule for its
 * container, the one an auto sheet is laid over:
 * - an MP4 (M4A): its sound track's `mdhd` duration over its timescale, read from its boxes ([Mp4]), as mutagen reads
 *   it: the encoder's priming and padding counted in, so a little longer than what is decoded; a fragmented one's
 *   (yt-dlp's m4a on the phone, with no FFmpeg to remux it), its fragments' length, which the computer's remux of it
 *   states ([Mp4.Track.statedSeconds]);
 * - an MP3 whose first frame has a Xing header with a frame count, or a VBRI header: what [MpegHeader] reads of it as
 *   mutagen does (a LAME tag's delay and padding taken off where mutagen reads the tag);
 * - an MP3 whose first frame names no length: the frames decoded over the rate, which is mpeg_frames.py's count of
 *   its frames, every frame being decoded (none trimmed) and Android's MP3 decoder giving each frame's samples;
 * - an Ogg (Vorbis, Opus), a FLAC, a WAV, an AIFF: the frames decoded over the rate, which is mutagen's (the last
 *   granule's less Opus's pre-skip, the STREAMINFO's, the header's), the decode being trimmed to it.
 */
data class Decoded(
    val rate: Int, val frames: Long, val channels: Int, val durationS: Double?, val codec: String? = null,
    val delay: Long = 0, val padding: Long = 0, val encoding: String = PcmEncoding.FLOAT.words,
)

/**
 * An audio file decoded as the computer decodes it (autochords/audio.py `load_mono` at the file's own rate: the
 * chords-on-the-phone design's §3.6 and its B1 decode gate, DecoderTest), into interleaved little-endian float32 PCM
 * written to a file, a buffer at a time, so that no song is held whole (its memory is its buffers', whatever the
 * song's length). On any failure the partial [decode]'s `into` is deleted, and the failure is [UndecodableAudio] in
 * words (a codec that can't be made or configured, a header cut short among them).
 *
 * - A WAV or an AIFF of PCM is read by [Pcm], with no codec, sample for sample libsndfile's.
 * - Anything else through [MediaExtractor], its first audio track (where FFmpeg takes its "best" one: a file of one
 *   audio track, as every file caracole keeps, reads the same), and Android's own software decoder
 *   ([softwareDecoder]: `c2.android.*`, never a vendor's), asked for float PCM, its output read in the encoding it
 *   names ([PcmEncoding]: an encoding caracole doesn't read refused, never read as 16-bit); a FLAC Android's
 *   extractor decodes itself (`audio/raw`) is passed through in the extractor's encoding.
 * - Trimmed as the computer trims ([Trim]), never by the codec: where the format names the encoder's delay and
 *   padding (`encoder-delay`, `encoder-padding`), the framework's codecs may trim them themselves (this emulator's
 *   do), so caracole takes both keys out of the codec's format and trims here:
 *   - an MP4 with one media edit: from the edit's media time, exactly as many samples as its length, as FFmpeg
 *     trims it, whatever the last frame's padding ([Mp4]), counted in the `mdhd` timescale and made the output's
 *     ([Trim.at]: a decoder that doubles the rate gives twice as many; a rate they can't be rescaled to exactly
 *     falls to the stated delay and padding);
 *   - a fragmented MP4 with no edit list (yt-dlp's m4a with no FFmpeg): as the computer's remux of it decodes
 *     (yt-dlp's FixupM4a, `ffmpeg -c copy -f mp4`): nothing skipped, the encoder's priming kept (no box names it), and
 *     ended at its fragments' length ([Mp4.Track.fragments]), the last frame's padding past it cut; one whose
 *     fragments can't be read (a download cut short) refused, never stated as 0 or cut to nothing ([fragmentsKeep]);
 *   - an MP3: Android's MP3 decoder ([DROPS_MP3_DELAY], the decoders measured; any other refused) always drops its
 *     own delay, the first [MP3_DECODER_DELAY] samples it decodes, and pads as many silent ones at the end. A LAME
 *     tag's
 *     delay and padding are trimmed after it (libsndfile's trim with those 529 already gone); a file whose first frame
 *     states none FFmpeg keeps whole, those 529 first, so the decoder is given a frame of digital silence first
 *     ([silentFrame]), whose samples it drops, and the silence it pads is cut;
 *   - an Ogg (Vorbis, Opus): to its last page's granule position, less Opus's pre-skip ([Ogg]), as libsndfile ends
 *     it: the decoder gives its last packet whole (Opus: 648 samples past it here); Opus's pre-skip the decoder drops
 *     itself;
 *   - anything else (a FLAC) by the delay and padding its format names, none.
 * - An AAC asked for no loudness normalization and no dynamic range control, which Android's AAC decoder applies by
 *   default ([aacAsDecoded]): untested here, the fixtures carrying no loudness metadata.
 */
object Decoder {
    /** Android's software MP3 decoder's delay (PV MP3's `kPVMP3DecoderDelay`), which it drops itself. */
    const val MP3_DECODER_DELAY = 529

    /** The MP3 decoders whose dropping of [MP3_DECODER_DELAY] and padding of as many silent samples DecoderTest
     * measured: Android's own, Codec2's and OMX's. */
    val DROPS_MP3_DELAY = setOf("c2.android.mp3.decoder", "OMX.google.mp3.decoder")

    /** [file] decoded into [into]; [check] called as it goes (each buffer, each block: a cancel, which ends it). */
    fun decode(file: File, into: File, check: () -> Unit = {}): Decoded {
        if (!file.isFile) throw UndecodableAudio("no audio file: $file")
        try {
            val format = try {
                Pcm.format(file)
            } catch (e: Pcm.Unreadable) {
                throw UndecodableAudio("a WAV or AIFF caracole can't read: ${e.message}", e)
            }
            return if (format != null) pcm(file, format, into, check) else coded(file, into, check)
        } catch (e: Throwable) {
            into.delete()
            throw e
        }
    }

    private fun pcm(file: File, format: Pcm.Format, into: File, check: () -> Unit): Decoded {
        FloatWriter(into).use { out -> Pcm.read(file, format) { block, n -> check(); out.write(block, n) } }
        return Decoded(format.rate, format.frames, format.channels, format.seconds)
    }

    private fun coded(file: File, into: File, check: () -> Unit): Decoded {
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
            val delay = intOf(format, "encoder-delay")
            val padding = intOf(format, "encoder-padding")
            val rate = intOf(format, MediaFormat.KEY_SAMPLE_RATE)
            format.removeKey("encoder-delay")
            format.removeKey("encoder-padding")
            if (mime != MediaFormat.MIMETYPE_AUDIO_RAW) {
                format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_FLOAT)
            }
            if (mime == MediaFormat.MIMETYPE_AUDIO_AAC) aacAsDecoded(format)
            val mp4 = if (mime == MediaFormat.MIMETYPE_AUDIO_AAC) {
                readContainer("its MP4 boxes") { Mp4.audioTrack(file) }
            } else null
            val mp3 = mime == MediaFormat.MIMETYPE_AUDIO_MPEG
            if (mp3 && name !in DROPS_MP3_DELAY) {
                throw UndecodableAudio("$name is an MP3 decoder caracole hasn't measured")
            }
            val silence = if (mp3 && delay == 0 && padding == 0) silentFrame(extractor) else null
            // The edit's and the granule's counts are in their own timescale's samples, the stated delay and padding
            // in the extractor's rate's: [Trim.at] makes each the output's, whose rate a decoder may double (an AAC's
            // implicit SBR), or drops it where it can't be made so exactly, never applied as it is.
            val edit = mp4?.edit()?.takeIf { mp4.timescale in 1..Int.MAX_VALUE }
            val ogg = if (mime == MediaFormat.MIMETYPE_AUDIO_OPUS || mime == MediaFormat.MIMETYPE_AUDIO_VORBIS) {
                readContainer("its Ogg pages") { Ogg.stream(file) }
            } else null
            val fragments = fragmentsKeep(mp4)
            val trim = when {
                edit != null -> Trim.edit(edit.mediaTime, readContainer("its edit list") { mp4.keptFrames(edit) },
                    mp4.timescale.toInt(), fallback = Trim.stated(delay, padding, rate))
                fragments != null -> Trim(skip = 0, keep = fragments, rate = mp4!!.timescale.toInt(),
                    fallback = Trim.stated(delay, padding, rate))
                ogg != null -> Trim(skip = delay.toLong(), keep = ogg.frames, rate = ogg.rate,
                    fallback = Trim.stated(delay, padding, rate))
                silence != null -> Trim(skip = (silence.second - MP3_DECODER_DELAY).toLong(),
                    cutEnd = MP3_DECODER_DELAY.toLong())
                else -> Trim.stated(delay, padding, rate)
            }
            val codec = try {
                MediaCodec.createByCodecName(name)
            } catch (e: IOException) {
                throw UndecodableAudio("$name can't be made here: ${e.message}", e)
            } catch (e: IllegalArgumentException) {
                throw UndecodableAudio("$name can't be made here: ${e.message}", e)
            }
            try {
                try {
                    codec.configure(format, null, null, 0)
                } catch (e: IllegalArgumentException) {
                    throw UndecodableAudio("$name refused the track's format: ${e.message}", e)
                }
                codec.start()
                return FloatWriter(into).use { out ->
                    val result = CodecLoop().run(Port(codec), Source(extractor), out, { r -> trim.at(r).skip },
                        silence?.first, check)
                    val applied = trim.at(result.rate)
                    val given = out.samples / result.channels
                    val frames = applied.frames(given)
                    out.cut(frames * result.channels)
                    val seconds = frames.toDouble() / result.rate
                    val stated = when {
                        mp4 != null -> mp4.statedSeconds
                        mp3 -> readContainer("its first MPEG frame") { MpegHeader.statedLength(file) } ?: seconds
                        else -> seconds
                    }
                    Decoded(result.rate, frames, result.channels, stated, name, applied.skip, given - frames,
                        result.encoding.words)
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

    /** [MediaCodec] as [CodecLoop] asks it. */
    private class Port(private val codec: MediaCodec) : CodecPort {
        private val info = MediaCodec.BufferInfo()
        override fun dequeueInput(timeoutUs: Long) = codec.dequeueInputBuffer(timeoutUs)
        override fun inputBuffer(index: Int): ByteBuffer = codec.getInputBuffer(index)!!
        override fun queueInput(index: Int, size: Int, timeUs: Long, endOfStream: Boolean) =
            codec.queueInputBuffer(index, 0, size, timeUs, if (endOfStream) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0)
        override fun dequeueOutput(timeoutUs: Long, into: OutBuffer): Int {
            val o = codec.dequeueOutputBuffer(info, timeoutUs)
            if (o >= 0) {
                into.offset = info.offset
                into.size = info.size
                into.endOfStream = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
            }
            return when (o) {
                MediaCodec.INFO_TRY_AGAIN_LATER -> CodecPort.TRY_AGAIN
                MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> CodecPort.FORMAT_CHANGED
                @Suppress("DEPRECATION") MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> CodecPort.BUFFERS_CHANGED
                else -> o
            }
        }
        override fun outputFormat() = of(codec.outputFormat)
        override fun outputFormat(index: Int) = of(codec.getOutputFormat(index))
        override fun outputBuffer(index: Int): ByteBuffer = codec.getOutputBuffer(index)!!
        override fun releaseOutput(index: Int) = codec.releaseOutputBuffer(index, false)

        private fun of(f: MediaFormat) = OutFormat(intOf(f, MediaFormat.KEY_SAMPLE_RATE),
            intOf(f, MediaFormat.KEY_CHANNEL_COUNT),
            if (f.containsKey(MediaFormat.KEY_PCM_ENCODING)) f.getInteger(MediaFormat.KEY_PCM_ENCODING) else null)
    }

    /** [MediaExtractor] as [CodecLoop] asks it. */
    private class Source(private val extractor: MediaExtractor) : SamplePort {
        override fun read(into: ByteBuffer) = extractor.readSampleData(into, 0)
        override fun timeUs() = extractor.sampleTime
        override fun advance() {
            extractor.advance()
        }
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
        val rates = when (version) {
            3 -> intArrayOf(44100, 48000, 32000)
            2 -> intArrayOf(22050, 24000, 16000)
            else -> intArrayOf(11025, 12000, 8000)
        }
        val pad = (b2 shr 1) and 1
        val size = (if (mpeg1) 144 else 72) * kbps * 1000 / rates[rateBits] + pad
        val frame = ByteArray(size)
        frame[0] = 0xFF.toByte()
        frame[1] = (b1 or 1).toByte()  // no CRC
        frame[2] = header[2]
        frame[3] = header[3]
        return frame to if (mpeg1) 1152 else 576
    }

    private val MPEG1_L3_KBPS = intArrayOf(32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
    private val MPEG2_L3_KBPS = intArrayOf(8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)

    /** An AAC decoded as it is coded, as FFmpeg decodes it: no loudness normalization, no dynamic range control,
     * which Android's AAC decoder applies by default toward a phone speaker's level. Untested here: no fixture carries
     * loudness metadata. */
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
}
