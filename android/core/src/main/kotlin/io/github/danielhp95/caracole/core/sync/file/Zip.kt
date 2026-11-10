package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.py.PyText
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.util.zip.CRC32
import java.util.zip.DataFormatException
import java.util.zip.Inflater
import java.util.zip.ZipException

/**
 * A `.caracole` file's zip, read as CPython 3.14's zipfile reads it (`_EndRecData`, `_EndRecData64`,
 * `_RealGetContents`, `ZipFile.open`, `ZipExtFile`), by hand: Android's java.util.zip.ZipFile refuses at open a member
 * whose name has a `..` segment or begins with `/` (ZipPathValidator, for an app of API 34 or more) and a name twice,
 * where Python reads the directory whole and peer_file's layout check says which member is wrong.
 *
 * - [open] reads the end record (zip64's too, with Python's checks) and the central directory: every member in its
 *   order ([members], a name twice included), its name as Python decodes it (UTF-8 with flag bit 11, else cp437; cut
 *   at a NUL; Info-ZIP's Unicode path field), its flags, method, CRC-32 and sizes (zip64's extra field). A
 *   ZipException for a file that is no whole zip (Python's BadZipFile, OSError, EOFError and ValueError, and the
 *   NotImplementedError of a version past 6.3, which Python lets through), an IOException for one that can't be read.
 * - [read] and [copy]: a member's local header checked (its name the directory's, its data not running into the next
 *   member's, not a patch, not encrypted), its data stored or inflated, at most its size, its CRC-32 checked at its end
 *   as ZipExtFile checks it (never its size: data that ends early with the CRC-32 its directory names is read as
 *   Python reads it). A [Damaged] else (Python's BadZipFile, EOFError, RuntimeError, zlib.error).
 *
 * What Python reads and this doesn't: a member compressed with bzip2, LZMA or Zstandard, a [Damaged] here. peer_file
 * refuses any such member but the manifest, which it reads before it checks the layout.
 */
internal class Zip private constructor(private val file: RandomAccessFile, val members: List<Member>) : AutoCloseable {
    /** A member as the central directory gives it: [name], Python's `filename` (`orig_filename` cut at a NUL, or the
     * Unicode path field's); [flags], its general purpose bits; [method], how it is compressed; [crc]; [size] and
     * [compressedSize], zip64's where its extra field gives them (one past a Long read as Long.MAX_VALUE). */
    class Member internal constructor(
        val name: String,
        internal val origName: String,
        val flags: Int,
        val method: Int,
        val crc: Long,
        val compressedSize: Long,
        val size: Long,
        internal val headerOffset: Long,
    ) {
        /** Where the next member's local header begins (`_end_offset`), or the central directory. */
        internal var endOffset: Long = Long.MAX_VALUE

        /** Flag bit 0: encrypted. */
        val encrypted: Boolean get() = flags and 1 != 0
    }

    /** A member that can't be read whole ([member], its name): one bigger than it may be ([tooBig]), else damaged
     * or cut short, [message] saying how. */
    class Damaged(val member: String, val tooBig: Boolean, message: String) : Exception(message)

    private val channel: FileChannel = file.channel
    private val byName: Map<String, Member> = members.associateBy { it.name }

    /** The member [name] (the last of that name, as Python's `getinfo`); null for none. */
    fun member(name: String): Member? = byName[name]

    /** [member]'s bytes, whole: a [Damaged] when they can't be read, or are more than [most]. */
    fun read(member: Member, most: Long): ByteArray {
        if (member.size > most) throw Damaged(member.name, true, "${member.name} is bigger than it may be")
        val out = ByteArrayOutputStream(if (member.size in 0..CHUNK) member.size.toInt() else CHUNK)
        copy(member, out, most)
        return out.toByteArray()
    }

