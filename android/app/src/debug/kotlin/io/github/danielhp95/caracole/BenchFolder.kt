package io.github.danielhp95.caracole

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import io.github.danielhp95.caracole.ml.OrtModels
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import org.json.JSONObject

/**
 * The folder the owner picks for the Chords bench (`ACTION_OPEN_DOCUMENT_TREE`, its grant kept), read and written
 * through the Storage Access Framework alone: the model files and the references in it, and the report written
 * there. Its files are named by their display names; the report names none but the references'.
 */
internal class BenchFolder(private val resolver: ContentResolver, private val tree: Uri) {
    class Entry(val name: String, val uri: Uri, val size: Long)

    private val folder: Uri =
        DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))

    /** Its files (no folders), by name. */
    fun entries(): List<Entry> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getDocumentId(folder))
        val columns = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE)
        val out = mutableListOf<Entry>()
        resolver.query(children, columns, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                if (c.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR) continue
                out += Entry(c.getString(1), DocumentsContract.buildDocumentUriUsingTree(tree, c.getString(0)),
                    if (c.isNull(3)) -1 else c.getLong(3))
            }
        }
        return out.sortedBy { it.name }
    }

    fun open(entry: Entry): InputStream =
        resolver.openInputStream(entry.uri) ?: throw IllegalStateException("${entry.name} won't open")

    /** A new file there, [name] as its display name (a provider may add " (1)" to a name taken). */
    fun create(name: String, mime: String): Uri =
        DocumentsContract.createDocument(resolver, folder, mime, name)
            ?: throw IllegalStateException("the folder won't take a new file")

    /** [bytes] as the whole of [uri], written over what it held. */
    fun write(uri: Uri, bytes: ByteArray) {
        (resolver.openOutputStream(uri, "wt") ?: throw IllegalStateException("the report won't open")).use {
            it.write(bytes)
        }
    }
}

/**
 * The model files the bench runs, in the app's own `no_backup/bench-models/`, where ONNX Runtime reads them by path
 * (BTC's graph reads its weights at their offsets in the file beside it): BTC's graph from `:ml`'s classpath (the
 * debug build's own), the weights and beat_this's files copied from the owner's folder, each checked by its SHA-256
 * against models.json's pins before it is used, a copy that already holds the pinned bytes kept.
 */
internal object BenchModels {
    private const val PINS = "caracole/autochords/models.json"

    fun pins(): JSONObject = JSONObject(resource(PINS).bufferedReader(Charsets.UTF_8).use { it.readText() })

    /** The folder of the files [names] (OrtModels' file names), each pinned and checked; a name the owner's folder
     * lacks, or holds with other bytes, is left out and said. */
    fun prepare(context: Context, folder: BenchFolder, names: Set<String>,
                say: (String) -> Unit): Pair<File, Set<String>> {
        val dir = File(context.noBackupFilesDir, "bench-models").apply { mkdirs() }
        val pins = pins()
        val pinned = mapOf(
            OrtModels.BTC_GRAPH to pins.getJSONObject("btc").getJSONObject("graph"),
            OrtModels.BTC_WEIGHTS to pins.getJSONObject("btc").getJSONObject("weights"),
            OrtModels.BEATS_FP32 to pins.getJSONObject("beats").getJSONObject("fp32"),
            OrtModels.BEATS_FP16 to pins.getJSONObject("beats").getJSONObject("fp16"),
        )
        val there = folder.entries().associateBy { it.name }
        val ready = mutableSetOf<String>()
        for (name in names) {
            val pin = pinned.getValue(name)
            val file = File(dir, name)
            if (file.length() == pin.getLong("bytes") && sha256(file.inputStream()) == pin.getString("sha256")) {
                ready += name
                continue
            }
            val source: () -> InputStream = if (name == OrtModels.BTC_GRAPH) {
                { resource("caracole/autochords/$name") }
            } else {
                val entry = there[name]
                if (entry == null) {
                    say("no $name in the folder: its runs are left out")
                    continue
                }
                { folder.open(entry) }
            }
            say("copying $name (${pin.getLong("bytes") / 1_000_000} MB)…")
            val part = File(dir, "$name.part")
            source().use { input -> part.outputStream().use { input.copyTo(it, 1 shl 20) } }
            if (sha256(part.inputStream()) != pin.getString("sha256")) {
                part.delete()
                say("$name in the folder isn't the pinned file (models.json's SHA-256): its runs are left out")
                continue
            }
            check(part.renameTo(file)) { "can't keep $name" }
            ready += name
        }
        return dir to ready
    }

    private fun resource(name: String): InputStream =
        OrtModels::class.java.classLoader!!.getResourceAsStream(name) ?: throw IllegalStateException("no $name")

    private fun sha256(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        input.use {
            val chunk = ByteArray(1 shl 20)
            while (true) {
                val n = it.read(chunk)
                if (n < 0) break
                digest.update(chunk, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
