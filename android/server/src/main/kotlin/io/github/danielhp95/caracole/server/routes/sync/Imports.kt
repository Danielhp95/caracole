package io.github.danielhp95.caracole.server.routes.sync

import io.github.danielhp95.caracole.core.py.Py
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.SecureRandom

/**
 * A file to import, staged on the phone part by part (peer_import.py's, the sync redesign's §3.4.2): what the phone's
 * import routes keep of a `.caracole` file (or an index export) the page sends, until the import's job takes it.
 *
 * The page sends a file in parts: [open] makes its folder, `stateDir/peer/import-<16 hex>/` (0700), with `open.json`
 * (the size the page said, its name, when it was opened) and `file.caracole`, the file as it comes (0600); [addPart]
 * writes each part where the last one ended, at most [PART_MAX] a part, refusing a part that isn't the next one or
 * would pass the size; [whole] is the file once every part has come. The import's job [held]s it while it reads it,
 * and [remove]s it once it is over.
 *
 * Nothing of it goes into the library. An import's id is 16 hex, checked before any path is built of it. At most
 * [OPEN] import is here at once, sent or being sent, and a file is at most [IMPORT_MAX]. One untouched for [EXPIRES]
 * (an hour, by [clock]) is deleted ([sweep]: as one is opened, as an import ends), unless the job holds it. The words of
 * each refusal ([StagingError], with the status the route answers it with) are peer_import.py's.
 */
class Imports(stateDir: File, private val clock: () -> Long = System::currentTimeMillis) {
    /** `stateDir/peer`, a push's and an import's folder as caracole serve's (peer_push.FOLDER). */
    val root = File(stateDir, FOLDER)

    /** An import, or a part of one, refused: why, in a sentence, and the status the route answers it with. */
    class StagingError(message: String, val status: Int = 400) : Exception(message)

    private val lock = Any()
    private val holds = HashMap<String, Int>()

    /** The folder of the import [importId] names: the one path built of an id, once it is checked. */
    fun folderOf(importId: String): File = File(root, PREFIX + checkId(importId))

    /**
     * An import opened for a file of [size] bytes named [name] (null for a size or a name that isn't one): its folder
     * made, its id; [StagingError] for a size that isn't one (400) or is past [IMPORT_MAX] (413), before anything is
     * made, and with [OPEN] imports here already (409). Imports untouched for an hour go first ([sweep]).
     */
    fun open(size: Long?, name: String?): String {
        if (size == null || size <= 0) throw StagingError("How big is the file? Its size is a number of bytes.")
        if (size > IMPORT_MAX) throw StagingError(TOO_BIG, 413)
        if (name == null) throw StagingError("What is the file called? Its name is text.")
        sweep()
        synchronized(lock) {
            if (imports().size >= OPEN) throw StagingError(BUSY, 409)
            privateDir(root)
            var folder = File(root, PREFIX + token())
            var tries = 0
            while (!folder.mkdir()) {
                if (++tries >= 8) throw IOException("no folder can be made in $root")
                folder = File(root, PREFIX + token())
            }
            privateDir(folder, made = true)
            val now = clock()
            val file = File(folder, FILE)
            createPrivate(file)
            val opened = JsonObject(linkedMapOf("size" to JsonPrimitive(size), "name" to JsonPrimitive(Py.slice(name, null, 255)),
                                                "opened" to JsonPrimitive(now / 1000.0)))
            writePrivate(File(folder, OPENED), opened.toString().toByteArray(Charsets.UTF_8))
            for (made in listOf(file, File(folder, OPENED), folder)) made.setLastModified(now)
            return folder.name.removePrefix(PREFIX)
        }
    }

    /**
     * A part of the import [importId]'s file, written at [at], where what it has ends: how much it has then;
     * [StagingError] for no such import (404), a part not at the end of what it has or that would pass its size, or
     * one past [PART_MAX] (400). What it had stays as it was.
     */
    fun addPart(importId: String, at: Long, data: ByteArray): Long {
        checkId(importId)
        if (data.size > PART_MAX) throw StagingError("A part is 8 MiB at most: send it in smaller parts.")
        synchronized(lock) {
            val folder = folderOf(importId)
            val size = opened(folder)?.first ?: throw StagingError(NO_SUCH, 404)
            val file = File(folder, FILE)
            val have = sizeOf(file)
            if (at != have || have + data.size > size) throw StagingError(NOT_NEXT)
            RandomAccessFile(file, "rw").use { out ->
                out.seek(at)
                out.write(data)
            }
            val now = clock()
            file.setLastModified(now)
            folder.setLastModified(now)
            return have + data.size
        }
    }

    /** The import [importId]'s file, once every part has come; [StagingError] else. */
    fun whole(importId: String): File = synchronized(lock) {
        val folder = folderOf(importId)
        val size = opened(folder)?.first ?: throw StagingError(NO_SUCH, 404)
        val file = File(folder, FILE)
        if (sizeOf(file) != size) throw StagingError(NOT_WHOLE)
        file
    }

    /** The name the file staged as [importId] was sent under (an index export's name is its own). */
    fun openedName(importId: String): String =
        synchronized(lock) { opened(folderOf(importId))?.second?.takeIf { it.isNotEmpty() } ?: FILE }

