package io.github.danielhp95.caracole.core.sync.internal.take

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import io.github.danielhp95.caracole.core.sync.UnitError
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.DirectoryNotEmptyException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.SecureRandom

/**
 * peer_sync._Folders on the phone: the changes a take makes to the library's folders, each step undone, latest
 * first, when the take fails ([undo]); [done] lets go of what they kept for that (a file a write replaced, a folder
 * left empty). Every folder from the library down is entered only as a folder of its own, never through a symbolic
 * link (the plan's §5.6: canonical paths under libraryDir, no link followed). A file is written under a temporary
 * name of its own first (`.<name>.<8 hex>.tmp`, which removal.py knows), then renamed into place; a folder is renamed
 * through a temporary name, so that a file system blind to case renames it too.
 */
internal class Folders(libraryDir: File) {
    private val root: Path = libraryDir.toPath()
    private val undoSteps = ArrayList<() -> Unit>()
    private val doneSteps = ArrayList<() -> Unit>()
    private val synced = LinkedHashSet<Path>()

    /** The folder [parts] under the library; null when it isn't there and isn't to be made. */
    private fun folder(parts: List<String>, make: Boolean = false): Path? {
        if (make) Files.createDirectories(root)
        if (!Files.isDirectory(root)) return null
        var at = root
        for ((i, name) in parts.withIndex()) {
            val next = at.resolve(name)
            val held = LibraryFiles.entry(next)
            if (held == null) {
                if (!make) return null
                Files.createDirectory(next)
                undoSteps += { Files.delete(next) }
            } else if (!held.isDirectory) {
                throw UnitError("${parts.take(i + 1).joinToString("/")}/ is a symbolic link or no folder: we " +
                                "don't follow it")
            }
            at = next
        }
        return at
    }

    private fun rename(from: Path, to: Path) {
        Files.move(from, to, StandardCopyOption.ATOMIC_MOVE)
        undoSteps += { Files.move(to, from, StandardCopyOption.ATOMIC_MOVE) }
        from.parent?.let { synced.add(it) }
        to.parent?.let { synced.add(it) }
    }

    /** The artist's folder [old] renamed [new], through a temporary name; into a folder [new] there is already,
     * each folder of [old]'s moved in. */
    fun moveFolder(old: String, new: String) {
        val top = folder(emptyList()) ?: return
        if (old == new) return
        val held = LibraryFiles.entry(top.resolve(old)) ?: return
        if (!held.isDirectory) throw UnitError("$old/ is a symbolic link or no folder: we don't follow it")
        val there = LibraryFiles.entry(top.resolve(new))
        if (there == null || LibraryFiles.same(top.resolve(old), top.resolve(new))) {
            val temporary = top.resolve(temporary(new))
            rename(top.resolve(old), temporary)
            rename(temporary, top.resolve(new))
            return
        }
        val src = folder(listOf(old))!!
        val dst = folder(listOf(new))!!
        val names = Files.newDirectoryStream(src).use { s -> s.map { it.fileName.toString() } }.sortedWith(Canonical.KEY_ORDER)
        for (name in names) {
            if (LibraryFiles.entry(dst.resolve(name)) != null) {
                throw UnitError("$new/$name is there already, so $old/ can't move into it")
            }
            rename(src.resolve(name), dst.resolve(name))
        }
        doneSteps += { prune(top, old) }
    }

    /** The files [names] of the song's folder [old] moved to its folder [new], one at a time, each a regular file
     * (another is left where it is). */
    fun moveFiles(old: List<String>, new: List<String>, names: Iterable<String>) {
        val src = folder(old) ?: return
        val dst = folder(new, make = true)!!
        for (name in names) {
            val held = LibraryFiles.entry(src.resolve(name))
            if (held == null || !held.isRegularFile) continue
            if (LibraryFiles.entry(dst.resolve(name)) != null) {
                if (LibraryFiles.same(src.resolve(name), dst.resolve(name))) continue // one folder by both names
                throw UnitError("${new.joinToString("/")}/$name is there already")
            }
            rename(src.resolve(name), dst.resolve(name))
        }
        val parent = folder(old.dropLast(1))
        if (parent != null) doneSteps += { prune(parent, old.last(), up = old.dropLast(1)) }
    }

    /** [data] as the file [name] of the folder [parts], in place of a regular file there. */
    fun write(parts: List<String>, name: String, data: ByteArray) {
        val dir = folder(parts, make = true)!!
        val temporary = dir.resolve(temporary(name))
        FileChannel.open(temporary, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                         LinkOption.NOFOLLOW_LINKS).use { channel ->
            undoSteps += { unlink(temporary) }
            val buffer = ByteBuffer.wrap(data)
            while (buffer.hasRemaining()) channel.write(buffer)
            channel.force(true)
        }
        aside(dir, name)
        rename(temporary, dir.resolve(name))
    }

    /** The regular file [name] of the folder [parts] gone, if it is there. */
    fun remove(parts: List<String>, name: String) {
        val dir = folder(parts) ?: return
        aside(dir, name)
    }

    /** A regular file renamed out of the way, deleted once the take is done; anything else there refused. */
    private fun aside(dir: Path, name: String) {
        val held = LibraryFiles.entry(dir.resolve(name)) ?: return
        if (!held.isRegularFile) throw UnitError("$name there isn't a regular file: we don't replace it")
        val aside = dir.resolve(temporary(name))
        rename(dir.resolve(name), aside)
        doneSteps += { unlink(aside) }
    }

    private fun unlink(file: Path) {
        if (LibraryFiles.entry(file)?.isRegularFile == true) Files.deleteIfExists(file)
    }

    /** The folder [name] gone once empty, then its own folder ([up]) the same way. */
    private fun prune(parent: Path, name: String, up: List<String> = emptyList()) {
        try {
            Files.delete(parent.resolve(name))
        } catch (_: DirectoryNotEmptyException) {
            return
        } catch (_: NoSuchFileException) {
            return
        } catch (_: IOException) {
            return
        }
        if (up.isNotEmpty()) folder(up.dropLast(1))?.let { prune(it, up.last()) }
    }

    fun undo() {
        for (step in undoSteps.asReversed()) {
            try {
                step()
            } catch (_: IOException) {
            } catch (_: UnitError) {
            }
        }
        clear()
    }

    fun done() {
        for (dir in synced) {
            try {
                FileChannel.open(dir, StandardOpenOption.READ).use { it.force(true) }
            } catch (_: IOException) {
            }
        }
        for (step in doneSteps) {
            try {
                step()
            } catch (_: IOException) {
            } catch (_: UnitError) {
            }
        }
        clear()
    }

    private fun clear() {
        undoSteps.clear()
        doneSteps.clear()
        synced.clear()
    }

    companion object {
        private val random = SecureRandom()

        /** `.<name>.<8 hex>.tmp`. */
        fun temporary(name: String): String {
            val bytes = ByteArray(4).also { random.nextBytes(it) }
            return ".$name.${hex(bytes)}.tmp"
        }

        private fun hex(bytes: ByteArray): String {
            val digits = "0123456789abcdef"
            val out = StringBuilder()
            for (b in bytes) out.append(digits[(b.toInt() shr 4) and 15]).append(digits[b.toInt() and 15])
            return out.toString()
        }
    }
}
