package io.github.danielhp95.caracole.autochords.frontend

import java.io.File
import java.io.RandomAccessFile
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * What an MP4's boxes say of its sound, as the computer reads them:
 *
 * - its length, as mutagen's `MP4Info` reads it (music.py `read_audio`'s): the first `trak` whose `mdia/hdlr` handler
 *   is `soun`, its `mdia/mdhd` duration over its timescale (version 0's 32-bit fields, version 1's 64-bit duration;
 *   any other version none, as mutagen refuses it), else, with no sound track, the `mvhd`'s;
 * - its edit list (`edts/elst`), by which FFmpeg trims the decoded samples (libavformat's mov demuxer, autochords/
 *   audio.py `load_mono` reading an M4A through it): the samples from the one media edit's `media_time`, as many as
 *   its segment duration rescaled from the movie's timescale to the media's, never past the media's known length
 *   ([keptFrames], [Track.bound]);
 * - of a fragmented file (yt-dlp's m4a on the phone, which has no FFmpeg to remux it), the length of its fragments
 *   ([Track.fragments]): what FFmpeg's remux of it writes in its `mdhd` (yt-dlp's FixupM4a on the computer, `ffmpeg -c
 *   copy -f mp4`), so the computer's length of the same audio ([Track.statedSeconds]), and where its decode ends.
 *
 * Only the box headers are read on the way to `moov`, which is read whole (at most [MOOV_MOST]), and to each `moof` of
 * a fragmented file (each at most [MOOV_MOST]), never the samples.
 */
object Mp4 {
    const val MOOV_MOST = 16L * 1024 * 1024

    /** One entry of an edit list: its duration in the movie's timescale, and where it starts in the media's (-1 an
     * empty edit, a gap). */
    data class Edit(val segment: Long, val mediaTime: Long)

    /** The sound track: its `mdhd` timescale and duration (or the `mvhd`'s, with no sound track), the movie's
     * timescale, its edits, its sample table's total length (`stbl/stts`: each entry's count times its delta, in the
     * media's timescale; null where none is read, or past a Long), and whether the file is [fragmented] (an `mvex` in
     * its `moov`: its samples in `moof`s, the `mdhd` and `stts` commonly empty) and then its [fragments]' length. */
    data class Track(val timescale: Long, val duration: Long, val movieTimescale: Long, val edits: List<Edit>,
                     val samples: Long? = null, val fragmented: Boolean = false, val fragments: Long? = null) {
        /** mutagen's length: `float(duration) / timescale`, 0 for a timescale of 0. */
        val seconds: Double get() = if (timescale == 0L) 0.0 else duration.toDouble() / timescale

        /** The length the computer states of this audio as it holds it: mutagen's [seconds]; of a [fragmented] file,
         * which the computer's yt-dlp remuxes before anything reads it (FixupM4a), the remux's `mdhd`, its
         * [fragments]' length over the timescale, and none where that isn't read (never its empty `mdhd`'s 0). */
        val statedSeconds: Double?
            get() = when {
                !fragmented -> seconds
                fragments != null && timescale > 0 -> fragments.toDouble() / timescale
                else -> null
            }

        /** The one media edit (empty ones aside), or none: no list, several media edits, which are not trimmed
         * exactly here, or numbers that lead nowhere (a timescale of 0, a segment of no length or less, as a
         * fragmented file's commonly is: the stated delay applies then). */
        fun edit(): Edit? = edits.filter { it.mediaTime >= 0 }.singleOrNull()
            ?.takeIf { it.segment > 0 && timescale > 0 && movieTimescale > 0 }

        /** The media's length that bounds an edit, where it is known: none in a [fragmented] file; else the sample
         * table's total ([samples], what FFmpeg indexes the samples by) where it is read and positive, else `mdhd`'s
         * [duration] where positive, else none (an unknown length never trims the audio away). */
        val bound: Long? get() = when {
            fragmented -> null
            samples != null && samples > 0 -> samples
            samples == null && duration > 0 -> duration
            else -> null
        }

        /** The samples FFmpeg keeps of [edit]: its segment rescaled to the media's timescale (av_rescale), and never
         * more than the media holds from the edit's start ([bound] less its media time, where that is known): a
         * segment that runs past the media's last sample ends with it, the last frame's padding cut to its stated
         * duration (an M4A of 16,299,355 samples whose edit says 369.600 s, 16,299,360 of them: FFmpeg gives
         * 16,299,355); with no known bound, the segment alone. */
        fun keptFrames(edit: Edit): Long {
            val kept = rescale(edit.segment, timescale, movieTimescale)
            return bound?.let { minOf(kept, maxOf(0L, it - edit.mediaTime)) } ?: kept
        }
    }

