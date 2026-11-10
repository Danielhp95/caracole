package io.github.danielhp95.caracole.core.sites.internal.gtptabs

import io.github.danielhp95.caracole.core.py.PyText
import java.math.BigInteger
import java.util.zip.CRC32

/**
 * The names a zip lists, read as CPython 3.14's zipfile reads them for `ZipFile(io.BytesIO(data)).namelist()`
 * (`_EndRecData`, `_EndRecData64`, `_RealGetContents`, `ZipInfo._decodeExtra`): from its end of central directory
 * record and its central directory alone, nothing unpacked and never java.util.zip's stream. Where zipfile raises
 * (BadZipFile, OSError, NotImplementedError, a UnicodeDecodeError: each one of gtptabs.sniff's `_ZIP_ERRORS`), [names]
 * gives null.
 *
 * Read as zipfile reads a BytesIO: a read past the end gives fewer bytes, a seek back from the end stops at 0. A name
 * is UTF-8 (strict, as Python decodes it) when its flag bit 11 says so, else cp437, then cut at its first NUL; a
 * Unicode Path extra field (0x7075) of version 1 whose CRC is the raw name's replaces it, when it isn't empty.
 */
internal object ZipNames {
    private val EOCD = sig(0x50, 0x4B, 0x05, 0x06)
    private val LOCATOR = sig(0x50, 0x4B, 0x06, 0x07)
    private val EOCD64 = sig(0x50, 0x4B, 0x06, 0x06)
    private val CENTRAL = sig(0x50, 0x4B, 0x01, 0x02)
    private const val SIZE_EOCD = 22
    private const val SIZE_LOCATOR = 20
    private const val SIZE_EOCD64 = 56
    private const val SIZE_CENTRAL = 46
    private const val MAX_COMMENT = 65535
    private const val MAX_EXTRACT_VERSION = 63
    private const val UTF8_NAME = 1 shl 11
    private val FULL_64 = BigInteger.ONE.shiftLeft(64) - BigInteger.ONE
    private val FULL_32 = BigInteger.valueOf(0xFFFF_FFFFL)

    /** cp437's upper half, as Python's codec decodes bytes 0x80 to 0xFF (the lower half is ASCII). */
    private const val CP437 = "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥" +
        "╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ "

    /** Where zipfile raises: the zip can't be read. */
    private class Bad : Exception() {
        override fun fillInStackTrace(): Throwable = this
    }

    /** What the end records say: the central directory's size and offset, and where the record read was. */
    private class End(var size: BigInteger, var offset: BigInteger, var location: Long)

    /** `ZipFile(io.BytesIO(data)).namelist()`, or null where zipfile raises. */
    fun names(data: ByteArray): List<String>? = try {
        read(data)
    } catch (_: Bad) {
        null
    }

    private fun read(data: ByteArray): List<String> {
        val end = endRecord(data) ?: throw Bad()
        // _handle_prepended_data: start_dir = offset + (location - size - offset)
        val startDir = BigInteger.valueOf(end.location) - end.size
        if (startDir.signum() < 0) throw Bad()
        val cd = slice(data, startDir.toLong(), end.size.toLong())
        val sizeCd = end.size.toLong()
        val names = ArrayList<String>()
        var pos = 0
        var total = 0L
        while (total < sizeCd) {
            val centdir = slice(cd, pos.toLong(), SIZE_CENTRAL.toLong())
            pos += centdir.size
            if (centdir.size != SIZE_CENTRAL) throw Bad()
            if (!startsWith(centdir, CENTRAL)) throw Bad()
            val nameLength = u16(centdir, 28)
            val extraLength = u16(centdir, 30)
            val commentLength = u16(centdir, 32)
            val raw = slice(cd, pos.toLong(), nameLength.toLong())
            pos += raw.size
            val crc = CRC32().apply { update(raw) }.value
            val flags = u16(centdir, 8)
            var name = sanitized(if ((flags and UTF8_NAME) != 0) utf8(raw) else cp437(raw))
            val extra = slice(cd, pos.toLong(), extraLength.toLong())
            pos += extra.size
            pos += slice(cd, pos.toLong(), commentLength.toLong()).size
            if ((centdir[6].toInt() and 0xFF) > MAX_EXTRACT_VERSION) throw Bad()  // NotImplementedError
            name = decodeExtra(extra, crc, name, fileSize = u32(centdir, 24), compressSize = u32(centdir, 20),
                               headerOffset = u32(centdir, 42))
            names += name
            total += SIZE_CENTRAL + nameLength + extraLength + commentLength
        }
        return names
    }

    /** `_EndRecData`: the end of central directory record, at the very end or before a comment; null for none. */
    private fun endRecord(data: ByteArray): End? {
        val size = data.size.toLong()
        val tail = slice(data, maxOf(size - SIZE_EOCD, 0L), SIZE_EOCD.toLong())
        if (tail.size == SIZE_EOCD && startsWith(tail, EOCD) && tail[20].toInt() == 0 && tail[21].toInt() == 0) {
            return endRecord64(data, size - SIZE_EOCD, end(tail, size - SIZE_EOCD))
        }
        val maxCommentStart = maxOf(size - MAX_COMMENT - SIZE_EOCD, 0L)
        val chunk = slice(data, maxCommentStart, (MAX_COMMENT + SIZE_EOCD).toLong())
        val start = lastIndexOf(chunk, EOCD)
        if (start < 0) return null
        val record = slice(chunk, start.toLong(), SIZE_EOCD.toLong())
        if (record.size != SIZE_EOCD) return null
        return endRecord64(data, maxCommentStart + start, end(record, maxCommentStart + start))
    }