    /** [member]'s bytes copied to [out] in chunks, at most its size, their CRC-32 checked as they end; a [Damaged]
     * else, or when they are more than [most]. */
    fun copy(member: Member, out: OutputStream, most: Long = Long.MAX_VALUE) {
        val name = member.name
        var at = dataStart(member)
        var compressLeft = member.compressedSize  // ZipExtFile's _compress_left
        var left = member.size  // and its _left
        var written = 0L
        val crc = CRC32()
        val buffer = ByteArray(CHUNK)

        // _read2: the next compressed bytes, none once they are all read; the file ending before them, EOFError.
        fun compressed(into: ByteArray): Int {
            if (compressLeft <= 0) return 0
            val n = readAt(at, into, minOf(into.size.toLong(), compressLeft).toInt())
            if (n <= 0) throw Damaged(name, false, "$name is cut short")
            at += n
            compressLeft -= n
            return n
        }

        // data[:self._left], then _update_crc.
        fun emit(n0: Int) {
            val n = if (n0 > left) left.toInt() else n0
            left -= n
            written += n
            if (written > most) throw Damaged(name, true, "$name is bigger than it may be")
            crc.update(buffer, 0, n)
            out.write(buffer, 0, n)
        }

        when (member.method) {
            STORED -> {
                var eof = false
                while (!eof) {
                    val n = compressed(buffer)
                    eof = compressLeft <= 0
                    emit(n)
                    if (left <= 0) eof = true
                }
            }
            DEFLATED -> {
                val inflater = Inflater(true)
                try {
                    val input = ByteArray(CHUNK)
                    var eof = false
                    while (!eof) {
                        if (inflater.needsInput()) {
                            val n = compressed(input)
                            if (n > 0) inflater.setInput(input, 0, n)
                        }
                        val n = try {
                            inflater.inflate(buffer)
                        } catch (e: DataFormatException) {
                            throw Damaged(name, false, "$name: ${e.message ?: "invalid deflate data"}")
                        }
                        eof = inflater.finished() || (compressLeft <= 0 && inflater.needsInput())
                        if (n == 0 && !eof && !inflater.needsInput()) throw Damaged(name, false, "$name can't be inflated")
                        emit(n)
                        if (left <= 0) eof = true
                    }
                } finally {
                    inflater.end()
                }
            }
            else -> throw Damaged(name, false, "$name: compression type ${member.method}")
        }
        if (crc.value != member.crc) throw Damaged(name, false, "Bad CRC-32 for file '$name'")
    }

    /** ZipFile.open's checks of [m]'s local header; where its data begins. */
    private fun dataStart(m: Member): Long {
        val header = ByteArray(LOCAL_HEADER)
        if (m.headerOffset < 0 || readAt(m.headerOffset, header, LOCAL_HEADER) != LOCAL_HEADER) {
            throw Damaged(m.name, false, "Truncated file header")
        }
        if (!header.startsWith(LOCAL_SIGNATURE)) throw Damaged(m.name, false, "Bad magic number for file header")
        val nameBytes = ByteArray(u16(header, 26))
        val got = maxOf(readAt(m.headerOffset + LOCAL_HEADER, nameBytes, nameBytes.size), 0)
        val start = m.headerOffset + LOCAL_HEADER + got + u16(header, 28)
        if (m.flags and 0x20 != 0) throw Damaged(m.name, false, "compressed patched data (flag bit 5)")
        if (m.flags and 0x40 != 0) throw Damaged(m.name, false, "strong encryption (flag bit 6)")
        val local = decodeName(nameBytes.copyOf(got), u16(header, 6))
        if (local != m.origName) throw Damaged(m.name, false, "File name in directory and header differ")
        if (m.compressedSize > m.endOffset - start && m.endOffset != m.headerOffset) {
            throw Damaged(m.name, false, "Overlapped entries: '${m.origName}' (possible zip bomb)")
        }
        if (m.encrypted) throw Damaged(m.name, false, "File '${m.name}' is encrypted, password required for extraction")
        return start
    }

