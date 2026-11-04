package io.github.danielhp95.caracole

import android.content.Context
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse

/**
 * alphaTab's bundle, Bravura.woff2 and the SoundFont as the APK's assets, answered at `/assets/alphatab/<name>` in the
 * WebView's shouldInterceptRequest before anything else (lane guitar-alphatab): the sandboxed Guitar Pro page's script
 * request carries no launch cookie, so the server can't answer it. Its answer carries `Access-Control-Allow-Origin:
 * *`, the content type and immutable caching.
 *
 * Until its lane lands it answers nothing (null: the request goes on as any other).
 */
class AlphaTabAssets(private val context: Context) {
    fun answer(request: WebResourceRequest): WebResourceResponse? = null
}
