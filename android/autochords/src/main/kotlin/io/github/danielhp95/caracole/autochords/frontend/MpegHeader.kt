package io.github.danielhp95.caracole.autochords.frontend

import java.io.File
import java.io.RandomAccessFile

/**
 * The length an MP3's first frame states, as mutagen reads it (music.py `read_audio`'s; mutagen 1.48's `MPEGFrame`
 * `_parse_vbr_header`), or none where it states none:
 *
 * - its first frame: after any ID3v2 tags (stacked, a footer by its flag), zero bytes passed over (mpeg_frames.py's
 *   `_first` for a file with no tag) or, after tags, the first frame within [FIRST_WITHIN] that another follows;
 *   Layer III alone, as mutagen reads a VBR header of no other layer;
 * - a Xing or Info header at mutagen's offset (36 or 21 bytes for MPEG-1, stereo or mono; 21 or 13 for MPEG-2 and
 *   2.5) with its frame count: that many frames of 1,152 samples (MPEG-1) or 576 (MPEG-2, 2.5), less a LAME tag's
 *   encoder delay and padding where mutagen reads one ([lameHeaderFollows], its `LAMEHeader.parse_version`: a version
 *   string of LAME 3.90 or later, a revision 0), never under 0, over the rate. FFmpeg's own tag ("Lavf") is no LAME
 *   tag: its delay and padding are counted in;
 * - a Xing header with no frame count is none: read_audio counts the frames (mpeg_frames.py), as for a file with no
 *   header;
 * - else a VBRI header (version 1, its table whole, entries of 2 or 4 bytes) 36 bytes in: its frames over the rate.
 *   (A VBRI header mutagen refuses leaves read_audio mutagen's guess, which is not read here: none, a case caracole
 *   has never met.)
 */
object MpegHeader {
    const val FIRST_WITHIN = 64 * 1024

