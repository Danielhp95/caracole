package io.github.danielhp95.caracole.server.routes.sync

import io.github.danielhp95.caracole.mirror.Entry
import io.github.danielhp95.caracole.mirror.Mirror
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.FileInputStream
import java.io.InputStream

/**
 * The pages the phone's export holds with its library (the sync redesign's Task 33: core.sync.file's `PageSource` over
 * the mirror): the computer's pages in the mirror and those its layers took from files, as `GET /api/offline`'s list.
 *
 * [manifest] of the units the file holds (by id, their digests as the phone holds them now) lists, for each path, the
 * first entry of those units at that digest, the computer's before its layers', the newest layer first: a page the
 * phone took from a file goes on in its export once the computer's is another; and the start page, the computer's
 * library page, else the newest layer's. A page whose blob is gone is listed by none. [open] reads a page's bytes by
 * its SHA-256, wherever the mirror holds them. The export checks each against its list as it reads it.
 */
class MirrorPages(private val mirror: Mirror?) {
    /** The list (`{"format": 1, "start", "files": [...]}`) of [units]' pages and the start page; null with no start
     * page (a phone that never synced, nor took a file's pages). */
    fun manifest(units: Map<String, String>): JsonObject? {
        val mirror = mirror ?: return null
        val sides = listOfNotNull(mirror.manifest()?.let { it to mirror.blobs }) +
            mirror.layers().mapNotNull { layer -> layer.manifest()?.let { it to layer.blobs } }
        val start = sides.firstNotNullOfOrNull { (list, blobs) ->
            list.byPath[list.start]?.takeIf { File(blobs, it.sha256).isFile }
        } ?: return null
        val files = LinkedHashMap<String, Entry>()
        files[start.path] = start
        for ((list, blobs) in sides) {
            for (entry in list.entries) {
                val unit = entry.unit ?: continue
                if (entry.path in files || units[unit] != entry.digest || !File(blobs, entry.sha256).isFile) continue
                files[entry.path] = entry
            }
        }
        return JsonObject(linkedMapOf(
            "format" to JsonPrimitive(1),
            "start" to JsonPrimitive(start.path),
            "files" to JsonArray(files.values.map { entryJson(it) }),
        ))
    }

    /** A page's bytes by its SHA-256, the computer's blob or a layer's; null when the mirror holds none. */
    fun open(sha256: String): InputStream? {
        val mirror = mirror ?: return null
        if (!SHA256.matches(sha256)) return null
        val file = (listOf(mirror.blob(sha256)) + mirror.layers().map { it.blob(sha256) }).firstOrNull { it.isFile } ?: return null
        return try {
            FileInputStream(file)
        } catch (e: java.io.IOException) {
            null
        }
    }

    companion object {
        private val SHA256 = Regex("[0-9a-f]{64}")

        /** An entry as offline_routes._entry writes it, its unit and digest after it where it names them. */
        fun entryJson(e: Entry): JsonObject = JsonObject(LinkedHashMap<String, kotlinx.serialization.json.JsonElement>().apply {
            put("path", JsonPrimitive(e.path))
            put("url", JsonPrimitive(e.url))
            put("size", JsonPrimitive(e.size))
            put("sha256", JsonPrimitive(e.sha256))
            put("type", JsonPrimitive(e.type))
            put("headers", JsonObject(e.headers.mapValues { JsonPrimitive(it.value) }))
            e.unit?.let { put("unit", JsonPrimitive(it)) }
            e.digest?.let { put("digest", JsonPrimitive(it)) }
        })
    }
}
