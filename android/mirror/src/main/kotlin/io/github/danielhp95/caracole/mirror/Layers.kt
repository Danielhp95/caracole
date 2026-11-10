package io.github.danielhp95.caracole.mirror

import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest

/**
 * A file's pages on the phone, beside the computer's mirror: the pages a `.caracole` file held of the units the phone
 * took from it, and the file's start page (its library page, whose cards the phone's library page reads of a song the
 * computer has no card of), in `layers/<id>/` of the mirror's folder, one layer a caracole that exported a file ([id],
 * the 16 hex of its kv `sync:id`).
 *
 * A layer is laid out as the mirror is: `manifest.json`, its list (`GET /api/offline`'s format 1, with `taken`, the
 * order it was taken in), and `blobs/<sha256>`, each page once. Only [Mirror.takeLayer] writes one; the computer's
 * sync never touches it ([Mirror.cleanUp] deletes the computer's blobs alone). [Mirror.pageFor] serves a layer's page
 * of a unit where the computer's isn't the phone's (the sync redesign's §10, Task 31): a song taken from a file opens
 * the file's sheet until the computer makes its own of the song as the phone holds it.
 */
class Layer(val id: String, val dir: File) {
    val blobs = File(dir, "blobs")
    val manifestFile = File(dir, "manifest.json")

    private val read: Pair<Manifest, Long>? by lazy { readList(manifestFile) }

    /** Its list, or null when it has none it can read. */
    fun manifest(): Manifest? = read?.first

    /** When it was taken, against the other layers: the newest is the highest. */
    val taken: Long get() = read?.second ?: -1L

    fun blob(sha256: String) = File(blobs, sha256)

    /** The page at [path] in this layer (its entry and its bytes on disk), or null when it holds none. */
    fun lookup(path: String): Served? {
        val entry = manifest()?.byPath?.get(path) ?: return null
        val file = blob(entry.sha256)
        return if (file.isFile) Served(entry, file) else null
    }

    internal fun bytes(): Long =
        (blobs.listFiles()?.sumOf { if (it.isFile) it.length() else 0L } ?: 0L) +
            (if (manifestFile.isFile) manifestFile.length() else 0L)

    companion object {
        /** A layer's id: the 16 hex of the caracole whose file it holds the pages of. */
        val ID = Regex("[0-9a-f]{16}")

        private fun readList(file: File): Pair<Manifest, Long>? = try {
            if (!file.isFile) {
                null
            } else {
                val bytes = file.readBytes()
                val taken = (Json.parse(String(bytes, Charsets.UTF_8)) as? Map<*, *>)?.get("taken") as? Long ?: 0L
                Manifest.parse(bytes) to taken
            }
        } catch (e: SyncError) {
            null
        } catch (e: Json.Malformed) {
            null
        } catch (e: IOException) {
            null
        }
    }
}

/** Why a file's pages couldn't be kept as a layer, in a sentence the import says; the layer is as it was. */
class LayerError(message: String, cause: Throwable? = null) : Exception(message, cause)

/** The mirror's layers: those of `layers/` with a list it can read, the newest taken first (ties by id). */
internal fun readLayers(root: File): List<Layer> =
    root.listFiles().orEmpty()
        .filter { Layer.ID.matches(it.name) && it.isDirectory }
        .map { Layer(it.name, it) }
        .filter { it.manifest() != null }
        .sortedWith(compareByDescending<Layer> { it.taken }.thenBy { it.id })

/**
 * Keeps [manifest]'s pages of [units] and its start page as the layer [id], each page's bytes from [blob], under
 * [root] (`layers/`), the order it is taken in [taken]. What the layer had of other units stays; what it had of these
 * goes. Each blob the layer lacks is written to a temporary file, checked by its size and its SHA-256, then renamed;
 * then the list is written whole over the old one, and the blobs it no longer names are deleted. A page the file
 * lacks, or whose bytes aren't the ones listed, fails it ([LayerError]) with the layer as it was.
 */
