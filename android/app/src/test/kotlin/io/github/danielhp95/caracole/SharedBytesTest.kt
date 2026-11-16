package io.github.danielhp95.caracole

import org.junit.Test
import java.io.InputStream
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A file shared to the app read whole up to the inbox's limit, and refused one byte past it, never read on. */
class SharedBytesTest {
    /** [size] bytes, counting how many were read. */
    private class Counted(val size: Long) : InputStream() {
        var read = 0L
        override fun read(): Int = if (read < size) { read++; (read % 251).toInt() } else -1
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (read >= size) return -1
            val n = minOf(len.toLong(), size - read).toInt()
            for (i in 0 until n) b[off + i] = ((read + i + 1) % 251).toByte()
            read += n
            return n
        }
    }

    @Test
    fun `a file at the limit is read whole, and one byte past it is refused having read one byte more`() {
        val most = 200_000
        for (size in listOf(0L, 1L, 65_536L, 65_537L, most.toLong())) {
            val bytes = SharedBytes.readAtMost(Counted(size), most)
            assertContentEquals(ByteArray(size.toInt()) { ((it + 1) % 251).toByte() }, bytes, "$size bytes")
        }
        for (size in listOf(most + 1L, 10L * most)) {
            val input = Counted(size)
            assertNull(SharedBytes.readAtMost(input, most), "$size bytes is past $most")
            assertEquals(most + 1L, input.read, "read no further than the byte past the limit")
        }
    }

    @Test
    fun `a stream that gives a little at a time is read whole`() {
        val drip = object : InputStream() {
            var left = 100_000
            override fun read(): Int = if (left-- > 0) 1 else -1
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                if (left <= 0) return -1
                b[off] = 1
                left--
                return 1
            }
        }
        val bytes = SharedBytes.readAtMost(drip, 1 shl 20)!!
        assertEquals(100_000, bytes.size)
        assertTrue(bytes.all { it == 1.toByte() })
    }
}
