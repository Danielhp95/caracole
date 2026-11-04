package io.github.danielhp95.caracole.core.library.internal.writes

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.JsonText
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.security.SecureRandom

/** Where a song's file goes, and the file operations library.py's writers rest on. */
internal object Place {
    /** The song's folder under the library, `library_dir / artist / title` (library.song_dir), as its path relative
     * to the library ("Artist/Title") and as a path. */
    fun folder(lib: LibraryStore, song: SongRow): Pair<String, Path> {
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        return "$artist/$title" to lib.libraryDir.toPath().resolve(artist).resolve(title)
    }

    /** `song_dir(library_dir, song) / safe_name(name)`: its path relative to the library ("Artist/Title/name", as
     * `files.path` holds it) and the path itself. */
    fun file(lib: LibraryStore, song: SongRow, name: String): Pair<String, Path> {
        val (rel, dir) = folder(lib, song)
        val safe = SafeName.safeName(name)
        return "$rel/$safe" to dir.resolve(safe)
    }

    /** A path relative to the library, as `files.path` holds one, under [lib]'s folder. */
    fun under(lib: LibraryStore, rel: String): Path = lib.libraryDir.toPath().resolve(rel)

    /** library.holds: whether the regular file at [path] (never a link, a folder or anything else in its place)
     * holds the bytes whose SHA-256 is [sha256]; with [size], a file of another length fails unread. Any failure to
     * look or read is false, as open_regular's OSError is. */
    fun holds(path: Path, sha256: String, size: Long?): Boolean {
        return try {
            val attrs = LibraryFiles.entry(path) ?: return false
            if (!attrs.isRegularFile) return false
            FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { ch ->
                if (size != null && ch.size() != size) return false
                val digest = MessageDigest.getInstance("SHA-256")
                val buffer = ByteBuffer.allocate(1 shl 16)
                while (ch.read(buffer) >= 0) {
                    buffer.flip()
                    digest.update(buffer)
                    buffer.clear()
                }
                JsonText.hex(digest.digest()) == sha256
            }
        } catch (_: IOException) {
            false
        }
    }

    private val random = SecureRandom()

    /** `.<name>.<8 hex>.tmp`: secrets.token_hex(4)'s name, beside the file. */
    fun temporary(name: String): String {
        val bytes = ByteArray(4).also { random.nextBytes(it) }
        return ".$name.${JsonText.hex(bytes)}.tmp"
    }

    /**
     * library.write_atomic: the folders made, the bytes written to a file of a random name beside [path] created
     * exclusively (CREATE_NEW, O_EXCL: a link waiting at a name is never written through) with the process's own
     * mode (never mkstemp's 0600), synced, then renamed over [path] (a link there is replaced, never followed), and
     * the folder synced; the bytes' SHA-256.
     */
    fun writeAtomic(path: Path, data: ByteArray): String {
        val dir = path.toAbsolutePath().parent
        Files.createDirectories(dir)
        val tmp = dir.resolve(temporary(path.fileName.toString()))
        try {
            FileChannel.open(tmp, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { ch ->
                val buffer = ByteBuffer.wrap(data)
                while (buffer.hasRemaining()) ch.write(buffer)
                ch.force(true)
            }
            Files.move(tmp, path, StandardCopyOption.ATOMIC_MOVE)
        } catch (e: Throwable) {
            try {
                Files.deleteIfExists(tmp)
            } catch (undoing: IOException) {
                e.addSuppressed(undoing)
            }
            throw e
        }
        syncFolder(dir)
        return Canonical.sha256Hex(data)
    }

    /** The folder's entries to the disk, as os.fsync of its descriptor: a sync that fails raises, as Python's does,
     * so no caller records a file the rename may not have put on the disk. Only a platform that can't open a folder
     * as a channel at all (none caracole runs on: Linux and Android can) leaves it to the file system. */
    private fun syncFolder(dir: Path) {
        val folder = try {
            FileChannel.open(dir, StandardOpenOption.READ)
        } catch (_: IOException) {
            return
        }
        folder.use { it.force(true) }
    }
}