    /** `a * b / c`, rounded to the nearest, halves away from zero, as FFmpeg's `av_rescale` rounds (a, b ≥ 0,
     * c > 0); an answer past a Long (a hostile segment) an [ArithmeticException], never wrapped. */
    fun rescale(a: Long, b: Long, c: Long): Long {
        require(a >= 0 && b >= 0 && c > 0) { "rescale($a, $b, $c)" }
        val product = BigInteger.valueOf(a).multiply(BigInteger.valueOf(b))
        return product.add(BigInteger.valueOf(c / 2)).divide(BigInteger.valueOf(c)).longValueExact()
    }

    /** [file]'s sound track as mutagen and FFmpeg read it, or null: no MP4, no `moov`, or one mutagen refuses. */
    fun audioTrack(file: File): Track? = RandomAccessFile(file, "r").use { f ->
        val moov = topLevel(f, "moov") ?: return null
        val movie = child(moov, "mvhd")?.let(::header) ?: return null
        val mvex = child(moov, "mvex")
        for (trak in children(moov, "trak")) {
            val mdia = child(trak, "mdia") ?: continue
            val hdlr = child(mdia, "hdlr") ?: return null
            if (hdlr.remaining() < 12 || !named(hdlr, 8, "soun")) continue
            val mdhd = child(mdia, "mdhd")?.let(::header) ?: return null
            val edits = child(trak, "edts")?.let { child(it, "elst") }?.let(::edits) ?: emptyList()
            val stts = child(mdia, "minf")?.let { child(it, "stbl") }?.let { child(it, "stts") }?.let(::total)
            val fragments = mvex?.let { trackId(trak)?.let { id -> fragmentsLength(f, id, trexDuration(it, id)) } }
            return Track(mdhd.first, mdhd.second, movie.first, edits, stts, mvex != null, fragments)
        }
        Track(movie.first, movie.second, movie.first, emptyList())
    }

    /** A `trak`'s `tkhd` track_ID, or null. */
    private fun trackId(trak: ByteBuffer): Long? {
        val tkhd = child(trak, "tkhd") ?: return null
        val at = when (tkhd.get(0).toInt()) {
            0 -> 12
            1 -> 20
            else -> return null
        }
        return if (tkhd.remaining() < at + 4) null else u32(tkhd, at)
    }

    /** The default sample duration an `mvex`'s `trex` gives [track], 0 for none. */
    private fun trexDuration(mvex: ByteBuffer, track: Long): Long = children(mvex, "trex")
        .firstOrNull { it.remaining() >= 24 && u32(it, 4) == track }?.let { u32(it, 12) } ?: 0L

    /**
     * [track]'s fragments' length in its media's timescale, as FFmpeg's mov demuxer times their samples and its remux
     * writes the `mdhd`: from the first fragment's decode time (its `tfdt`, else 0) to its last sample's end, each
     * `traf` of the track starting at its `tfdt` (else where the one before ended), each sample's duration its
     * `trun`'s, else its `tfhd`'s default, else the `trex`'s ([default]). Null, an unknown length, never a wrong one:
     * where none is read; where the file's top-level boxes can't all be read (a download cut short, trailing junk, a
     * `moof` past [MOOV_MOST]); where one is cut short or leads past a Long; where a `tfdt` goes back before the end
     * of the fragment before it; where the length comes to 0 or less (samples of no duration at all).
     */
    private fun fragmentsLength(f: RandomAccessFile, track: Long, default: Long): Long? {
        var first: Long? = null
        var end = 0L
        var any = false
        for (moof in topLevels(f, "moof") ?: return null) {
            for (traf in children(moof, "traf")) {
                val tfhd = child(traf, "tfhd") ?: return null
                if (tfhd.remaining() < 8) return null
                if (u32(tfhd, 4) != track) continue
                val flags = tfhd.getInt(0) and 0xFFFFFF
                var at = 8 + (if (flags and 0x01 != 0) 8 else 0) + (if (flags and 0x02 != 0) 4 else 0)
                val duration = if (flags and 0x08 != 0) {
                    if (tfhd.remaining() < at + 4) return null
                    u32(tfhd, at)
                } else default
                child(traf, "tfdt")?.let { tfdt ->
                    val time = when {
                        tfdt.remaining() >= 12 && tfdt.get(0).toInt() == 1 ->
                            tfdt.getLong(4).also { if (it < 0) return null }
                        tfdt.remaining() >= 8 && tfdt.get(0).toInt() == 0 -> u32(tfdt, 4)
                        else -> return null
                    }
                    if (first != null && time < end) return null  // back before where the fragment before ended
                    end = time
                }
                if (first == null) first = end
                for (trun in children(traf, "trun")) {
                    if (trun.remaining() < 8) return null
                    val tflags = trun.getInt(0) and 0xFFFFFF
                    val count = u32(trun, 4)
                    at = 8 + (if (tflags and 0x01 != 0) 4 else 0) + (if (tflags and 0x04 != 0) 4 else 0)
                    val each = listOf(0x100, 0x200, 0x400, 0x800).count { tflags and it != 0 } * 4
                    if (at + count * each > trun.remaining()) return null
                    try {
                        if (tflags and 0x100 == 0) {
                            end = Math.addExact(end, Math.multiplyExact(count, duration))
                        } else {
                            for (i in 0 until count.toInt()) end = Math.addExact(end, u32(trun, at + i * each))
                        }
                    } catch (e: ArithmeticException) {
                        return null
                    }
                    any = true
                }
            }
        }
        return if (any) (end - first!!).takeIf { it > 0 } else null
    }

