package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Units
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException

/** The push the phone sends the computer (the plan's §5.3, peer_push.read_push_document's document). */
internal object Give {
    /** A unit the computer takes: its digest there as compared ([expected]), the phone's now ([digest]) and its
     * document ([unit]), both null for a unit the phone hasn't got (the computer removes it). */
    class Entry(val id: String, val expected: String?, val digest: String?, val unit: JsonObject?)

    /** The SHA-256 of every file a song document of [entries] keeps, each once, in order. */
    fun files(entries: List<Entry>): List<String> {
        val found = LinkedHashSet<String>()
        for (entry in entries) {
            val unit = entry.unit ?: continue
            if (entry.id.substringBefore('/') != "song") continue
            for (version in unit["versions"] as? JsonArray ?: continue) {
                for (file in (version as? JsonObject)?.get("files") as? JsonArray ?: continue) {
                    Documents.text((file as? JsonObject)?.get("sha256"))?.let(found::add)
                }
            }
        }
        return found.toList()
    }

    /** The bytes of a file the phone keeps whose SHA-256 is [sha256], read from its library folder (a regular file
     * under it, never through a link), as peer_push.kept_copy reads one; null when none is as recorded any more. */
    fun read(database: Database, libraryDir: File, sha256: String): ByteArray? {
        val paths = database.read { db -> db.query("SELECT path FROM files WHERE sha256 = ? ORDER BY id", sha256) { it.text(0) } }
        val root = libraryDir.canonicalFile
        for (path in paths.filterNotNull()) {
            val file = File(root, path)
            val bytes = try {
                val real = file.canonicalFile
                if (!real.path.startsWith(root.path + File.separator) || real.path != file.absoluteFile.normalize().path ||
                    !real.isFile) continue
                real.readBytes()
            } catch (e: IOException) {
                continue
            }
            if (Canonical.sha256Hex(bytes) == sha256) return bytes
        }
        return null
    }

    /** The push document: who pushes, its state after its own take ([state]), and the units the computer takes. */
    fun document(from: String, name: String, caracole: String, at: String, state: Map<String, SyncUnit>,
                 entries: List<Entry>): JsonObject = JsonObject(linkedMapOf(
        "format" to JsonPrimitive(Units.FORMAT),
        "from" to JsonPrimitive(from),
        "name" to JsonPrimitive(name),
        "caracole" to JsonPrimitive(caracole),
        "at" to JsonPrimitive(at),
        "units" to JsonObject(state.values.associate { unit ->
            unit.id to JsonObject(linkedMapOf("label" to JsonPrimitive(unit.label), "digest" to JsonPrimitive(unit.digest)))
        }),
        "take" to JsonArray(entries.map { entry ->
            JsonObject(linkedMapOf(
                "id" to JsonPrimitive(entry.id),
                "expected" to text(entry.expected),
                "digest" to text(entry.digest),
                "unit" to (entry.unit ?: JsonNull),
            ))
        }),
    ))

    /** What the computer's request said of each unit as it took the push (Job.as_json's `units`: [id, outcome, why]
     * each, outcome "taken", "given" or "left"), by its id; its odd entries left out. */
    fun units(job: JsonObject): Map<String, Pair<String, String>> {
        val found = LinkedHashMap<String, Pair<String, String>>()
        for (entry in job["units"] as? JsonArray ?: return found) {
            val parts = entry as? JsonArray ?: continue
            val id = Documents.text(parts.getOrNull(0)) ?: continue
            val outcome = Documents.text(parts.getOrNull(1)) ?: continue
            found[id] = outcome to (Documents.text(parts.getOrNull(2)) ?: "")
        }
        return found
    }

    /** A text value, or null for anything else. */
    fun text(e: JsonElement?): String? = Documents.text(e)

    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
}
