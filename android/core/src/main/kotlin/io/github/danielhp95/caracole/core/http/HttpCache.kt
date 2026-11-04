package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

/**
 * One provider's part of caracole's HTTP cache, laid out as http.py lays it out ([root] is `cacheDir/http/<provider>`):
 * an answer under the SHA-256 of its URL's UTF-8, `<2 hex>/<sha>.body` (its body, gzip'd) and `<sha>.json` (its URL,
 * status, kept headers and `fetched_at`, as `json.dumps(meta, ensure_ascii=False)` writes them), each replaced whole:
 * a temporary file beside it, then a rename. A copy that can't be read is none.
 */
internal class HttpCache(val root: File) {
    fun key(url: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(url.toByteArray(Charsets.UTF_8))
        return buildString { for (b in digest) append(HEX[(b.toInt() shr 4) and 15]).append(HEX[b.toInt() and 15]) }
    }

    private fun paths(key: String): Pair<File, File> {
        val dir = File(root, key.substring(0, 2))
        return File(dir, "$key.body") to File(dir, "$key.json")
    }

    /** The answer cached under [key], however old, or null. */
    fun read(key: String): Response? {
        val (body, meta) = paths(key)
        return try {
            val m = Json.parseToJsonElement(meta.readText(Charsets.UTF_8)).jsonObject
            val content = gunzip(body.readBytes())
            val headers = (m["headers"] as? JsonObject ?: JsonObject(emptyMap()))
                .mapValuesTo(LinkedHashMap()) { it.value.jsonPrimitive.content }
            val fetchedAt = m["fetched_at"]?.let { if (it is JsonNull) null else it.jsonPrimitive.content }
            Response(m.getValue("url").jsonPrimitive.content, m.getValue("status").jsonPrimitive.int, content, headers,
                     fromCache = true, fetchedAt = fetchedAt)
        } catch (e: Exception) {
            null
        }
    }

    /** http.py's `cached_answer`: the copy of [url] when its status is in [accept]. */
    fun answer(url: String, accept: Set<Int>): Response? = read(key(url))?.takeIf { it.status in accept }

    /** Whether a copy of [url] with a status in [accept] is kept: its meta says so and its body is there. */
    fun has(url: String, accept: Set<Int>): Boolean {
        val (body, meta) = paths(key(url))
        return try {
            Json.parseToJsonElement(meta.readText(Charsets.UTF_8)).jsonObject.getValue("status").jsonPrimitive.int in
                accept && body.isFile
        } catch (e: Exception) {
            false
        }
    }

    fun write(key: String, url: String, status: Int, headers: Map<String, String>, body: ByteArray, stamp: String) {
        val (bodyFile, _) = paths(key)
        bodyFile.parentFile.mkdirs()
        replace(bodyFile, gzip(body))
        writeMeta(key, url, status, headers, stamp)
    }

    fun writeMeta(key: String, url: String, status: Int, headers: Map<String, String>, stamp: String) {
        val (_, meta) = paths(key)
        meta.parentFile.mkdirs()
        val doc = JsonObject(linkedMapOf(
            "url" to JsonPrimitive(url), "status" to JsonPrimitive(status),
            "headers" to JsonObject(headers.mapValuesTo(LinkedHashMap()) { JsonPrimitive(it.value) }),
            "fetched_at" to JsonPrimitive(stamp),
        ))
        replace(meta, PyJson.dumps(doc).toByteArray(Charsets.UTF_8))
    }

    companion object {
        private const val HEX = "0123456789abcdef"

        fun gzip(data: ByteArray): ByteArray {
            val out = ByteArrayOutputStream()
            GZIPOutputStream(out).use { it.write(data) }
            return out.toByteArray()
        }

        fun gunzip(data: ByteArray): ByteArray = GZIPInputStream(data.inputStream()).use { it.readBytes() }

        /** `_replace`: [path] written whole, a temporary file beside it renamed over it. */
        fun replace(path: File, data: ByteArray) {
            val tmp = File(path.parentFile, path.name + ".tmp")
            tmp.writeBytes(data)
            if (!tmp.renameTo(path)) throw IOException("could not replace $path")
        }
    }
}
