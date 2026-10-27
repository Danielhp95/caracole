package io.github.danielhp95.caracole

import android.webkit.WebResourceResponse
import androidx.webkit.WebViewAssetLoader
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.Response
import java.io.ByteArrayInputStream
import java.io.FileInputStream
import java.io.IOException

/**
 * Answers the WebView's requests at the root of `https://appassets.androidplatform.net/` ([Links.PREFIX]) from
 * the mirror ([Mirror.respond]): each file with the type caracole listed and the headers caracole serve sends
 * with it (a page's Content-Security-Policy, with its sandbox, which a page's own `<meta>` policy can't set),
 * and a 404 for anything the list doesn't name.
 */
class MirrorPathHandler(private val mirror: Mirror) : WebViewAssetLoader.PathHandler {
    override fun handle(path: String): WebResourceResponse {
        val answer = mirror.respond(path)
        val body = answer.file?.let {
            try {
                FileInputStream(it)
            } catch (e: IOException) {
                null // a sync deleted it since: as if it weren't listed
            }
        }
        if (answer.file != null && body == null) return notFound()
        return WebResourceResponse(answer.mimeType, answer.charset, answer.status, answer.reason, answer.headers,
            body ?: ByteArrayInputStream(ByteArray(0)))
    }

    companion object {
        fun notFound(): WebResourceResponse = Response.NOT_FOUND.let {
            WebResourceResponse(it.mimeType, it.charset, it.status, it.reason, it.headers, ByteArrayInputStream(ByteArray(0)))
        }
    }
}
