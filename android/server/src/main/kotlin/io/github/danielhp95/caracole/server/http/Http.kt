package io.github.danielhp95.caracole.server.http

import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.FileInputStream
import java.io.InputStream

// web/app.py's shapes on the phone (lane server-shell).

/** A request as it came: the raw target as sent, headers by lowercase name, the body read up to the route's limit. */
data class Request(val method: String, val target: String, val headers: Map<String, String>, val body: ByteArray)

/** An answer's body: none, bytes, or a file streamed. */
sealed interface Body {
    data object Empty : Body
    class Bytes(val bytes: ByteArray) : Body

    /** [file]'s [length] bytes, streamed from [open]; [once], a file sent once (an export,
     * web/sync_file_routes.py's): its name deleted as it is opened, the bytes read through the stream opened. */
    class FromFile(val file: File, val length: Long, val once: Boolean = false) : Body {
        /** The file opened to be sent, its name then deleted when it is sent [once]. */
        fun open(): InputStream {
            val stream = FileInputStream(file)
            if (once) file.delete()
            return stream
        }
    }
}

/** An answer. [data], a script's JSON, is what a 303 answers to a page's fetch instead (web/app.py's). */
class Response(
    var status: Int,
    var body: Body = Body.Empty,
    val headers: MutableList<Pair<String, String>> = mutableListOf(),
    var data: JsonObject? = null,
)

/** A route's refusal, which App answers as the message page, or as JSON to the page's script. */
class Refused(val status: Int, val title: String, message: String, val reload: Boolean = false) : Exception(message)

fun interface GetAnswer {
    fun answer(request: Request): Response
}

fun interface PostAnswer {
    fun answer(request: Request, form: Map<String, String>): Response
}

/** A `json` or a `bytes` route's answer (web/app.py's `Route.body`): [document], its body read as JSON (PyJson.loads,
 * a JsonElement), or its bytes (a ByteArray). */
fun interface DocumentAnswer {
    fun answer(request: Request, document: Any): Response
}

/** One route: a method and a path ([under]: every path below it), what it is ([doc]), whether only the page's script
 * reads it ([scriptOnly]: the token header), the page its refusals name, its body's limit in bytes, and its answer: a
 * POST's [body] a form ([post]), or, a page's script's alone, a JSON document or bytes ([document]), each with the
 * form token in its header (web/app.py's `BODIES`). */
data class Route(
    val method: String, val path: String, val doc: String, val under: Boolean = false, val scriptOnly: Boolean = false,
    val page: String = "the library", val limit: Int = 16_384, val get: GetAnswer? = null, val post: PostAnswer? = null,
    val body: String = FORM, val document: DocumentAnswer? = null,
) {
    companion object {
        /** A POST's kinds of body (web/app.py's BODIES), each read as its content type says (BODY_TYPES). */
        const val FORM = "form"
        const val JSON = "json"
        const val BYTES = "bytes"
        val BODY_TYPES = mapOf(FORM to "application/x-www-form-urlencoded", JSON to "application/json",
                               BYTES to "application/octet-stream")
    }
}

/** An area's routes, as each of web/'s *_routes.py modules gives its ROUTES. */
interface RouteModule {
    val routes: List<Route>
}
