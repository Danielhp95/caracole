package io.github.danielhp95.caracole.mirror

import java.io.File
import java.io.IOException
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.SecureRandom
import java.util.concurrent.locks.ReentrantLock

/**
 * The copy of the library on the phone, in [dir] (the app's files folder): each file once, by its content,
 * as `blobs/<sha256>`, and `manifest.json`, the server's list as last synced whole, which says what each path
 * is. Only a sync writes here ([SyncEngine], one at a time under [syncLock]); the WebView reads through
 * [lookup], which keeps the list it read until [reload].
 */
class Mirror(val dir: File) {
    val blobs = File(dir, "blobs")
    val manifestFile = File(dir, "manifest.json")

    /** Held by a sync from its first request to its clean-up. */
    val syncLock = ReentrantLock()

    @Volatile private var current: Manifest? = null
    @Volatile private var loaded = false

    /** The list the mirror shows, read once; null when no sync ever ended (or the list can't be read). */
    fun manifest(): Manifest? = if (loaded) current else reload()

    /** Reads `manifest.json` again (after a sync swapped a new one in). */
    @Synchronized
    fun reload(): Manifest? {
        current = try {
            if (manifestFile.isFile) Manifest.parse(manifestFile.readBytes()) else null
        } catch (e: SyncError) {
            null
        } catch (e: IOException) {
            null
        }
        loaded = true
        return current
    }

    fun blob(sha256: String) = File(blobs, sha256)

    /** The file at [path] in the mirror (its entry and its bytes on disk), or null when it holds none. */
    fun lookup(path: String): Served? {
        val entry = manifest()?.byPath?.get(path) ?: return null
        val file = blob(entry.sha256)
        return if (file.isFile) Served(entry, file) else null
    }

    /** What the WebView gets for [path] under the mirror's prefix: the file as listed, or a 404. */
    fun respond(path: String): Response {
        val served = lookup(path) ?: return Response.NOT_FOUND
        val entry = served.entry
        return Response(200, "OK", entry.mimeType, entry.charset, entry.headers, served.file)
    }

    /** The bytes the mirror takes on the phone. */
    fun storageBytes(): Long =
        (blobs.listFiles()?.sumOf { if (it.isFile) it.length() else 0L } ?: 0L) +
            (if (manifestFile.isFile) manifestFile.length() else 0L)

    /** Writes [bytes] as the new `manifest.json` whole: a temporary file, synced, then renamed over it. */
    internal fun swapManifest(bytes: ByteArray) {
        val tmp = File(dir, "$TMP${token()}")
        try {
            tmp.outputStream().use { out ->
                out.write(bytes)
                out.fd.sync()
            }
            moveOver(tmp, manifestFile)
        } finally {
            tmp.delete()
        }
    }

    /** Deletes the blobs no entry of [keep] names, and every temporary file a sync left. */
    internal fun cleanUp(keep: Manifest?) {
        val wanted = keep?.entries?.mapTo(HashSet()) { it.sha256 } ?: emptySet()
        blobs.listFiles()?.forEach { if (it.name !in wanted) it.delete() }
        removeTemporaries()
    }

    internal fun removeTemporaries() {
        blobs.listFiles()?.forEach { if (it.name.startsWith(TMP)) it.delete() }
        dir.listFiles()?.forEach { if (it.name.startsWith(TMP)) it.delete() }
    }

    internal fun newTemporary(): File = File(blobs, "$TMP${token()}")

    companion object {
        /** The prefix of every temporary file a sync writes. */
        const val TMP = ".tmp-"

        private val random = SecureRandom()

        private fun token(): String {
            val bytes = ByteArray(8).also { random.nextBytes(it) }
            return bytes.joinToString("") { "%02x".format(it) }
        }

        internal fun moveOver(from: File, to: File) {
            try {
                Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (e: AtomicMoveNotSupportedException) {
                Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        }
    }
}

/** A file the mirror holds: its [entry] in the list and its bytes, [file]. */
data class Served(val entry: Entry, val file: File)

/**
 * An answer for the WebView, as Android's WebResourceResponse takes one: a [status] and its [reason], the
 * [mimeType] and [charset], the [headers], and the [file] whose bytes are the body (none for a 404).
 */
data class Response(
    val status: Int,
    val reason: String,
    val mimeType: String,
    val charset: String?,
    val headers: Map<String, String>,
    val file: File?,
) {
    companion object {
        val NOT_FOUND = Response(404, "Not Found", "text/plain", "utf-8", emptyMap(), null)
    }
}
