package io.github.danielhp95.caracole.mirror

import java.net.URI
import java.net.URISyntaxException
import java.net.URLDecoder

/** Where a link the WebView is asked to follow goes. */
sealed interface Route {
    /** A page of the mirror: the WebView loads it. */
    data object Page : Route

    /** A file of the mirror that isn't a page (a PDF, a Guitar Pro file, a .cho): another app opens it. */
    data class File(val served: Served) : Route

    /** An address on the web (Ultimate Guitar, MuseScore…): the phone's browser opens it. */
    data class Browser(val url: String) : Route

    /** One of caracole serve's own pages (Export, the versions' forms): the server's alone, not in the copy. */
    data object ServerOnly : Route

    /** A path of the mirror that it doesn't hold (a sync since changed the list). */
    data object Missing : Route

    /** Anything else (another scheme): nothing opens it. */
    data object Ignored : Route
}

/**
 * The mirror's addresses in the WebView, `https://appassets.androidplatform.net/<path>`: at the root of the
 * origin, so a page's path there is its path on caracole serve, and where every other link goes ([route]).
 *
 * A page that takes itself for served links caracole serve's own pages by their absolute paths:
 * `/guitar?file=<its path>` for a Guitar Pro file, which is in the mirror and opens as any other file;
 * `/export`, `/versions` and the like, which need the server ([Route.ServerOnly]).
 */
class Links(private val mirror: Mirror) {

    fun route(url: String): Route {
        val uri = try {
            URI(url)
        } catch (e: URISyntaxException) {
            return Route.Ignored
        }
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return Route.Ignored
        if (scheme != "https" || !HOST.equals(uri.host, ignoreCase = true)) return Route.Browser(url)
        val path = uri.path ?: return Route.Missing
        if (path == GUITAR_PAGE) {
            val file = query(uri.rawQuery)["file"] ?: return Route.Missing
            return mirror.lookup(file)?.let { Route.File(it) } ?: Route.Missing
        }
        val served = mirror.lookup(path.removePrefix(PREFIX))
        return when {
            served == null -> if ('.' in path.substringAfterLast('/')) Route.Missing else Route.ServerOnly
            served.entry.isPage -> Route.Page
            else -> Route.File(served)
        }
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
        /** The WebView's origin for the mirror: androidx.webkit's WebViewAssetLoader's own domain. */
        const val HOST = "appassets.androidplatform.net"

        /** The path the mirror is under: the root, as on caracole serve. */
        const val PREFIX = "/"

        /** caracole serve's Guitar Pro page, which a served viewer links each Guitar Pro file to. */
        private const val GUITAR_PAGE = "/guitar"

        /** The address of [path] in the mirror, for the WebView: each part percent-encoded. */
        fun address(path: String): String =
            "https://$HOST$PREFIX" + path.split('/').joinToString("/") { encodePart(it) }

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