    private val RATES = mapOf(3 to intArrayOf(44100, 48000, 32000), 2 to intArrayOf(22050, 24000, 16000),
        0 to intArrayOf(11025, 12000, 8000))
    private val KBPS_MPEG1 = intArrayOf(32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
    private val KBPS_MPEG2 = intArrayOf(8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)

    private class Frame(val at: Int, val version: Int, val mono: Boolean, val rate: Int, val size: Int) {
        val mpeg1: Boolean get() = version == 3
        val samples: Int get() = if (mpeg1) 1152 else 576
        val xingOffset: Int get() = if (mpeg1) (if (mono) 21 else 36) else (if (mono) 13 else 21)
    }

    /** The length in seconds [file]'s first frame states, as mutagen reads it, or null. */
    fun statedLength(file: File): Double? {
        val bytes = RandomAccessFile(file, "r").use { f ->
            val n = minOf(f.length(), (FIRST_WITHIN * 2 + 1024 * 1024).toLong()).toInt()
            ByteArray(n).also { f.readFully(it) }
        }
        val frame = first(bytes) ?: return null
        val xing = frame.at + frame.xingOffset
        if (has(bytes, xing, "Xing") || has(bytes, xing, "Info")) return xingLength(bytes, xing, frame)
        return vbriLength(bytes, frame.at + 36, frame)
    }

    private fun xingLength(b: ByteArray, at: Int, frame: Frame): Double? {
        if (at + 8 > b.size) return null
        val flags = u32(b, at + 4)
        var p = at + 8
        var frames = -1L
        if (flags and 1L != 0L) { if (p + 4 > b.size) return null; frames = u32(b, p); p += 4 }
        if (flags and 2L != 0L) { if (p + 4 > b.size) return null; p += 4 }
        if (flags and 4L != 0L) { if (p + 100 > b.size) return null; p += 100 }
        if (flags and 8L != 0L) { if (p + 4 > b.size) return null; p += 4 }
        if (frames == -1L) return null
        var samples = frame.samples * frames
        if (p + 20 <= b.size && lameHeaderFollows(b.copyOfRange(p, p + 20)) == true) {
            // the LAME header's 27 bytes begin after the 9 of its version (mutagen reads 20, then 11 back)
            val payload = p + 9
            if (payload + 27 <= b.size && (b[payload].toInt() and 0xF0) == 0) {
                val delay = ((b[payload + 12].toInt() and 0xFF) shl 4) or ((b[payload + 13].toInt() and 0xF0) shr 4)
                val padding = ((b[payload + 13].toInt() and 0x0F) shl 8) or (b[payload + 14].toInt() and 0xFF)
                samples -= delay + padding
                if (samples < 0) samples = 0
            }
        }
        return samples.toDouble() / frame.rate
    }

    private fun vbriLength(b: ByteArray, at: Int, frame: Frame): Double? {
        if (at + 26 > b.size || !has(b, at, "VBRI") || u16(b, at + 4) != 1) return null
        val frames = u32(b, at + 14)
        val entries = u16(b, at + 18)
        val entrySize = u16(b, at + 22)
        if (at + 26 + entries * entrySize > b.size || (entrySize != 2 && entrySize != 4)) return null
        return (frame.samples * frames).toDouble() / frame.rate
    }

    /**
     * Whether a LAME header follows these 20 bytes after a Xing header, as mutagen's `LAMEHeader.parse_version`
     * decides it: true, a header; false, a version string of LAME before 3.90 (or a 3.90 alpha), no header; null, no
     * LAME version at all (mutagen's LAMEError), as FFmpeg's "Lavf" is.
     */
    fun lameHeaderFollows(d: ByteArray): Boolean? {
        if (d.size != 20 || !(starts(d, "LAME") || starts(d, "L3.99"))) return null
        var s = d.dropWhile { it == 'E'.code.toByte() || it == 'M'.code.toByte() || it == 'A'.code.toByte() ||
            it == 'L'.code.toByte() }
        if (s.isEmpty()) return null
        val major = digit(s[0]) ?: return null
        s = s.drop(1).dropWhile { it == '.'.code.toByte() }
        val minorDigits = s.takeWhile { digit(it) != null }
        if (minorDigits.isEmpty()) return null
        val minor = minorDigits.fold(0) { n, c -> n * 10 + digit(c)!! }
        s = s.drop(minorDigits.size)
        val alpha = s.size >= 11 && s[s.size - 11] == '('.code.toByte()
        if (major < 3 || (major == 3 && minor < 90) || (major == 3 && minor == 90 && alpha)) return false
        if (s.size < 11) return null
        return true
    }

    private fun digit(b: Byte): Int? = (b - '0'.code.toByte()).takeIf { it in 0..9 }

    private fun first(b: ByteArray): Frame? {
        var start = 0
        while (start + 10 <= b.size && has(b, start, "ID3")) {
            val size = ((b[start + 6].toInt() and 0x7F) shl 21) or ((b[start + 7].toInt() and 0x7F) shl 14) or
                ((b[start + 8].toInt() and 0x7F) shl 7) or (b[start + 9].toInt() and 0x7F)
            start += 10 + size + (if (b[start + 5].toInt() and 0x10 != 0) 10 else 0)
        }
        if (start == 0) {
            var at = 0
            while (at < minOf(b.size, FIRST_WITHIN) && b[at].toInt() == 0) at++
            return frame(b, at)?.takeIf { followed(b, it) }
        }
        for (at in start until minOf(b.size, start + FIRST_WITHIN)) {
            val f = frame(b, at) ?: continue
            if (followed(b, f)) return f
        }
        return null
    }

    private fun followed(b: ByteArray, f: Frame): Boolean {
        val next = f.at + f.size
        if (next == b.size) return true
        val n = frame(b, next) ?: return false
        return n.version == f.version && n.rate == f.rate
    }

    private fun frame(b: ByteArray, at: Int): Frame? {
        if (at + 4 > b.size || b[at].toInt() and 0xFF != 0xFF) return null
        val b1 = b[at + 1].toInt() and 0xFF
        val b2 = b[at + 2].toInt() and 0xFF
        if (b1 and 0xE0 != 0xE0) return null
        val version = (b1 shr 3) and 3
        val layer = (b1 shr 1) and 3
        val index = b2 shr 4
        val rateBits = (b2 shr 2) and 3
        if (layer != 1 || version == 1 || index == 0 || index == 15 || rateBits == 3) return null
        val rate = RATES.getValue(version)[rateBits]
        val kbps = (if (version == 3) KBPS_MPEG1 else KBPS_MPEG2)[index - 1]
        val pad = (b2 shr 1) and 1
        val size = (if (version == 3) 144 else 72) * kbps * 1000 / rate + pad
        val mono = (b[at + 3].toInt() and 0xFF) shr 6 == 3
        return Frame(at, version, mono, rate, size)
    }

    private fun has(b: ByteArray, at: Int, id: String): Boolean =
        at >= 0 && at + id.length <= b.size && id.indices.all { b[at + it] == id[it].code.toByte() }

    private fun starts(b: ByteArray, id: String): Boolean = has(b, 0, id)

    private fun u32(b: ByteArray, at: Int): Long =
        ((b[at].toLong() and 0xFF) shl 24) or ((b[at + 1].toLong() and 0xFF) shl 16) or
            ((b[at + 2].toLong() and 0xFF) shl 8) or (b[at + 3].toLong() and 0xFF)

    private fun u16(b: ByteArray, at: Int): Int = ((b[at].toInt() and 0xFF) shl 8) or (b[at + 1].toInt() and 0xFF)
}
