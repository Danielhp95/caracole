package io.github.danielhp95.caracole.mirror

import java.net.URI
import java.net.URISyntaxException
import java.net.URLDecoder

/** Where a link the WebView is asked to follow goes. */
sealed interface Route {
    /** At the phone's server: the WebView loads it, and the server answers (a page, its message, or a 404). */
    data object Page : Route

    /**
     * A file of the library that isn't a page (a PDF, a Guitar Pro file, a .cho), by its [path] there
     * ("Estopa/Tu calorro/sheet.pdf"): the app reads it from its server and another app opens it.
     */
    data class File(val path: String) : Route

    /** Any other address on the web (Ultimate Guitar, caracole serve on the computer…): the phone's browser opens it. */
    data class Browser(val url: String) : Route

    /**
     * The viewer's Export PDF, caracole serve's `/export.pdf?…` at the phone's server, by its whole [url]: the app
     * prints the viewer shown (Android's print framework; the server names the version and its file), never a file
     * downloaded.
     */
    data class Print(val url: String) : Route

    /** Anything else (another scheme, no address): nothing opens it. */
    data object Ignored : Route
}

/**
 * The phone's server's addresses in the WebView, at [origin] (`http://127.0.0.1:8738`): a page's path there is its path
 * on caracole serve, and every other link goes elsewhere ([route]).
 *
 * The launch's cookie is the server's alone, and a cookie ignores the port: so the WebView loads that exact origin
 * (scheme, host and port) and nothing else ([loads]), and a link to any other origin, another port of 127.0.0.1
 * (a Termux caracole serve's 8737) included, opens in the browser, which has no such cookie.
 *
 * [isFile] says whether a path of the library ("Estopa/Tu calorro/sheet.pdf") is a file another app opens rather than a
 * page: a link to one is [Route.File]. The Guitar Pro page, `/guitar?file=<its path>`, which the library page and a
 * served viewer link each Guitar Pro file to, is a page the phone serves (its GuitarRoutes, alphaTab from the APK);
 * a download of it, the file. Its Export PDF, `/export.pdf?<the version>`, is printed ([Route.Print]), a navigation
 * or a download alike.
 */
class Links(origin: URI, private val isFile: (String) -> Boolean) {
    private val scheme = origin.scheme.lowercase()
    private val host = origin.host.lowercase()
    private val port = portOf(origin)
    private val base = "$scheme://${origin.rawAuthority}"

    /** Where [url] goes; with [download] (the WebView's download listener), a file of the server's whatever its path. */
    fun route(url: String, download: Boolean = false): Route {
        val uri = parse(url) ?: return Route.Ignored
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return Route.Ignored
        if (!own(uri)) return Route.Browser(url)
        val path = (uri.path ?: "").removePrefix("/")
        if (path == EXPORT) return Route.Print(url)
        if (path == GUITAR_PAGE && download) query(uri.rawQuery)["file"]?.let { return Route.File(it) }
        return when {
            download -> if (path.isEmpty()) Route.Ignored else Route.File(path)
            path.isNotEmpty() && isFile(path) -> Route.File(path)
            else -> Route.Page
        }
    }

    /**
     * Whether the WebView may fetch [url] itself: an address of the server's exact origin, or a `data:` URL, the page's
     * own bytes; anything else is answered 404 in the app and reaches no socket.
     */
    fun loads(url: String): Boolean {
        // A data: URL may hold what no URI parses (an SVG's own <, a space): its scheme alone says what it is.
        if (url.regionMatches(0, "data:", 0, 5, ignoreCase = true)) return true
        val uri = parse(url) ?: return false
        val scheme = uri.scheme?.lowercase()
        return (scheme == "http" || scheme == "https") && own(uri)
    }

    /** The address of [path] on the server, for the WebView: each part percent-encoded. */
    fun address(path: String): String = base + target(path)

    private fun own(uri: URI): Boolean =
        uri.scheme.lowercase() == scheme && uri.rawUserInfo == null && uri.host?.lowercase() == host && portOf(uri) == port

    private fun portOf(uri: URI): Int = if (uri.port != -1) uri.port else if (uri.scheme.lowercase() == "https") 443 else 80

    private fun parse(url: String): URI? = try {
        URI(url)
    } catch (e: URISyntaxException) {
        null
    }

    private fun query(raw: String?): Map<String, String> = raw.orEmpty().split('&')
        .filter { '=' in it }
        .associate { pair ->
            val (name, value) = pair.split('=', limit = 2)
            decode(name) to decode(value)
        }

    private fun decode(text: String) = try {
        URLDecoder.decode(text, "UTF-8")
    } catch (e: IllegalArgumentException) {
        ""
    }

    companion object {
        /** The Guitar Pro page, which the library page and a served viewer link each Guitar Pro file to. */
        private const val GUITAR_PAGE = "guitar"

        /** caracole serve's Export PDF, which a served viewer's settings link (viewer.js). */
        private const val EXPORT = "export.pdf"

        /** [path] of the library as a target on the server ("/Estopa/Tu%20calorro/sheet.pdf"): each part percent-encoded. */
        fun target(path: String): String = "/" + path.split('/').joinToString("/") { encodePart(it) }

        private fun encodePart(part: String): String {
            val out = StringBuilder()
            for (byte in part.toByteArray(Charsets.UTF_8)) {
                val c = byte.toInt() and 0xff
                if (c.toChar() in UNRESERVED) out.append(c.toChar()) else out.append("%%%02X".format(c))
            }
            return out.toString()
        }

        private val UNRESERVED: Set<Char> =
            (('A'..'Z') + ('a'..'z') + ('0'..'9') + listOf('-', '.', '_', '~')).toSet()
    }
}
