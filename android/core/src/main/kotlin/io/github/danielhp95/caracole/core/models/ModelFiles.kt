package io.github.danielhp95.caracole.core.models

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.LinkOption
import java.security.MessageDigest

/** Where a pinned file comes from. */
sealed interface From {
    /** The app's own: the debug build's `:ml` resource `caracole/autochords/<name>` (BTC's graph), no request. */
    data object App : From

    /** An asset of this repository's GitHub release [Pins.release], named [asset] (beat_this's converted file). */
    data class Release(val asset: String) : From

    /** The git blob [blob] of [repository] (its [path] at [commit]), read through GitHub's API: BTC's authors' file,
     * never re-hosted. */
    data class Blob(val repository: String, val commit: String, val path: String, val blob: String) : From
}

/** One file the chords are worked out with: its [name] in the models' folder, its exact [bytes] and [sha256]. */
data class Pin(val name: String, val bytes: Long, val sha256: String, val from: From)

/** models.json's pins: the [contract], the GitHub release's tag ([release]) and the [files] the hearing reads. */
data class Pins(val contract: Int, val release: String, val files: List<Pin>) {
    /** The folder the files are installed in, `stateDir/models/c<contract>` (MlChordModels' `models`). */
    fun folder(stateDir: File): File = File(File(stateDir, ModelFiles.FOLDER), "c$contract")

    /** The bytes of every file: what the Settings row says a download is. */
    val bytes: Long get() = files.sumOf { it.bytes }
}

/**
 * The chord models' files on the phone (the design's §6): data/caracole/autochords/models.json read as [Pins]
 * ([read]: BTC's graph from the app, BTC's authors' `.pt` beside it, as the graph's external data names it, and
 * beat_this's float16 graph), and whether a folder holds them ([installed], cheap; [verify], every byte hashed).
 *
 * A folder is installed whole or not at all: [ModelsSource.fetch] writes it beside its place under a name of its
 * own, every file checked by its SHA-256 and fsynced, its [MANIFEST] last (the pins of each file and its time on the
 * disk), then renames it into place. So [installed] reads the manifest and stats each file (its size and its time),
 * with no hash: a folder half written is never in place, and a file changed since its check has another time; the
 * whole re-hash, [verify], is for a caller that asks (a stat can't tell bytes changed in place with the time put
 * back).
 */
object ModelFiles {
    /** The pins on the classpath: the debug build's `:ml` puts them there (`:core` ships none, as the graph). */
    const val RESOURCE = "caracole/autochords/models.json"

    /** The models' folders' parent in the state directory. */
    const val FOLDER = "models"

    /** Written last into an installed folder: each file's pin and its time on the disk. */
    const val MANIFEST = "manifest.json"

    /** A folder being written, or one put aside as its new one takes its place: `.c1-<16 hex>.part`, `.old`. */
    internal const val PART = ".part"
    internal const val OLD = ".old"

    private const val MANIFEST_MOST = 64 * 1024

    /** models.json's pins, from the classpath; an IllegalStateException in a build that carries none. */
    fun read(): Pins {
        val text = resource(RESOURCE)?.use { it.readBytes() }
            ?: throw IllegalStateException("this build carries no chord models (no $RESOURCE)")
        return read(text)
    }

    /** [text], models.json's bytes, as [Pins]: BTC's graph, BTC's weights and beat_this's float16 graph. */
    fun read(text: ByteArray): Pins {
        val doc = PyJson.loads(text).jsonObject
        val btc = doc.getValue("btc").jsonObject
        val graph = btc.getValue("graph").jsonObject
        val weights = btc.getValue("weights").jsonObject
        val beats = doc.getValue("beats").jsonObject.getValue("fp16").jsonObject
        fun pin(o: JsonObject, from: From) =
            Pin(o.str("name"), o.getValue("bytes").jsonPrimitive.long, o.str("sha256"), from)
        return Pins(
            contract = doc.getValue("contract").jsonPrimitive.long.toInt(),
            release = doc.str("release"),
            files = listOf(
                pin(graph, From.App),
                pin(weights, From.Blob(weights.str("repository"), weights.str("commit"), weights.str("path"),
                                       weights.str("git_blob"))),
                pin(beats, From.Release(beats.str("asset"))),
            ),
        )
    }

    /** The classpath's [name], or null. */
    internal fun resource(name: String): InputStream? = ModelFiles::class.java.classLoader?.getResourceAsStream(name)

    /**
     * Null when [dir] holds every one of [pins]' files whole, as its [MANIFEST] says it was checked (each file a
     * regular file there of its pinned size and of the time the manifest gives it, the manifest's pins [pins]'
     * own); else why not, in words.
     */
    fun installed(dir: File, pins: Pins = read()): String? {
        if (!dir.isDirectory) return NOT_HERE
        val manifest = File(dir, MANIFEST)
        val entries = manifest(manifest) ?: return NOT_WHOLE
        if (entries.contract != pins.contract || entries.files.map { it.pin } != pins.files.map(::bare)) {
            return OTHER
        }
        for (entry in entries.files) {
            val file = File(dir, entry.pin.name)
            if (!regular(file)) return "$NOT_WHOLE_YET no ${entry.pin.name}."
            if (file.length() != entry.pin.bytes || file.lastModified() != entry.modified) {
                return "${entry.pin.name} on the phone has changed since it was downloaded."
            }
        }
        return null
    }

