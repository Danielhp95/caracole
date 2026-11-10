package io.github.danielhp95.caracole.mirror

import java.io.File
import java.io.IOException
import java.io.InputStream
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
 *
 * Beside it, in `layers/`, the pages files held of the units the phone took from them ([Layer], [takeLayer]), which
 * [pageFor] serves where the computer's page isn't the phone's; the computer's sync never touches them.
 */
class Mirror(val dir: File) {
    val blobs = File(dir, "blobs")
    val manifestFile = File(dir, "manifest.json")

    /** The layers' folder: `layers/<id>/` each ([Layer]). */
    val layersDir = File(dir, "layers")

    /** Held by a sync from its first request to its clean-up. */
    val syncLock = ReentrantLock()

    @Volatile private var current: Manifest? = null
    @Volatile private var loaded = false
    @Volatile private var layersRead: List<Layer>? = null

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

    /** The bytes the mirror takes on the phone, its layers' with it. */
    fun storageBytes(): Long =
        (blobs.listFiles()?.sumOf { if (it.isFile) it.length() else 0L } ?: 0L) +
            (if (manifestFile.isFile) manifestFile.length() else 0L) +
            layers().sumOf { it.bytes() }

    /** The layers, those of `layers/<16 hex>/` with a list it can read, the newest taken first; read once, until a
     * [takeLayer] here. */
    fun layers(): List<Layer> = layersRead ?: readLayers(layersDir).also { layersRead = it }

    /**
     * Keeps the pages of [units] that a file's list of pages, [manifest] (its `pages.json`: `GET /api/offline`'s
     * format 1), names, and its start page, as the layer [id] (the 16 hex of the caracole that exported it), each
     * page's bytes from [blob] by its SHA-256; the layer becomes the newest. A layer taken before under that id keeps
     * its pages of other units and loses those of [units] and its start page. Each blob is checked by its size and
     * its SHA-256 as it is written, then the layer's list is written whole and the blobs it no longer names are
     * deleted, so a page the file lacks or holds otherwise than listed fails it ([LayerError]) and leaves the layer as
     * it was. Each page is kept as the phone serves it ([LayerPolicy]: a kind caracole serves alone, a page in a
     * sandbox), never with the headers the file gave. With a [gate], the layers are then cut to the pages it still
     * serves ([pruneLayers]: a page of a unit the phone changed or removed since goes, a layer left with no page
     * goes). One at a time, as a sync of the computer's is ([syncLock]).
     */
    fun takeLayer(id: String, manifest: ByteArray, units: Set<String>, gate: UnitGate? = null,
                  blob: (String) -> InputStream?) {
        syncLock.lock()
        try {
            val taken = (readLayers(layersDir).maxOfOrNull { it.taken } ?: 0L) + 1
            try {
                writeLayer(layersDir, id, manifest, units, taken, blob)
                gate?.let { pruneLayers(layersDir, it) }
            } finally {
                layersRead = null
            }
        } finally {
            syncLock.unlock()
        }
    }

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

        internal fun token(): String {
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

/** Whether the mirror may serve a file of a unit as the computer made it: the phone's own state decides. */
fun interface UnitGate {
    /** [unit] as the file's entry names it, and its digest when the computer made the list. */
    fun check(unit: String, digest: String?): Gate
}

enum class Gate {
    /** The phone holds the unit as the computer did (or holds none of it): the file is served. */
    SERVE,

    /** The phone changed the unit since: the computer's page is no longer the song's. */
    CHANGED,

    /** The phone removed the song. */
    REMOVED,
}

/** What the mirror has at a path, once its unit is checked. */
sealed interface Looked {
    /** The file, to serve as its entry says. */
    data class Page(val entry: Entry, val file: File) : Looked

    /** A file the [gate] keeps back. */
    data class Gated(val entry: Entry, val gate: Gate) : Looked

    /** No file at that path. */
    data object Missing : Looked
}

/**
 * The mirror's file at [path], checked by [gate] when its entry names a unit: the computer's when the gate serves it
 * (or it names no unit); else the first layer's ([Mirror.layers], the newest first) of a unit the gate serves, at a
 * path the computer's list gives no other unit (a file's page never stands for another song's, as in a folder two
 * songs share); else what the computer's answered (Gated), or where the computer has nothing at [path], the first
 * layer's (Gated), or Missing. A layer's file of no unit (its start page) is never served: the phone's library page
 * is its own.
 */
fun Mirror.pageFor(path: String, gate: UnitGate): Looked {
    val listed = lookup(path)
    val computers = listed?.let { checked(it, gate) }
    if (computers is Looked.Page) return computers
    var layers: Looked.Gated? = null
    for (layer in layers()) {
        val found = layer.lookup(path) ?: continue
        if (found.entry.unit == null) continue
        if (listed != null && listed.entry.unit != found.entry.unit) continue
        // As the phone serves a file's page, whatever its list on disk says (LayerPolicy is idempotent).
        val served = Served(LayerPolicy.served(found.entry) ?: continue, found.file)
        when (val looked = checked(served, gate)) {
            is Looked.Page -> return looked
            is Looked.Gated -> if (layers == null) layers = looked
            Looked.Missing -> {}
        }
    }
    return computers ?: layers ?: Looked.Missing
}

private fun checked(served: Served, gate: UnitGate): Looked {
    val unit = served.entry.unit ?: return Looked.Page(served.entry, served.file)
    return when (val checked = gate.check(unit, served.entry.digest)) {
        Gate.SERVE -> Looked.Page(served.entry, served.file)
        else -> Looked.Gated(served.entry, checked)
    }
}
