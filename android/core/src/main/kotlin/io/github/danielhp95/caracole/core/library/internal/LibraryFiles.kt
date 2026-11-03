package io.github.danielhp95.caracole.core.library.internal

import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes

/**
 * The phone's library folder read as removal.py and peer_sync.py read the computer's, with no symbolic link
 * followed below the library: each folder from the library down is looked at itself (lstat) before it is entered,
 * and a file is read or changed only while it is a regular file. The phone's library is the app's own (filesDir), so
 * nothing else changes it meanwhile.
 */
internal object LibraryFiles {
    /** A folder that isn't there. */
    class NoFolder : Exception()

    /** A folder caracole won't enter: why, as removal.py says it ("Artist/ is a symbolic link, …"). */
    class NotFollowed(message: String) : Exception(message)

    const val LINK = "a symbolic link, which caracole doesn't follow"

    /** What [path] is, itself (no link followed); null when nothing is there. */
    fun entry(path: Path): BasicFileAttributes? = try {
        Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
    } catch (_: NoSuchFileException) {
        null
    }

    /** "file", "link", "folder" or "other", as removal._entries names them. */
    fun kind(attrs: BasicFileAttributes): String = when {
        attrs.isRegularFile -> "file"
        attrs.isSymbolicLink -> "link"
        attrs.isDirectory -> "folder"
        else -> "other"
    }

    /** The folder [parts] under [root], each entered only as a folder of its own: NoFolder when one isn't there,
     * NotFollowed for a link or no folder in its place (removal._open_folder). */
    fun folder(root: Path, parts: List<String>): Path {
        if (!Files.isDirectory(root)) throw NoFolder()
        var at = root
        for ((i, part) in parts.withIndex()) {
            at = at.resolve(part)
            val attrs = entry(at) ?: throw NoFolder()
            if (!attrs.isDirectory) {
                val where = parts.take(i + 1).joinToString("/") + "/"
                throw NotFollowed("$where is ${if (attrs.isSymbolicLink) LINK else "not a folder"}")
            }
        }
        return at
    }

    /** Each name in [folder] with what it is, sorted as Python sorts them (by code point). */
    fun entries(folder: Path): List<Pair<String, String>> =
        Files.newDirectoryStream(folder).use { names ->
            names.mapNotNull { p -> entry(p)?.let { p.fileName.toString() to kind(it) } }
        }.sortedWith { a, b -> io.github.danielhp95.caracole.core.json.Canonical.KEY_ORDER.compare(a.first, b.first) }

    /** The bytes of the regular file [file], never through a link in its place; null for anything else. */
    fun regularBytes(file: Path): ByteArray? {
        val attrs = entry(file) ?: return null
        if (!attrs.isRegularFile) return null
        return try {
            Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (_: IOException) {
            null
        }
    }

    /** Whether [a] and [b] are one entry (a file system blind to case gives one by both names). */
    fun same(a: Path, b: Path): Boolean {
        val x = entry(a) ?: return false
        val y = entry(b) ?: return false
        val kx = x.fileKey()
        val ky = y.fileKey()
        if (kx != null && ky != null) return kx == ky
        return try { Files.isSameFile(a, b) } catch (_: IOException) { false }
    }
}
