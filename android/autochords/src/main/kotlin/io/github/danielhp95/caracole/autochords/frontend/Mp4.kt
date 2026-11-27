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
 *   its segment duration rescaled from the movie's timescale to the media's ([keptFrames]).
 *
 * Only the box headers are read on the way to `moov`, which is read whole (at most [MOOV_MOST]), never the samples.
 */
object Mp4 {
    const val MOOV_MOST = 16L * 1024 * 1024

    /** One entry of an edit list: its duration in the movie's timescale, and where it starts in the media's (-1 an
     * empty edit, a gap). */
    data class Edit(val segment: Long, val mediaTime: Long)

    /** The sound track: its `mdhd` timescale and duration (or the `mvhd`'s, with no sound track), the movie's
     * timescale, and its edits. */
    data class Track(val timescale: Long, val duration: Long, val movieTimescale: Long, val edits: List<Edit>) {
        /** mutagen's length: `float(duration) / timescale`, 0 for a timescale of 0. */
        val seconds: Double get() = if (timescale == 0L) 0.0 else duration.toDouble() / timescale

        /** The one media edit (empty ones aside), or none: no list, several media edits, which are not trimmed
         * exactly here, or numbers that lead nowhere (a timescale of 0, a negative segment). */
        fun edit(): Edit? = edits.filter { it.mediaTime >= 0 }.singleOrNull()
            ?.takeIf { it.segment >= 0 && timescale > 0 && movieTimescale > 0 }

        /** The samples FFmpeg keeps of [edit]: its segment rescaled to the media's timescale (av_rescale). */
        fun keptFrames(edit: Edit): Long = rescale(edit.segment, timescale, movieTimescale)
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
        for (trak in children(moov, "trak")) {
            val mdia = child(trak, "mdia") ?: continue
            val hdlr = child(mdia, "hdlr") ?: return null
            if (hdlr.remaining() < 12 || !named(hdlr, 8, "soun")) continue
            val mdhd = child(mdia, "mdhd")?.let(::header) ?: return null
            val edits = child(trak, "edts")?.let { child(it, "elst") }?.let(::edits) ?: emptyList()
            return Track(mdhd.first, mdhd.second, movie.first, edits)
        }
        Track(movie.first, movie.second, movie.first, emptyList())
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

    private fun u32(b: ByteBuffer, at: Int): Long = b.getInt(at).toLong() and 0xFFFFFFFFL

    /** The payload of the first top-level box [name], read whole, or null. */
    private fun topLevel(f: RandomAccessFile, name: String): ByteBuffer? {
        val length = f.length()
        var at = 0L
        val head = ByteArray(16)
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
                return ByteBuffer.wrap(body).order(ByteOrder.BIG_ENDIAN)
            }
            at += size
        }
        return null
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
