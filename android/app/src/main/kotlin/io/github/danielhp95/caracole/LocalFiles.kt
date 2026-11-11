package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.mirror.Links
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Security
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.io.ByteArrayInputStream
import java.io.FileInputStream
import java.io.InputStream
import java.net.URI

/** What the phone's server answered for a file another app is to open. */
sealed interface Fetched {
    /** The file: its [type] (without parameters, "application/pdf"), its [length], the server's Content-Disposition
     * ([disposition], null for none: an export's names the file) and its bytes, read by [open]. */
    class File(val type: String, val length: Long, val disposition: String? = null,
               private val bytes: () -> InputStream) : Fetched {
        fun open(): InputStream = bytes()
    }

    /** No file: the answer's [status], and the server's words for it when it gave some. */
    data class Refused(val status: Int, val message: String?) : Fetched
}

/**
 * A file of the phone's server (`App.handle`, [handle]) read in the app's own process, for another app: asked as the
 * WebView would ask for it, with the launch's cookie ([secret]) and the server's host ([origin]), never through
 * Android's DownloadManager, which carries no cookie, nor over the socket.
 */
class LocalFiles(private val handle: (Request) -> Response, origin: URI, private val secret: String) {
    private val host = origin.rawAuthority

    /** The file at [path] in the library ("Estopa/Tu calorro/sheet.pdf"). */
    fun get(path: String): Fetched = at(Links.target(path))

    /** The file the server answers at [target], a path and query as sent ("/api/sync/export?export=…": an export of
     * the sync sheet's, Exports'). */
    fun at(target: String): Fetched {
        val response = handle(Request("GET", target, mapOf(
            "host" to host,
            "cookie" to "${Security.SECRET_COOKIE}=$secret",
            "sec-fetch-site" to "same-origin",
            "accept" to "application/json",
        ), ByteArray(0)))
        val type = response.headers.lastOrNull { it.first.equals("Content-Type", ignoreCase = true) }?.second
            ?.substringBefore(';')?.trim()?.lowercase()?.ifEmpty { null } ?: ANY_FILE
        if (response.status != 200 || type in PAGES) return Fetched.Refused(response.status, said(response, type))
        val disposition = response.headers.lastOrNull { it.first.equals("Content-Disposition", ignoreCase = true) }?.second
        return when (val body = response.body) {
            Body.Empty -> Fetched.File(type, 0, disposition) { ByteArrayInputStream(ByteArray(0)) }
            is Body.Bytes -> Fetched.File(type, body.bytes.size.toLong(), disposition) { ByteArrayInputStream(body.bytes) }
            is Body.FromFile -> Fetched.File(type, body.length, disposition) { FileInputStream(body.file) }
        }
    }

    /** The refusal's words: its data's `error`, or the JSON it answered a script with. */
    private fun said(response: Response, type: String): String? {
        val data = response.data ?: (response.body as? Body.Bytes)?.takeIf { type == JSON }?.let {
            try {
                Json.parseToJsonElement(it.bytes.toString(Charsets.UTF_8)) as? JsonObject
            } catch (e: IllegalArgumentException) {
                null
            }
        }
        return (data?.get("error") as? JsonPrimitive)?.contentOrNull
    }

    private companion object {
        const val ANY_FILE = "application/octet-stream"
        const val JSON = "application/json"
        val PAGES = setOf("text/html", "application/xhtml+xml")
    }
}
