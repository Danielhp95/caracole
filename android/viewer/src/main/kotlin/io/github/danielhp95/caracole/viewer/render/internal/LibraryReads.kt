package io.github.danielhp95.caracole.viewer.render.internal

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.py.PyText
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.attribute.BasicFileAttributes
import kotlinx.serialization.json.JsonElement

/** render.RenderError: what fails a song's sheet (its file can't be read or written as caracole reads and writes one),
 * in render.py's words. */
class RenderError(message: String) : Exception(message)

/** library.NotRegularFile: a link, a folder or anything but a regular file where caracole reads or writes one. */
class NotRegularFile(message: String) : IOException(message)

/**
 * library.py's reads and render.py's writes of the song's folder, as the phone does them: a file read only while it is
 * a regular file (never through a link in its place), a page written through a temporary file and a rename, and only
 * when its bytes change.
 */
internal object LibraryReads {
    /** library.read_regular: the regular file's bytes; NoSuchFileException where nothing is there, [NotRegularFile]
     * for a link or anything else, another IOException for a file that can't be read. */
    fun regular(file: File): ByteArray {
        val path = file.toPath()
        val attrs = Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        if (!attrs.isRegularFile) throw NotRegularFile("${file.path}: not a regular file")
        return Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
    }

    /** bytes.decode("utf-8", errors="replace"). */
    fun replaced(bytes: ByteArray): String = PyText.utf8(bytes, replace = true)!!

    /** render._read_text: a file as UTF-8 text, never read through a link; RenderError for one that can't be read
     * so (or isn't UTF-8). */
    fun text(file: File): String {
        val bytes = try {
            regular(file)
        } catch (e: IOException) {
            throw RenderError("cannot read ${file.path}: ${e.message}")
        }
        return PyText.utf8(bytes) ?: throw RenderError("cannot read ${file.path}: not UTF-8")
    }

    /** library.read_json: the JSON of a regular file; IOException for nothing there or no regular file,
     * IllegalArgumentException (Python's ValueError) for what isn't UTF-8 or JSON. */
    fun json(file: File): JsonElement {
        val text = PyText.utf8(regular(file)) ?: throw IllegalArgumentException("not UTF-8")
        return PyJson.loads(text)
    }

    /** render._write_if_changed: [data] at [file] (write_atomic) unless it holds them already; the old file is read
     * only to compare, never through a link: RenderError when something other than a regular file is in its place.
     * Whether it was written. */
    fun writeIfChanged(file: File, data: ByteArray): Boolean {
        try {
            if (regular(file).contentEquals(data)) return false
        } catch (e: NotRegularFile) {
            throw RenderError("cannot read ${file.path}: ${e.message}")
        } catch (_: IOException) {
        }
        Kept.writeAtomic(file.toPath(), data)
        return true
    }

    /** Path.unlink(missing_ok=True): the file (or a link in its place) deleted; a folder there is an IOException, as
     * Python's IsADirectoryError. */
    fun unlink(file: File) {
        val path = file.toPath()
        val attrs = try {
            Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        } catch (_: NoSuchFileException) {
            return
        }
        if (attrs.isDirectory) throw IOException("${file.path}: is a directory")
        Files.deleteIfExists(path)
    }
}