    /** [installed], then every file hashed whole against its pin: null, or why not. */
    fun verify(dir: File, pins: Pins = read()): String? {
        installed(dir, pins)?.let { return it }
        for (pin in pins.files) {
            if (sha256(File(dir, pin.name)) != pin.sha256) return "${pin.name} on the phone ${differs()}"
        }
        return null
    }

    /** What a [ModelsSource.fetch] cut off (the process killed) left beside [into]: its folder being written, or the
     * folder it had put aside. Deleted; their names, as they were. */
    fun sweep(into: File): List<String> {
        val parent = into.absoluteFile.parentFile ?: return emptyList()
        val left = parent.listFiles().orEmpty().filter { aside(into, it.name) }.sortedBy { it.name }
        for (file in left) file.deleteRecursively()
        return left.map { it.name }
    }

    /** Whether [name] is one of [into]'s folders being written or put aside: `.<into>-<16 hex>.part` or `.old`. */
    internal fun aside(into: File, name: String): Boolean {
        val start = "." + into.name + "-"
        val end = when {
            name.endsWith(PART) -> PART
            name.endsWith(OLD) -> OLD
            else -> return false
        }
        if (!name.startsWith(start) || name.length != start.length + 16 + end.length) return false
        return name.substring(start.length, start.length + 16).all { it in '0'..'9' || it in 'a'..'f' }
    }

    /** [dir]'s manifest written, of [pins]' files as they are there now, fsynced. */
    internal fun writeManifest(dir: File, pins: Pins) {
        val files = pins.files.map { pin ->
            JsonObject(linkedMapOf(
                "name" to JsonPrimitive(pin.name), "bytes" to JsonPrimitive(pin.bytes),
                "sha256" to JsonPrimitive(pin.sha256), "modified" to JsonPrimitive(File(dir, pin.name).lastModified()),
            ))
        }
        val doc = JsonObject(linkedMapOf("contract" to JsonPrimitive(pins.contract), "files" to JsonArray(files)))
        java.io.FileOutputStream(File(dir, MANIFEST)).use { out ->
            out.write((doc.toString() + "\n").toByteArray(Charsets.UTF_8))
            out.fd.sync()
        }
    }

    /** [file]'s SHA-256, read a MiB at a time (never the file in the heap), in lower-case hex. */
    fun sha256(file: File): String = file.inputStream().use { sha256(it) }

    internal fun sha256(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(1 shl 20)
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            digest.update(buffer, 0, n)
        }
        return hex(digest.digest())
    }

    internal fun hex(bytes: ByteArray): String {
        val digits = "0123456789abcdef"
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) out.append(digits[(b.toInt() shr 4) and 0xf]).append(digits[b.toInt() and 0xf])
        return out.toString()
    }

    /** [file] a regular file, not through a link. */
    internal fun regular(file: File): Boolean = Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)

    internal fun differs() = "isn't the file caracole's chords are made with (its SHA-256 differs)."

    const val NOT_HERE = "The chord models aren't on the phone."
    const val NOT_WHOLE = "The chord models on the phone aren't whole."
    private const val NOT_WHOLE_YET = "The chord models on the phone aren't whole:"
    const val OTHER = "The chord models on the phone are another caracole's."

    // --- the manifest -----------------------------------------------------------------------------------------------

    private class Entry(val pin: Pin, val modified: Long)

    private class Manifest(val contract: Int, val files: List<Entry>)

    /** A pin as the manifest keeps it: where it came from is the pins', not the folder's. */
    private fun bare(pin: Pin) = pin.copy(from = From.App)

    private fun manifest(file: File): Manifest? = try {
        if (!regular(file) || file.length() > MANIFEST_MOST) null else {
            val doc = PyJson.loads(file.readBytes()) as? JsonObject
            val contract = (doc?.get("contract") as? JsonPrimitive)?.contentOrNull?.toIntOrNull()
            val files = (doc?.get("files") as? JsonArray)?.map { item ->
                val o = item as? JsonObject ?: throw IllegalArgumentException("an entry that isn't an object")
                fun long(key: String) = number(o[key]) ?: throw IllegalArgumentException("no number $key")
                Entry(Pin(o.str("name"), long("bytes"), o.str("sha256"), From.App), long("modified"))
            }
            if (contract == null || files == null) null else Manifest(contract, files)
        }
    } catch (e: IOException) {
        null
    } catch (e: IllegalArgumentException) {
        null  // not JSON, or not the manifest's shape
    }

    private fun number(value: JsonElement?): Long? =
        (value as? JsonPrimitive)?.takeIf { !it.isString && value !is JsonNull }?.contentOrNull?.toLongOrNull()

    private fun JsonObject.str(key: String): String {
        val value = get(key) as? JsonPrimitive
        require(value != null && value.isString) { "no text $key" }
        return value.content
    }
}