    /** The import [importId] held while [block] reads it (its folder), so that no [sweep] deletes it meanwhile;
     * [StagingError] when it is gone (left over an hour). */
    fun <T> held(importId: String, block: (File) -> T): T {
        val folder = synchronized(lock) {
            val folder = folderOf(importId)
            if (opened(folder) == null) throw StagingError(GONE, 404)
            holds[importId] = (holds[importId] ?: 0) + 1
            folder
        }
        try {
            return block(folder)
        } finally {
            synchronized(lock) {
                val left = (holds[importId] ?: 1) - 1
                if (left > 0) holds[importId] = left else holds.remove(importId)
            }
        }
    }

    /** The import [importId]'s folder deleted, all of it (once it is taken, or refused). */
    fun remove(importId: String) {
        synchronized(lock) { folderOf(importId).deleteRecursively() }
    }

    /** Delete each import untouched for [EXPIRES], unless it is [held]; the ids deleted. */
    fun sweep(): List<String> {
        val now = clock()
        val gone = ArrayList<String>()
        synchronized(lock) {
            for (folder in imports()) {
                val id = folder.name.removePrefix(PREFIX)
                if (now - touched(folder) <= EXPIRES || id in holds) continue
                folder.deleteRecursively()
                gone.add(id)
            }
        }
        return gone
    }

    /** The imports' folders under [root], by their names alone. */
    private fun imports(): List<File> = root.listFiles().orEmpty().filter {
        it.name.startsWith(PREFIX) && ID.matches(it.name.removePrefix(PREFIX)) &&
            Files.isDirectory(it.toPath(), LinkOption.NOFOLLOW_LINKS)
    }

    /** When the import in [folder] last changed: opened, or a part written. */
    private fun touched(folder: File): Long =
        listOf(folder, File(folder, FILE), File(folder, OPENED)).filter { it.exists() }.maxOfOrNull { it.lastModified() } ?: 0L

    /** What `open.json` says: the size and the name; null for an import that isn't there, or a size that isn't one. */
    private fun opened(folder: File): Pair<Long, String?>? {
        val file = File(folder, OPENED)
        if (!Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) return null
        val read = try {
            Json.parseToJsonElement(file.readText(Charsets.UTF_8)) as? JsonObject
        } catch (e: IOException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        } ?: return null
        val size = (read["size"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return null
        return size to (read["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    }

    private fun sizeOf(file: File): Long {
        if (!Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) throw StagingError(NO_SUCH, 404)
        return file.length()
    }

    private fun checkId(importId: String): String {
        if (!ID.matches(importId)) throw StagingError("Which import? Its id is 16 hex.")
        return importId
    }

    companion object {
        const val FOLDER = "peer"
        const val OPEN = 1
        const val PART_MAX = 8 * 1024 * 1024
        const val EXPIRES = 3_600_000L
        const val PREFIX = "import-"
        const val FILE = "file.caracole"
        const val OPENED = "open.json"

        /** peer_file.IMPORT_MAX: a file to import, at most 8 GiB. */
        const val IMPORT_MAX = 8L * 1024 * 1024 * 1024

        const val TOO_BIG = "That file is too big: a file to import is at most 8 GiB."
        const val BUSY = "A file is being sent here already: try again once it is taken, or in an hour."
        const val NOT_NEXT = "That part isn't the next one: choose the file again."
        const val NO_SUCH = "No such import is open here: choose the file again."
        const val NOT_WHOLE = "That file isn't whole yet: send the rest of it."
        const val GONE = "That file is gone: it was left over an hour. Choose it again."

        val ID = Regex("[0-9a-f]{16}")

        private val random = SecureRandom()

        internal fun token(): String = ByteArray(8).also(random::nextBytes).joinToString("") { "%02x".format(it) }

        /** [dir] made (with its parents) and private, 0700; [made] when it was made just now. */
        internal fun privateDir(dir: File, made: Boolean = false) {
            if (!made && !dir.isDirectory) {
                dir.mkdirs()
                if (!dir.isDirectory) throw IOException("the folder $dir can't be made")
            }
            try {
                Files.setPosixFilePermissions(dir.toPath(), PosixFilePermissions.fromString("rwx------"))
            } catch (e: UnsupportedOperationException) {
                dir.setReadable(false, false); dir.setReadable(true, true)
                dir.setWritable(false, false); dir.setWritable(true, true)
                dir.setExecutable(false, false); dir.setExecutable(true, true)
            }
        }

        /** [file] made new and private, 0600; an IOException when it is there already. */
        internal fun createPrivate(file: File) {
            try {
                Files.createFile(file.toPath(), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))
            } catch (e: UnsupportedOperationException) {
                Files.createFile(file.toPath())
                file.setReadable(false, false); file.setReadable(true, true)
                file.setWritable(false, false); file.setWritable(true, true)
            }
        }

        /** [bytes] written whole as [file], private: a temporary file beside it, then renamed over it. */
        internal fun writePrivate(file: File, bytes: ByteArray) {
            val tmp = File(file.parentFile, ".${file.name}.${token()}")
            try {
                createPrivate(tmp)
                tmp.outputStream().use { it.write(bytes) }
                Files.move(tmp.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING)
            } finally {
                tmp.delete()
            }
        }
    }
}
