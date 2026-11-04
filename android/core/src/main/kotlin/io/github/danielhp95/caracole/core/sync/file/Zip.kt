package io.github.danielhp95.caracole.core.sync.file

import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipException
import java.util.zip.ZipFile

/**
 * A `.caracole` file's zip, read as Python's zipfile reads it: its central directory's members in their order
 * ([members]), each member's bytes read through with its CRC-32 and its size checked against what the directory
 * declares ([read], [copy]: java.util.zip.ZipFile checks neither), never more than a member may hold. Every failure
 * of a member is a [Damaged] (Python's BadZipFile, zlib.error, EOFError), whose caller says it in the owner's words.
 * [open] is a ZipException (or an IOException) for a file that is no whole zip: one cut short, one with an encrypted
 * member or one compressed otherwise than stored or deflated (which ZipFile refuses as it reads the directory).
 */
internal class Zip private constructor(private val zip: ZipFile) : AutoCloseable {
    /** A member that can't be read whole ([member], its name): one bigger than it may be ([tooBig]), else damaged
     * or cut short, [message] saying how. */
    class Damaged(val member: String, val tooBig: Boolean, message: String) : Exception(message)

    /** Every member, in the central directory's order, a name twice included. */
    val members: List<ZipEntry> = zip.entries().toList()

    /** The member [name] (the first of that name); null for none. */
    fun member(name: String): ZipEntry? = zip.getEntry(name)

    /** [entry]'s bytes, whole: a [Damaged] when they aren't what the directory says, or are more than [most]. */
    fun read(entry: ZipEntry, most: Long): ByteArray {
        if (entry.size > most) throw Damaged(entry.name, true, "${entry.name} is bigger than it may be")
        val out = java.io.ByteArrayOutputStream(if (entry.size in 0..CHUNK) entry.size.toInt() else CHUNK)
        copy(entry, out, most)
        return out.toByteArray()
    }

    /** [entry]'s bytes copied to [out] in chunks, their CRC-32 and size checked as they end; a [Damaged] else. */
    fun copy(entry: ZipEntry, out: OutputStream, most: Long = Long.MAX_VALUE) {
        val crc = CRC32()
        var size = 0L
        val stream: InputStream = try {
            zip.getInputStream(entry)
        } catch (e: IOException) {
            throw Damaged(entry.name, false, "${entry.name}: ${e.message ?: e.javaClass.simpleName}")
        }
        stream.use {
            val buffer = ByteArray(CHUNK)
            while (true) {
                val n = try {
                    it.read(buffer)
                } catch (e: IOException) {
                    throw Damaged(entry.name, false, "${entry.name}: ${e.message ?: e.javaClass.simpleName}")
                }
                if (n < 0) break
                size += n
                if (size > most) throw Damaged(entry.name, true, "${entry.name} is bigger than it may be")
                crc.update(buffer, 0, n)
                out.write(buffer, 0, n)
            }
        }
        if ((entry.size >= 0 && size != entry.size) || (entry.crc >= 0 && crc.value != entry.crc)) {
            throw Damaged(entry.name, false, "${entry.name}: Bad CRC-32 or size")
        }
    }

    override fun close() = zip.close()

    companion object {
        const val CHUNK = 1024 * 1024

        /** The zip at [file]; a ZipException or an IOException for no whole zip. */
        fun open(file: File): Zip = Zip(ZipFile(file))

        /** Whether [e] is what a zip that can't be opened throws. */
        fun unopened(e: Exception): Boolean = e is ZipException || e is IOException
    }
}