    /** A `mvhd` or `mdhd` payload's timescale and duration, or null for a version mutagen doesn't read. */
    private fun header(b: ByteBuffer): Pair<Long, Long>? {
        if (b.remaining() < 4) return null
        return when (b.get(0).toInt()) {
            0 -> if (b.remaining() < 20) null else u32(b, 12) to u32(b, 16)
            1 -> if (b.remaining() < 32) null else u32(b, 20) to b.getLong(24).also { if (it < 0) return null }
            else -> null
        }
    }

    private fun edits(b: ByteBuffer): List<Edit>? {
        if (b.remaining() < 8) return null
        val version = b.get(0).toInt()
        val count = u32(b, 4)
        val size = if (version == 1) 20 else 12
        if (version !in 0..1 || 8 + count * size > b.remaining()) return null
        return (0 until count.toInt()).map { i ->
            val at = 8 + i * size
            if (version == 1) Edit(b.getLong(at), b.getLong(at + 8)) else Edit(u32(b, at), b.getInt(at + 4).toLong())
        }
    }

    /** An `stts` payload's total: each entry's sample count times its delta; null where it is cut short or the
     * total passes a Long. */
    private fun total(b: ByteBuffer): Long? {
        if (b.remaining() < 8) return null
        val count = u32(b, 4)
        if (8 + count * 8 > b.remaining()) return null
        var sum = BigInteger.ZERO
        for (i in 0 until count.toInt()) {
            sum += BigInteger.valueOf(u32(b, 8 + 8 * i)).multiply(BigInteger.valueOf(u32(b, 12 + 8 * i)))
        }
        return if (sum.bitLength() < 63) sum.toLong() else null
    }

    private fun u32(b: ByteBuffer, at: Int): Long = b.getInt(at).toLong() and 0xFFFFFFFFL

    /** The payload of the first top-level box [name], read whole, or null. */
    private fun topLevel(f: RandomAccessFile, name: String): ByteBuffer? =
        topLevels(f, name, first = true)?.firstOrNull()

    /** The payloads of the top-level boxes [name] (the first alone where [first]), each read whole; null where one is
     * past [MOOV_MOST], or a box's size leads past the file (the boxes before it are no answer then). */
    private fun topLevels(f: RandomAccessFile, name: String, first: Boolean = false): List<ByteBuffer>? {
        val length = f.length()
        var at = 0L
        val head = ByteArray(16)
        val out = mutableListOf<ByteBuffer>()
        while (at + 8 <= length) {
            f.seek(at)
            f.readFully(head, 0, 8)
            var size = u32(ByteBuffer.wrap(head), 0)
            var headerSize = 8
            if (size == 1L) {
                if (at + 16 > length) return null
                f.readFully(head, 8, 8)
                size = ByteBuffer.wrap(head).getLong(8)
                headerSize = 16
            } else if (size == 0L) {
                size = length - at
            }
            if (size < headerSize || size > length - at) return null  // never past the file, never by overflow
            if (named(ByteBuffer.wrap(head), 4, name)) {
                if (size - headerSize > MOOV_MOST) return null
                val body = ByteArray((size - headerSize).toInt())
                f.readFully(body)
                out += ByteBuffer.wrap(body).order(ByteOrder.BIG_ENDIAN)
                if (first) return out
            }
            at += size
        }
        return out
    }

    /** The payloads of [parent]'s child boxes named [name], in order. */
    private fun children(parent: ByteBuffer, name: String): List<ByteBuffer> {
        val out = mutableListOf<ByteBuffer>()
        var at = 0
        while (at + 8 <= parent.remaining()) {
            val size = u32(parent, at)
            var headerSize = 8
            val whole = when (size) {
                1L -> if (at + 16 > parent.remaining()) return out else parent.getLong(at + 8).also { headerSize = 16 }
                0L -> (parent.remaining() - at).toLong()
                else -> size
            }
            if (whole < headerSize || whole > parent.remaining() - at) return out
            if (named(parent, at + 4, name)) {
                val body = parent.duplicate()
                body.position(at + headerSize).limit((at + whole).toInt())
                out += body.slice().order(ByteOrder.BIG_ENDIAN)
            }
            at += whole.toInt()
        }
        return out
    }

    private fun child(parent: ByteBuffer, name: String): ByteBuffer? = children(parent, name).firstOrNull()

    private fun named(b: ByteBuffer, at: Int, id: String): Boolean =
        at + 4 <= b.limit() && id.indices.all { b.get(at + it) == id[it].code.toByte() }
}
