package io.github.danielhp95.caracole.server.routes.sync

import io.github.danielhp95.caracole.core.sync.file.PageSource
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.mirror.Entry
import io.github.danielhp95.caracole.mirror.Mirror
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.security.MessageDigest

/**
 * The pages the phone's export holds with its library (the sync redesign's Task 33: core.sync.file's [PageSource] over
 * the mirror): the computer's pages in the mirror and those its layers took from files, as `GET /api/offline`'s list.
 *
 * [manifest] of the units the file holds (by id, their digests as the phone holds them now) lists, for each path, the
 * first entry of those units at that digest, the computer's before its layers', the newest layer first: a page the
 * phone took from a file goes on in its export once the computer's is another. A page whose blob is gone is listed by
 * none. Its start page is [start] where given (the phone's own library page's data, [startPage]: its every card, a song
 * taken from a file's too, so that a phone the file goes on to opens that song's sheet as this one does), else the
 * computer's library page, else the newest layer's. [open] reads a page's bytes by its SHA-256, wherever the mirror
 * holds them. The export checks each against its list as it reads it.
 */
class MirrorPages(private val mirror: Mirror?, private val start: ByteArray? = null) : PageSource {
    private val startSha = start?.let(::sha256)

    /** The list (`{"format": 1, "start", "files": [...]}`) of [units]' pages and the start page; null with no start
     * page (a phone that never synced, nor took a file's pages, nor gives its own). */
    override fun manifest(units: Map<String, String>): JsonObject? {
        val sides = mirror?.let { mirror ->
            listOfNotNull(mirror.manifest()?.let { it to mirror.blobs }) +
                mirror.layers().mapNotNull { layer -> layer.manifest()?.let { it to layer.blobs } }
        }.orEmpty()
        val first = start?.let { Entry(START, "/$START", it.size.toLong(), startSha!!, PAGE, HEADERS) }
            ?: sides.firstNotNullOfOrNull { (list, blobs) -> list.byPath[list.start]?.takeIf { File(blobs, it.sha256).isFile } }
            ?: return null
        val files = LinkedHashMap<String, Entry>()
        files[first.path] = first
        for ((list, blobs) in sides) {
            for (entry in list.entries) {
                val unit = entry.unit ?: continue
                if (entry.path in files || units[unit] != entry.digest || !File(blobs, entry.sha256).isFile) continue
                files[entry.path] = entry
            }
        }
        return JsonObject(linkedMapOf(
            "format" to JsonPrimitive(1),
            "start" to JsonPrimitive(first.path),
            "files" to JsonArray(files.values.map { entryJson(it) }),
        ))
    }

    /** A page's bytes by its SHA-256: [start]'s, the computer's blob or a layer's; null when the mirror holds none. */
    override fun open(sha256: String): InputStream? {
        if (!SHA256.matches(sha256)) return null
        if (sha256 == startSha) return ByteArrayInputStream(start)
        val mirror = mirror ?: return null
        val file = (listOf(mirror.blob(sha256)) + mirror.layers().map { it.blob(sha256) }).firstOrNull { it.isFile } ?: return null
        return try {
            FileInputStream(file)
        } catch (e: java.io.IOException) {
            null
        }
    }

    companion object {
        private val SHA256 = Regex("[0-9a-f]{64}")

        /** The start page's path, as the computer's list names its library page. */
        const val START = "index.html"
        private const val PAGE = "text/html; charset=utf-8"
        private val HEADERS = mapOf("Referrer-Policy" to "same-origin", "X-Content-Type-Options" to "nosniff")

        /** The phone's library page as an export's start page: [data], the page's data (PageData.data), in its block
         * (`<script type="application/json" id="songs">`, every `<` escaped, Inline.jsonBlock), which a phone that
         * takes the file reads its songs' cards from; no script, nothing to load. */
        fun startPage(data: JsonObject): ByteArray =
            ("<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>caracole</title></head><body>\n" +
                Inline.jsonBlock("songs", data) + "</body></html>\n").toByteArray(Charsets.UTF_8)

        /** An entry as offline_routes._entry writes it, its unit and digest after it where it names them. */
        fun entryJson(e: Entry): JsonObject = JsonObject(LinkedHashMap<String, JsonElement>().apply {
            put("path", JsonPrimitive(e.path))
            put("url", JsonPrimitive(e.url))
            put("size", JsonPrimitive(e.size))
            put("sha256", JsonPrimitive(e.sha256))
            put("type", JsonPrimitive(e.type))
            put("headers", JsonObject(e.headers.mapValues { JsonPrimitive(it.value) }))
            e.unit?.let { put("unit", JsonPrimitive(it)) }
            e.digest?.let { put("digest", JsonPrimitive(it)) }
        })

        private fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