    /** Up to [n] bytes of the file at [at] into [into], fewer where it ends: how many. */
    private fun readAt(at: Long, into: ByteArray, n: Int): Int = readAt(channel, at, into, n)

    override fun close() = file.close()

    companion object {
        const val CHUNK = 1024 * 1024
        const val STORED = 0
        const val DEFLATED = 8

        private const val END = 22  // sizeEndCentDir
        private const val END64_LOCATOR = 20
        private const val END64 = 56
        private const val CENTRAL = 46
        private const val LOCAL_HEADER = 30
        private const val MAX_COMMENT = 65535
        private const val MAX_EXTRACT_VERSION = 63
        private val END_SIGNATURE = byteArrayOf(0x50, 0x4b, 5, 6)
        private val END64_LOCATOR_SIGNATURE = byteArrayOf(0x50, 0x4b, 6, 7)
        private val END64_SIGNATURE = byteArrayOf(0x50, 0x4b, 6, 6)
        private val CENTRAL_SIGNATURE = byteArrayOf(0x50, 0x4b, 1, 2)
        private val LOCAL_SIGNATURE = byteArrayOf(0x50, 0x4b, 3, 4)

        /** cp437's characters for the bytes 0x80 to 0xFF, as Python's codec decodes them (below 0x80, ASCII). */
        private const val CP437_HIGH =
            "ÇüéâäàåçêëèïîìÄÅ" +
            "ÉæÆôöòûùÿÖÜ¢£¥₧ƒ" +
            "áíóúñÑªº¿⌐¬½¼¡«»" +
            "░▒▓│┤╡╢╖╕╣║╗╝╜╛┐" +
            "└┴┬├─┼╞╟╚╔╩╦╠═╬╧" +
            "╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀" +
            "αßΓπΣσµτΦΘΩδ∞φε∩" +
            "≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ "

        /** The zip at [file]: a ZipException for no whole zip, an IOException for a file that can't be read. */
        fun open(file: File): Zip {
            val raf = RandomAccessFile(file, "r")
            try {
                return Zip(raf, directory(raf.channel))
            } catch (e: Throwable) {
                raf.close()
                throw e
            }
        }

        /** Whether [e] is what a zip that can't be opened throws. */
        fun unopened(e: Exception): Boolean = e is ZipException || e is IOException

        /** The end record's central directory: its size, its offset and where the end record is (`endrec`'s
         * `_ECD_SIZE`, `_ECD_OFFSET` and `_ECD_LOCATION`). */
        private class End(val dirSize: Long, val dirOffset: Long, val location: Long)

        /** _RealGetContents: every member of the central directory, each with where the next one begins. */
        private fun directory(channel: FileChannel): List<Member> {
            val end = endRecord(channel, channel.size()) ?: throw ZipException("File is not a zip file")
            val startDir = end.location - end.dirSize
            if (startDir < 0) throw ZipException("Bad offset for central directory")
            val concat = startDir - end.dirOffset
            val held = minOf(end.dirSize, maxOf(channel.size() - startDir, 0L))
            if (held > Int.MAX_VALUE - 64) throw ZipException("a central directory too big to read")
            val cd = ByteArray(held.toInt()).let { it.copyOf(maxOf(readAt(channel, startDir, it, it.size), 0)) }
            val members = mutableListOf<Member>()
            var p = 0
            var total = 0L
            while (total < end.dirSize) {
                if (cd.size - p < CENTRAL) throw ZipException("Truncated central directory")
                if (!cd.startsWith(CENTRAL_SIGNATURE, p)) throw ZipException("Bad magic number for central directory")
                val extractVersion = cd[p + 6].toInt() and 0xFF
                val flags = u16(cd, p + 8)
                val method = u16(cd, p + 10)
                val crc = u32(cd, p + 16)
                var compressSize = u32(cd, p + 20)
                var fileSize = u32(cd, p + 24)
                val nameLength = u16(cd, p + 28)
                val extraLength = u16(cd, p + 30)
                val commentLength = u16(cd, p + 32)
                var headerOffset = u32(cd, p + 42)
                p += CENTRAL
                val nameBytes = cd.slice(p, nameLength).also { p += it.size }
                val extra = cd.slice(p, extraLength).also { p += it.size }
                p += minOf(commentLength, cd.size - p)
                val origName = decodeName(nameBytes, flags) ?: throw ZipException("a member's name isn't UTF-8")
                var name = sanitized(origName)
                if (extractVersion > MAX_EXTRACT_VERSION) throw ZipException("zip file version ${extractVersion / 10}.${extractVersion % 10}")
                // _decodeExtra: zip64's sizes and offset (as raw 64 bits: -1 is 2**64 - 1), Info-ZIP's Unicode path.
                var e = 0
                while (extra.size - e >= 4) {
                    val type = u16(extra, e)
                    val length = u16(extra, e + 2)
                    if (length + 4 > extra.size - e) throw ZipException("Corrupt extra field")
                    val data = extra.copyOfRange(e + 4, e + 4 + length)
                    if (type == 0x0001) {
                        var d = 0
                        fun next(): Long {
                            if (data.size - d < 8) throw ZipException("Corrupt zip64 extra field")
                            return u64(data, d).also { d += 8 }
                        }
                        if (fileSize == 0xFFFFFFFFL || fileSize == -1L) fileSize = next()
                        if (compressSize == 0xFFFFFFFFL) compressSize = next()
                        if (headerOffset == 0xFFFFFFFFL) headerOffset = next()
                    } else if (type == 0x7075) {
                        if (data.size < 5) throw ZipException("Corrupt unicode path extra field (0x7075)")
                        val nameCrc = CRC32().apply { update(nameBytes) }.value
                        if ((data[0].toInt() and 0xFF) == 1 && u32(data, 1) == nameCrc) {
                            val unicode = PyText.utf8(data, 5, data.size)
                                ?: throw ZipException("Corrupt unicode path extra field (0x7075): invalid utf-8 bytes")
                            if (unicode.isNotEmpty()) name = sanitized(unicode)
                        }
                    }
                    e += 4 + length
                }
                members += Member(name, origName, flags, method, crc, past(compressSize), past(fileSize),
                                  plus(past(headerOffset), concat))
                total += (CENTRAL + nameLength + extraLength + commentLength).toLong()
            }
            var endOffset = startDir
            for (m in members.sortedBy { it.headerOffset }.asReversed()) {
                m.endOffset = endOffset
                endOffset = m.headerOffset
            }
            return members
        }

        /** _EndRecData: the end record, the one at the file's end else the last within a comment's reach, read on
         * by [end64]; null for none. */
        private fun endRecord(channel: FileChannel, size: Long): End? {
            if (size < END) return null
            val last = ByteArray(END).also { readAt(channel, size - END, it, END) }
            if (last.startsWith(END_SIGNATURE) && last[20] == 0.toByte() && last[21] == 0.toByte()) {
                return end64(channel, size - END, End(u32(last, 12), u32(last, 16), size - END))
            }
            val from = maxOf(size - MAX_COMMENT - END, 0L)
            val data = ByteArray((size - from).toInt()).let { it.copyOf(maxOf(readAt(channel, from, it, it.size), 0)) }
            var start = data.size - END_SIGNATURE.size
            while (start >= 0 && !data.startsWith(END_SIGNATURE, start)) start--
            if (start < 0 || data.size - start < END) return null
            return end64(channel, from + start, End(u32(data, start + 12), u32(data, start + 16), from + start))
        }

        /** _EndRecData64: [end] as the zip64 end record gives it, when its locator is right before [at]. */
        private fun end64(channel: FileChannel, at: Long, end: End): End {
            var offset = at - END64_LOCATOR
            if (offset < 0) return end
            val locator = ByteArray(END64_LOCATOR)
            if (readAt(channel, offset, locator, END64_LOCATOR) != END64_LOCATOR) throw ZipException("Unknown I/O error")
            if (!locator.startsWith(END64_LOCATOR_SIGNATURE)) return end
            val reloff = u64(locator, 8)
            if (u32(locator, 4) != 0L || u32(locator, 16) > 1) {
                throw ZipException("zipfiles that span multiple disks are not supported")
            }
            offset -= END64
            if (reloff < 0 || reloff > offset) throw ZipException("Corrupt zip64 end of central directory locator")
            var extra = offset - reloff
            var data = ByteArray(END64)
            if (readAt(channel, reloff, data, END64) != END64) throw ZipException("Unknown I/O error")
            if (!data.startsWith(END64_SIGNATURE) && reloff != offset) {
                extra = 0
                data = ByteArray(END64)
                if (readAt(channel, offset, data, END64) != END64) throw ZipException("Unknown I/O error")
            }
            if (!data.startsWith(END64_SIGNATURE)) throw ZipException("Zip64 end of central directory record not found")
            val recordSize = u64(data, 4)
            val dirSize = u64(data, 40)
            val dirOffset = u64(data, 48)
            if (recordSize < 0 || dirSize < 0 || dirOffset < 0 || dirOffset > reloff || dirSize != reloff - dirOffset ||
                recordSize != END64 + extra - 12) {
                throw ZipException("Corrupt zip64 end of central directory record")
            }
            return End(dirSize, dirOffset, offset - extra)
        }

        /** Up to [n] bytes of [channel] at [at] into [into], fewer where it ends: how many (positional reads, so
         * that members are read alike from any thread). */
        private fun readAt(channel: FileChannel, at: Long, into: ByteArray, n: Int): Int {
            if (at < 0) return 0
            val buffer = ByteBuffer.wrap(into, 0, n)
            var done = 0
            while (buffer.hasRemaining()) {
                val got = channel.read(buffer, at + done)
                if (got < 0) break
                done += got
            }
            return done
        }

        /** A name's bytes as Python decodes them: UTF-8 (strict) with flag bit 11, else cp437; null where they
         * aren't UTF-8. */
        private fun decodeName(bytes: ByteArray, flags: Int): String? {
            if (flags and 0x800 != 0) return PyText.utf8(bytes)
            val out = StringBuilder(bytes.size)
            for (b in bytes) {
                val v = b.toInt() and 0xFF
                out.append(if (v < 0x80) v.toChar() else CP437_HIGH[v - 0x80])
            }
            return out.toString()
        }

        /** _sanitize_filename on a POSIX system: the name cut at its first NUL. */
        private fun sanitized(name: String): String = name.indexOf('\u0000').let { if (it >= 0) name.substring(0, it) else name }

        /** A 64-bit field read as Python's unbounded int would be compared: one past Long.MAX_VALUE as it. */
        private fun past(raw: Long): Long = if (raw < 0) Long.MAX_VALUE else raw

        /** [a] + [b], held within a Long. */
        private fun plus(a: Long, b: Long): Long {
            val sum = a + b
            return if (((a xor sum) and (b xor sum)) < 0) (if (a > 0) Long.MAX_VALUE else Long.MIN_VALUE) else sum
        }

        private fun u16(b: ByteArray, at: Int): Int = (b[at].toInt() and 0xFF) or ((b[at + 1].toInt() and 0xFF) shl 8)

        private fun u32(b: ByteArray, at: Int): Long = u16(b, at).toLong() or (u16(b, at + 2).toLong() shl 16)

        private fun u64(b: ByteArray, at: Int): Long = u32(b, at) or (u32(b, at + 4) shl 32)

        private fun ByteArray.startsWith(prefix: ByteArray, at: Int = 0): Boolean =
            size - at >= prefix.size && prefix.indices.all { this[at + it] == prefix[it] }

        /** Up to [n] bytes from [at], fewer where the array ends (BytesIO's read). */
        private fun ByteArray.slice(at: Int, n: Int): ByteArray = copyOfRange(at, minOf(size, at + n))
    }
}
