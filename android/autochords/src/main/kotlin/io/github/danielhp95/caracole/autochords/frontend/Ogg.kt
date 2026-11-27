package io.github.danielhp95.caracole.autochords.frontend

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Where an Ogg stream ends, as libsndfile (libvorbisfile, libopusfile) and mutagen read it: its last page's granule
 * position, the samples decoded up to its end, less an Opus stream's pre-skip (its `OpusHead`'s, at 48 kHz), which
 * the decoder drops at the start. A decoder gives whole packets, so its last packet's samples past that granule are
 * cut, as the computer cuts them. The stream is the first page's (its serial number): a page of another logical
 * stream is passed over. A Vorbis stream that begins past granule 0 (a cut-out stream) is not trimmed at its start
 * here: none caracole has met.
 */
object Ogg {
    /** How far from the end the last page is looked for: an Ogg page is 65,307 bytes at most. */
    const val TAIL = 70_000

    /** The stream's rate (Opus's 48 kHz; Vorbis's, its identification header's) and its samples. */
    data class Stream(val rate: Int, val frames: Long)

    /** [file]'s first logical stream's end, or null: no Ogg, or no Vorbis or Opus stream. */
    fun stream(file: File): Stream? = RandomAccessFile(file, "r").use { f ->
        val length = f.length()
        val head = ByteArray(minOf(length, 4096L).toInt()).also { f.readFully(it) }
        if (head.size < 28 || !has(head, 0, "OggS")) return null
        val serial = ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN).getInt(14)
        val segments = head[26].toInt() and 0xFF
        val payload = 27 + segments
        val (rate, preSkip) = when {
            has(head, payload, "OpusHead") && payload + 12 <= head.size ->
                48000 to (ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN).getShort(payload + 10).toInt() and
                    0xFFFF)
            has(head, payload + 1, "vorbis") && payload + 16 <= head.size && head[payload].toInt() == 1 ->
                ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN).getInt(payload + 12) to 0
            else -> return null
        }
        val start = maxOf(0L, length - TAIL)
        val tail = ByteArray((length - start).toInt())
        f.seek(start)
        f.readFully(tail)
        val t = ByteBuffer.wrap(tail).order(ByteOrder.LITTLE_ENDIAN)
        var at = tail.size - 27
        while (at >= 0) {
            if (has(tail, at, "OggS") && tail[at + 4].toInt() == 0 && t.getInt(at + 14) == serial) {
                val granule = t.getLong(at + 6)
                if (granule >= 0) return Stream(rate, maxOf(0L, granule - preSkip))
            }
            at--
        }
        null
    }

    private fun has(b: ByteArray, at: Int, id: String): Boolean =
        at >= 0 && at + id.length <= b.size && id.indices.all { b[at + it] == id[it].code.toByte() }
}
