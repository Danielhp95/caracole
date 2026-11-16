package io.github.danielhp95.caracole

import java.io.InputStream

/** A shared file's bytes read whole, but never more of them held than the inbox takes. */
object SharedBytes {
    private const val CHUNK = 1 shl 16

    /**
     * Every byte of [input] when there are at most [most]; null as soon as there is one more (one byte past [most]
     * read, never the rest). The bytes are held in chunks as they come and copied once into the answer, so a file
     * past the limit costs [most] bytes at most, never a buffer grown to twice its size (ByteArrayOutputStream's).
     */
    fun readAtMost(input: InputStream, most: Int): ByteArray? {
        val chunks = ArrayList<ByteArray>()
        var total = 0L
        while (true) {
            val room = (most - total).coerceAtMost(CHUNK.toLong()).toInt()
            if (room == 0) return if (input.read() < 0) join(chunks, total.toInt()) else null
            val chunk = ByteArray(room)
            var filled = 0
            while (filled < room) {
                val n = input.read(chunk, filled, room - filled)
                if (n < 0) break
                filled += n
            }
            if (filled > 0) chunks += if (filled == room) chunk else chunk.copyOf(filled)
            total += filled
            if (filled < room) return join(chunks, total.toInt())
        }
    }

    private fun join(chunks: List<ByteArray>, size: Int): ByteArray {
        val out = ByteArray(size)
        var at = 0
        for (chunk in chunks) {
            chunk.copyInto(out, at)
            at += chunk.size
        }
        return out
    }
}