    private fun end(record: ByteArray, location: Long) =
        End(BigInteger.valueOf(u32(record, 12)), BigInteger.valueOf(u32(record, 16)), location)

    /** `_EndRecData64`: the zip64 end records before the plain one at [at], when its locator is there. */
    private fun endRecord64(data: ByteArray, at: Long, end: End): End {
        var offset = at - SIZE_LOCATOR
        if (offset < 0) return end
        val locator = slice(data, offset, SIZE_LOCATOR.toLong())
        if (locator.size != SIZE_LOCATOR) throw Bad()
        if (!startsWith(locator, LOCATOR)) return end
        val disk = u32(locator, 4)
        val reloff = u64(locator, 8)
        val disks = u32(locator, 16)
        if (disk != 0L || disks > 1) throw Bad()
        offset -= SIZE_EOCD64
        if (reloff > BigInteger.valueOf(offset)) throw Bad()
        val relative = reloff.toLong()
        var extra = offset - relative
        var record = slice(data, relative, SIZE_EOCD64.toLong())
        if (record.size != SIZE_EOCD64) throw Bad()
        if (!startsWith(record, EOCD64) && relative != offset) {
            extra = 0
            record = slice(data, offset, SIZE_EOCD64.toLong())
            if (record.size != SIZE_EOCD64) throw Bad()
        }
        if (!startsWith(record, EOCD64)) throw Bad()
        val sz = u64(record, 4)
        val dirSize = u64(record, 40)
        val dirOffset = u64(record, 48)
        if (dirOffset + dirSize != reloff || sz + BigInteger.valueOf(12) != BigInteger.valueOf(SIZE_EOCD64 + extra)) {
            throw Bad()
        }
        end.size = dirSize
        end.offset = dirOffset
        end.location = offset - extra
        return end
    }

    /** `ZipInfo._decodeExtra`: the zip64 field's sizes read where the entry asks for them, a Unicode Path field's
     * name taken; the name, so. */
    private fun decodeExtra(extra: ByteArray, crc: Long, name: String, fileSize: Long, compressSize: Long,
                            headerOffset: Long): String {
        var named = name
        var file = BigInteger.valueOf(fileSize)
        var compressed = BigInteger.valueOf(compressSize)
        var header = BigInteger.valueOf(headerOffset)
        var i = 0
        while (extra.size - i >= 4) {
            val tp = u16(extra, i)
            val ln = u16(extra, i + 2)
            if (ln + 4 > extra.size - i) throw Bad()
            val field = extra.copyOfRange(i + 4, i + 4 + ln)
            if (tp == 0x0001) {
                var at = 0
                if (file == FULL_64 || file == FULL_32) {
                    if (field.size - at < 8) throw Bad()
                    file = u64(field, at)
                    at += 8
                }
                if (compressed == FULL_32) {
                    if (field.size - at < 8) throw Bad()
                    compressed = u64(field, at)
                    at += 8
                }
                if (header == FULL_32) {
                    if (field.size - at < 8) throw Bad()
                    header = u64(field, at)
                }
            } else if (tp == 0x7075) {
                if (field.size < 5) throw Bad()
                if ((field[0].toInt() and 0xFF) == 1 && u32(field, 1) == crc) {
                    val unicode = PyText.utf8(field, 5, field.size) ?: throw Bad()
                    if (unicode.isNotEmpty()) named = sanitized(unicode)
                }
            }
            i += ln + 4
        }
        return named
    }

    /** `_sanitize_filename` on a POSIX system: the name up to its first NUL. */
    private fun sanitized(name: String): String = name.indexOf('\u0000').let { if (it >= 0) name.substring(0, it) else name }

    private fun utf8(raw: ByteArray): String = PyText.utf8(raw) ?: throw Bad()

    private fun cp437(raw: ByteArray): String {
        val out = StringBuilder(raw.size)
        for (b in raw) {
            val v = b.toInt() and 0xFF
            out.append(if (v < 0x80) v.toChar() else CP437[v - 0x80])
        }
        return out.toString()
    }

    /** `data[from:from + n]`, clipped as Python slices (a BytesIO read). */
    private fun slice(data: ByteArray, from: Long, n: Long): ByteArray {
        val start = minOf(maxOf(from, 0L), data.size.toLong()).toInt()
        val stop = minOf(start.toLong() + maxOf(n, 0L), data.size.toLong()).toInt()
        return data.copyOfRange(start, stop)
    }

    private fun startsWith(data: ByteArray, prefix: ByteArray): Boolean =
        data.size >= prefix.size && prefix.indices.all { data[it] == prefix[it] }

    /** bytes.rfind. */
    private fun lastIndexOf(data: ByteArray, what: ByteArray): Int {
        for (i in data.size - what.size downTo 0) {
            if (what.indices.all { data[i + it] == what[it] }) return i
        }
        return -1
    }

    private fun u16(b: ByteArray, at: Int): Int = (b[at].toInt() and 0xFF) or ((b[at + 1].toInt() and 0xFF) shl 8)

    private fun u32(b: ByteArray, at: Int): Long = u16(b, at).toLong() or (u16(b, at + 2).toLong() shl 16)

    private fun u64(b: ByteArray, at: Int): BigInteger =
        BigInteger.valueOf(u32(b, at + 4)).shiftLeft(32) + BigInteger.valueOf(u32(b, at))

    private fun sig(vararg b: Int): ByteArray = ByteArray(b.size) { b[it].toByte() }
}
