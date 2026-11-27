package io.github.danielhp95.caracole.autochords.frontend

import java.io.File
import java.io.RandomAccessFile

/**
 * An audio file's length as the computer's audio store reads it (audio_store._read: mutagen's `info.length`, an MP3's
 * its frames' count where its first frame names none), for each format the store keeps, from the file's own headers
 * alone, never a decode: the phone's examiner of an upload (the chords-on-the-phone design's §8.2), which hands the
 * store a spool named with no audio extension, so the format it is given says how to read it.
 *
 * - MP3: [MpegFrames]' count where the first frame names no length, else what that frame states ([MpegHeader]);
 * - M4A: the sound track's `mdhd` ([Mp4]); none for a file with no sound track (a video alone, which the store
 *   refuses: mutagen reads it as long as its movie, audio_store's `soun` check);
 * - FLAC: STREAMINFO's samples over its rate ([flac]);
 * - Ogg: the last granule, less Opus's pre-skip, over the rate ([Ogg]);
 * - WAV, AIFF: their frames over their rate ([Pcm]).
 *
 * None where the headers can't be read as that format; an IOException is the disk's.
 */
object AudioLengths {
    fun of(file: File, format: String): Double? = when (format) {
        "MP3" -> MpegFrames.countedLength(file)?.takeIf { it != 0.0 } ?: MpegHeader.statedLength(file)
        "M4A" -> Mp4.audioTrack(file)?.takeIf { it.sound }?.seconds
        "FLAC" -> flac(file)
        "Ogg" -> Ogg.stream(file)?.let { if (it.rate > 0) it.frames.toDouble() / it.rate else null }
        "WAV", "AIFF" -> try {
            Pcm.format(file)?.seconds
        } catch (e: Pcm.Unreadable) {
            null
        }
        else -> null
    }

    /** mutagen's FLAC length: its STREAMINFO block's total samples over its rate, the block first after `fLaC` (an
     * ID3v2 tag before it passed over, as mutagen passes it); none with a rate of 0. */
    fun flac(file: File): Double? = RandomAccessFile(file, "r").use { f ->
        var start = 0L
        val head = ByteArray(10)
        while (start + 10 <= f.length()) {
            f.seek(start)
            f.readFully(head)
            if (head[0] != 'I'.code.toByte() || head[1] != 'D'.code.toByte() || head[2] != '3'.code.toByte()) break
            val size = ((head[6].toLong() and 0x7F) shl 21) or ((head[7].toLong() and 0x7F) shl 14) or
                ((head[8].toLong() and 0x7F) shl 7) or (head[9].toLong() and 0x7F)
            start += 10 + size
        }
        if (start + 4 + 4 + 18 > f.length()) return null
        val b = ByteArray(26)
        f.seek(start)
        f.readFully(b)
        if (String(b, 0, 4, Charsets.ISO_8859_1) != "fLaC" || b[4].toInt() and 0x7F != 0) return null
        val info = 8  // STREAMINFO: sizes (10 bytes), then 20 bits of rate, 3 of channels, 5 of bits, 36 of samples
        fun u(at: Int) = b[info + at].toLong() and 0xFF
        val rate = (u(10) shl 12) or (u(11) shl 4) or (u(12) shr 4)
        val samples = ((u(13) and 0x0F) shl 32) or (u(14) shl 24) or (u(15) shl 16) or (u(16) shl 8) or u(17)
        if (rate == 0L) null else samples.toDouble() / rate
    }
}