internal fun writeLayer(root: File, id: String, manifest: ByteArray, units: Set<String>, taken: Long,
                        blob: (String) -> InputStream?) {
    require(Layer.ID.matches(id)) { "a layer's id is 16 lowercase hex, not “${id.take(40)}”" }
    val given = try {
        Manifest.parse(manifest)
    } catch (e: SyncError) {
        throw LayerError("The file's list of pages can't be used: ${e.message}", e)
    }
    val layer = Layer(id, File(root, id))
    val before = layer.manifest()
    val start = given.byPath.getValue(given.start)
    val took = given.entries.filter { it.path != given.start && it.unit != null && it.unit in units }
    val paths = took.mapTo(HashSet()) { it.path }.apply { add(given.start) }
    val kept = before?.entries.orEmpty().filter { it.unit != null && it.unit !in units && it.path !in paths }
    val entries = listOf(start) + took + kept

    val written = ArrayList<File>()
    try {
        layer.blobs.mkdirs()
        if (!layer.blobs.isDirectory) throw LayerError("The phone's storage failed: the folder ${layer.blobs} can't be made.")
        removeTemporaries(layer)
        for (entry in entries.distinctBy { it.sha256 }) {
            val file = layer.blob(entry.sha256)
            if (file.isFile) continue
            copyChecked(layer, entry, blob, file)
            written.add(file)
        }
        swap(layer, listJson(given.start, taken, entries).toByteArray(Charsets.UTF_8))
    } catch (e: IOException) {
        written.forEach { it.delete() }
        throw LayerError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", e)
    } catch (e: Throwable) {
        written.forEach { it.delete() }
        throw e
    } finally {
        removeTemporaries(layer)
    }
    val named = entries.mapTo(HashSet()) { it.sha256 }
    layer.blobs.listFiles()?.forEach { if (it.name !in named) it.delete() }
}

private fun copyChecked(layer: Layer, entry: Entry, blob: (String) -> InputStream?, to: File) {
    val tmp = File(layer.blobs, "${Mirror.TMP}${Mirror.token()}")
    try {
        val input = blob(entry.sha256) ?: throw LayerError("The file holds no page “${entry.path}” it lists: export it again.")
        val digest = MessageDigest.getInstance("SHA-256")
        var total = 0L
        input.use { source ->
            tmp.outputStream().use { out ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val room = (entry.size - total).coerceAtMost(buffer.size.toLong() - 1).toInt() + 1
                    val n = source.read(buffer, 0, room)
                    if (n < 0) break
                    total += n
                    if (total > entry.size) throw notListed(entry, "it is longer than ${entry.size} bytes")
                    digest.update(buffer, 0, n)
                    out.write(buffer, 0, n)
                }
                out.fd.sync()
            }
        }
        if (total != entry.size) throw notListed(entry, "it is $total bytes, not ${entry.size}")
        val sha256 = digest.digest().joinToString("") { "%02x".format(it) }
        if (sha256 != entry.sha256) throw notListed(entry, "its bytes aren't the ones listed")
        Mirror.moveOver(tmp, to)
    } finally {
        tmp.delete()
    }
}

private fun notListed(entry: Entry, why: String) =
    LayerError("The file's page “${entry.path}” isn't as its list says ($why): export it again.")

private fun swap(layer: Layer, bytes: ByteArray) {
    val tmp = File(layer.dir, "${Mirror.TMP}${Mirror.token()}")
    try {
        tmp.outputStream().use { out ->
            out.write(bytes)
            out.fd.sync()
        }
        Mirror.moveOver(tmp, layer.manifestFile)
    } finally {
        tmp.delete()
    }
}

private fun removeTemporaries(layer: Layer) {
    layer.blobs.listFiles()?.forEach { if (it.name.startsWith(Mirror.TMP)) it.delete() }
    layer.dir.listFiles()?.forEach { if (it.name.startsWith(Mirror.TMP)) it.delete() }
}

/** A layer's list: [Manifest]'s format 1 as `GET /api/offline` writes it, with `taken`. */
private fun listJson(start: String, taken: Long, entries: List<Entry>): String = buildString {
    append("{\"format\": ").append(Manifest.FORMAT).append(", \"start\": ").append(quote(start))
    append(", \"taken\": ").append(taken).append(", \"files\": [")
    entries.forEachIndexed { i, e ->
        if (i > 0) append(",\n")
        append("{\"path\": ").append(quote(e.path)).append(", \"url\": ").append(quote(e.url))
        append(", \"size\": ").append(e.size).append(", \"sha256\": ").append(quote(e.sha256))
        append(", \"type\": ").append(quote(e.type)).append(", \"headers\": {")
        e.headers.entries.forEachIndexed { j, (name, value) ->
            if (j > 0) append(", ")
            append(quote(name)).append(": ").append(quote(value))
        }
        append('}')
        e.unit?.let { append(", \"unit\": ").append(quote(it)) }
        e.digest?.let { append(", \"digest\": ").append(quote(it)) }
        append('}')
    }
    append("]}")
}

/** [text] as a JSON string: a quote, a backslash, a control character and half of a surrogate pair escaped, so that
 * the list reads back as it was written. */
private fun quote(text: String): String = buildString {
    append('"')
    for (c in text) when {
        c == '"' -> append("\\\"")
        c == '\\' -> append("\\\\")
        c < ' ' || c == '\u007f' || c.isSurrogate() -> append("\\u%04x".format(c.code))
        else -> append(c)
    }
    append('"')
}
