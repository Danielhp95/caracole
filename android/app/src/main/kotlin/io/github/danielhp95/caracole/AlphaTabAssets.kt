package io.github.danielhp95.caracole

import android.content.Context
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.guitar.AlphaTabBundle
import java.io.ByteArrayInputStream
import java.io.IOException

/**
 * alphaTab's bundle as the APK's asset (app/alphatab.gradle.kts builds it from nix/alphatab.nix's files exactly as
 * web/alphatab.py does), answered at `/assets/alphatab/<name>` of the phone's server in the WebView's
 * shouldInterceptRequest before anything else: the Guitar Pro page is served in a sandbox, an origin of its own,
 * whose request for the bundle (`<script src integrity crossorigin>`) carries no launch cookie, so the server would
 * refuse it.
 *
 * The answer is guitar_routes.asset's: `text/javascript; charset=utf-8`, kept for good, to any origin
 * (`Access-Control-Allow-Origin: *`: the script is loaded in CORS mode with its integrity, from an opaque origin, and
 * without the header the load fails). Any other name there is 404, answered here too, so that nothing under the
 * address reaches the server; a request anywhere else is the server's (null).
 */
class AlphaTabAssets(private val context: Context) {
    /** The bundle's name, as the build recorded it (AlphaTabBundle.installed). */
    private val name: String? by lazy { AlphaTabBundle.installed()?.name }

    fun answer(request: WebResourceRequest): WebResourceResponse? {
        val url = request.url
        val answer = answerFor(request.method, url.scheme, url.host, url.encodedPath, name) ?: return null
        val body = answer.asset?.let { asset ->
            try {
                context.assets.open(asset)
            } catch (e: IOException) {
                return response(NOT_FOUND)
            }
        }
        return response(answer, body)
    }

    private fun response(answer: Answer, body: java.io.InputStream? = null): WebResourceResponse =
        WebResourceResponse(answer.mimeType, answer.encoding, answer.status, answer.reason, answer.headers,
                            body ?: ByteArrayInputStream(answer.text.toByteArray(Charsets.UTF_8)))

    /** What the WebView is answered: [asset], the APK's asset of the body, else [text]. */
    data class Answer(val status: Int, val reason: String, val mimeType: String, val encoding: String,
                      val headers: Map<String, String>, val asset: String? = null, val text: String = "")

    companion object {
        /** Where the bundle is among the APK's assets: `alphatab/<name>`, its licences in `alphatab/licenses/`. */
        const val FOLDER = "alphatab"

        /** guitar_routes.asset's headers, but the content type, which the WebView takes from the answer's own. */
        val HEADERS: Map<String, String> = linkedMapOf(
            "Access-Control-Allow-Origin" to "*",
            "Cross-Origin-Resource-Policy" to "cross-origin",
            "Cache-Control" to "public, max-age=31536000, immutable",
            "Content-Security-Policy" to "default-src 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options" to "nosniff",
        )

        val NOT_FOUND = Answer(404, "Not Found", "text/plain", "utf-8",
                               linkedMapOf("Content-Security-Policy" to "default-src 'none'; frame-ancestors 'none'",
                                           "X-Content-Type-Options" to "nosniff"),
                               text = "There's no such file of alphaTab's here.\n")

        /**
         * The answer to a request of [method] for [scheme]://[host][encodedPath]: the bundle for `GET
         * /assets/alphatab/<name>` of the phone's server (any port of 127.0.0.1, where it listens) when its path, once
         * unquoted, names the bundle [name]; [NOT_FOUND] for any other there; null for anything else.
         */
        fun answerFor(method: String?, scheme: String?, host: String?, encodedPath: String?, name: String?): Answer? {
            if (scheme?.lowercase() != "http" || host != HOST || encodedPath == null) return null
            val path = try {
                PyUrl.unquote(encodedPath, strict = true)
            } catch (e: PyUrl.Invalid) {
                return if (encodedPath.startsWith(AlphaTabBundle.ASSETS)) NOT_FOUND else null
            }
            if (!path.startsWith(AlphaTabBundle.ASSETS)) return null
            if (method != "GET" || name == null || path.substring(AlphaTabBundle.ASSETS.length) != name) return NOT_FOUND
            return Answer(200, "OK", "text/javascript", "utf-8", HEADERS, asset = "$FOLDER/$name")
        }

        /** The phone's server's host (Caracole's origin). */
        private const val HOST = "127.0.0.1"
    }
}
