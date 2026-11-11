package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.sites.GtpTabsFetch
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.NotDirectoryException
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.FileTime
import java.security.SecureRandom
import java.time.Duration
import java.time.Instant

/**
 * The files shared to the app that wait to be filed, the phone's `_inbox/`: `stateDir/inbox/`, each under the name it
 * was shared by (made a file's name: [nameFor]), one a name (" (2)" before the extension of a second one, which
 * parse_download_name drops as a browser's), the time it was staged its modification time. A file waits [DAYS] days
 * for a song that fits ([sweep]), as `_inbox/` keeps one until a song fits; one filed is dropped ([drop]). A filing
 * that failed is remembered by the file's name in `.failed/` ([failed], [failedAt]), so the phone tries it again only
 * after a sync or a day on, never after every job. Only regular files are read: a link is never followed, and a name
 * that begins with a dot (a file being staged, the failures' folder) is none of them.
 */
class InboxFolder(val dir: File) {
    /** [data] staged as [name] (one of [nameFor]'s: an extension inbox.py files) at [now], under a name of its own
     * when another file waits under it; the name it waits under. */
    fun stage(name: String, data: ByteArray, now: Instant): String {
        require(Inbox.keeps(name) && '/' !in name && !name.startsWith(".")) { "no name to stage a file by: $name" }
        dir.mkdirs()
        val folder = dir.toPath()
        val tmp = folder.resolve(".staging.${hex(8)}.tmp")
        try {
            FileChannel.open(tmp, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { ch ->
                val buffer = ByteBuffer.wrap(data)
                while (buffer.hasRemaining()) ch.write(buffer)
                ch.force(true)
            }
            Files.setLastModifiedTime(tmp, FileTime.from(now))
            synchronized(LOCK) {
                val free = free(name)
                Files.move(tmp, folder.resolve(free), StandardCopyOption.ATOMIC_MOVE)
                marker(free)?.let(Files::deleteIfExists)  // a failure of a file gone before is none of this one's
                return free
            }
        } finally {
            Files.deleteIfExists(tmp)
        }
    }

    /** The names of the files that wait, in code point order (file_inbox's sorted entries): regular files, none that
     * begins with a dot. */
    fun waiting(): List<String> {
        val names = ArrayList<String>()
        try {
            Files.newDirectoryStream(dir.toPath()).use { entries ->
                for (entry in entries) {
                    val name = entry.fileName.toString()
                    if (!name.startsWith(".") && attributes(entry)?.isRegularFile == true) names += name
                }
            }
        } catch (_: NoSuchFileException) {
        }
        return names.sortedWith(Py.CODE_POINT_ORDER)
    }

    /** The bytes of the file waiting as [name]; null when none does (or a link, a folder, anything but a regular file,
     * is there). */
    fun read(name: String): ByteArray? {
        val path = at(name) ?: return null
        if (attributes(path)?.isRegularFile != true) return null
        return try {
            FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { ch ->
                val out = ByteBuffer.allocate(Math.toIntExact(ch.size()))
                while (out.hasRemaining() && ch.read(out) >= 0) Unit
                out.array().copyOf(out.position())
            }
        } catch (_: IOException) {
            null
        }
    }

    /** When the file waiting as [name] was staged; null when none waits. */
    fun stagedAt(name: String): Instant? = at(name)?.let(::attributes)?.takeIf { it.isRegularFile }?.lastModifiedTime()
        ?.toInstant()

    /** The file waiting as [name] dropped (filed, or kept too long), its failure forgotten; nothing when none waits.
     * A link there is deleted, never followed. */
    fun drop(name: String) {
        val path = at(name) ?: return
        Files.deleteIfExists(path)
        marker(name)?.let(Files::deleteIfExists)
    }

    /** Filing the file waiting as [name] failed at [now] (a shared folder, a full disk): remembered until it is
     * filed, dropped or failed again. */
    fun failed(name: String, now: Instant) {
        val file = at(name) ?: return
        if (attributes(file)?.isRegularFile != true) return
        val folder = dir.toPath().resolve(FAILED)
        if (attributes(folder) == null) Files.createDirectory(folder)
        val marker = marker(name) ?: return  // a link or a file in the folder's place: never followed, nothing kept
        Files.write(marker, ByteArray(0), StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)
        Files.setLastModifiedTime(marker, FileTime.from(now))
    }

    /** When filing the file waiting as [name] last failed; null when it hasn't since it was staged. */
    fun failedAt(name: String): Instant? =
        marker(name)?.let(::attributes)?.takeIf { it.isRegularFile }?.lastModifiedTime()?.toInstant()

    /** The files that waited [DAYS] days or more by [now] dropped, and a staging left behind a day ago; the names
     * dropped of the files that waited. */
    fun sweep(now: Instant): List<String> {
        val dropped = ArrayList<String>()
        val oldest = now.minus(Duration.ofDays(DAYS))
        try {
            Files.newDirectoryStream(dir.toPath()).use { entries ->
                for (entry in entries) {
                    val attrs = attributes(entry) ?: continue
                    val name = entry.fileName.toString()
                    val at = attrs.lastModifiedTime().toInstant()
                    if (name.startsWith(".")) {
                        if (attrs.isRegularFile && at < now.minus(Duration.ofDays(1))) Files.deleteIfExists(entry)
                    } else if (attrs.isRegularFile && at <= oldest) {
                        Files.deleteIfExists(entry)
                        dropped += name
                    }
                }
            }
        } catch (_: NoSuchFileException) {
        }
        val failures = failures()
        if (failures != null) {
            try {  // the failures of files no longer waiting forgotten
                Files.newDirectoryStream(failures).use { entries ->
                    for (entry in entries) {
                        if (attributes(dir.toPath().resolve(entry.fileName.toString()))?.isRegularFile != true) {
                            Files.deleteIfExists(entry)
                        }
                    }
                }
            } catch (_: NoSuchFileException) {
            } catch (_: NotDirectoryException) {
            }
        }
        return dropped.sortedWith(Py.CODE_POINT_ORDER)
    }

    /** The path of a file named [name] in the folder; null for a name that can't be one of its files. */
    private fun at(name: String): Path? =
        if (name.isEmpty() || '/' in name || name.startsWith(".") || '\u0000' in name) null else dir.toPath().resolve(name)

    /** The folder of the failures remembered, when it is one (never a link to one); null else. */
    private fun failures(): Path? =
        dir.toPath().resolve(FAILED).takeIf { attributes(it)?.isDirectory == true }

    /** Where a failure to file the file waiting as [name] is remembered; null for a name that can't be one, or with
     * no folder of the failures. */
    private fun marker(name: String): Path? = at(name)?.let { failures()?.resolve(name) }

    /** [name], or "<stem> (2)<ext>", " (3)"… : the first no file of the folder has. */
    private fun free(name: String): String {
        val ext = name.substring(name.length - PyPath.suffix(name).length)
        val stem = name.substring(0, name.length - ext.length)
        var n = 1
        while (true) {
            val candidate = if (n == 1) name else "$stem ($n)$ext"
            if (!Files.exists(dir.toPath().resolve(candidate), LinkOption.NOFOLLOW_LINKS)) return candidate
            n++
        }
    }

    companion object {
        /** How many days a file waits for a song that fits. */
        const val DAYS = 30L

        /** The folder of the failures remembered. */
        const val FAILED = ".failed"

        /** A file's name is at most this many bytes of UTF-8, room left for " (99)" under a file system's 255. */
        const val MAX_NAME_BYTES = 240

        /** The name of a file shared with none. */
        const val NO_NAME = "shared file"

        /** The extension a file of these types is given when its name has none inbox.py files (a share's MIME type,
         * as the manifest names them). */
        val TYPE_EXTENSIONS: Map<String, String> = mapOf(
            "application/pdf" to ".pdf", "audio/midi" to ".mid", "audio/x-midi" to ".mid",
            "application/vnd.recordare.musicxml" to ".mxl", "application/vnd.recordare.musicxml+xml" to ".musicxml",
            "application/x-musescore" to ".mscz",
        )

        private val LOCK = Any()
        private val random = SecureRandom()

        /**
         * The name a shared file waits under: the name it was shared by ([shared], a content provider's display
         * name or its address's last part: its last path part, PurePosixPath's name, less NULs and the dots it begins
         * with, which would hide it), else [NO_NAME]; one whose extension inbox.py files nothing of gets the one its
         * bytes tell (gtptabs.sniff: a Guitar Pro or Power Tab file's), else its [type]'s ([TYPE_EXTENSIONS]),
         * after it; at most [MAX_NAME_BYTES] bytes, its stem cut by whole code points. A name that still has no
         * extension inbox.py files is no file to stage: [Inbox.keeps] says so.
         */
        fun nameFor(shared: String?, type: String?, data: ByteArray): String {
            val last = shared.orEmpty().split('/').lastOrNull { it.isNotEmpty() && it != "." }.orEmpty()
            var name = PyText.strip(PyText.strip(last.replace("\u0000", "")).trimStart('.')).ifEmpty { NO_NAME }
            if (!Inbox.keeps(name)) {
                val ext = GtpTabsFetch.sniff(data)
                    ?: type?.let { TYPE_EXTENSIONS[PyText.strip(PyText.asciiLower(it).substringBefore(';'))] }
                if (ext != null) name += ext
            }
            return shortened(name)
        }

        /** [name] within [MAX_NAME_BYTES] bytes of UTF-8: its stem cut by whole code points, its extension kept. */
        private fun shortened(name: String): String {
            if (name.toByteArray(Charsets.UTF_8).size <= MAX_NAME_BYTES) return name
            val ext = PyPath.suffix(name).takeIf { it.length < 16 }.orEmpty()
            var stem = name.substring(0, name.length - ext.length)
            val room = MAX_NAME_BYTES - ext.toByteArray(Charsets.UTF_8).size
            while (stem.isNotEmpty() && stem.toByteArray(Charsets.UTF_8).size > room) {
                stem = stem.substring(0, stem.offsetByCodePoints(stem.length, -1))
            }
            return PyText.strip(stem) + ext
        }

        private fun attributes(path: Path): BasicFileAttributes? = try {
            Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        } catch (_: IOException) {
            null
        }

        private fun hex(bytes: Int): String = buildString {
            for (b in ByteArray(bytes).also { random.nextBytes(it) }) {
                append("0123456789abcdef"[(b.toInt() shr 4) and 15]).append("0123456789abcdef"[b.toInt() and 15])
            }
        }
    }
}
