package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.py.IpAddress
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import java.security.MessageDigest

/**
 * web/security.py on the phone, answer for answer (vectors/web/security.jsonl), and the launch's secret.
 *
 * - **The secret.** The app makes one at each launch and sets it as the WebView's cookie [SECRET_COOKIE]; every
 *   request must carry it ([hasSecret]), so no other app on the phone can use the server on 127.0.0.1.
 * - **Host names** ([hostName], [answersTo]): a page on another site can make a browser send requests to 127.0.0.1
 *   under a name of its own that it points there (DNS rebinding); every request must name the server by a name it
 *   answers to, or an IP address.
 * - **Writes** ([crossOriginOk]) come from the server's own pages: Sec-Fetch-Site, else Origin against Host; and
 *   every form carries the form token ([sameToken]). An API read ([ownPageRead]) is refused to another site's fetch.
 */
object Security {
    const val SECRET_COOKIE = "caracole-launch"

    private val NAME = Regex("[a-z0-9._-]+|[0-9a-f:.]+")
    private val SAFE_METHODS = setOf("GET", "HEAD", "OPTIONS")

    /** The name a Host header gives, lowercase, without its port or a final dot; null if it isn't one. */
    fun hostName(h: String?): String? {
        if (h.isNullOrEmpty()) return null
        val text = PyText.lower(PyText.strip(h))
        val name: String
        if (text.startsWith("[")) {
            val close = text.indexOf(']', 1)
            if (close < 0) return null
            name = text.substring(1, close)
            val rest = text.substring(close + 1)
            if (rest.isNotEmpty() && !(rest.startsWith(":") && PyText.allDigits(rest.substring(1)))) return null
        } else {
            val colon = text.indexOf(':')
            name = if (colon >= 0) text.substring(0, colon) else text
            if (colon >= 0 && !PyText.allDigits(text.substring(colon + 1))) return null
        }
        val bare = name.trimEnd('.')
        return if (bare.isNotEmpty() && NAME.matches(bare)) bare else null
    }

    /** Whether the server answers to the name a Host header gives: one it knows, or an IP address. */
    fun answersTo(name: String?, allowed: Set<String>): Boolean {
        if (name == null) return false
        if (name in allowed) return true
        return IpAddress.version(name) != null
    }

    /** Whether a request may change something: not a cross-origin write from a browser ([headers] by lowercase
     * name). Reads always may; Sec-Fetch-Site says where a request comes from; Origin alone is compared with Host;
     * neither is no browser. */
    fun crossOriginOk(method: String, headers: Map<String, String>, host: String?): Boolean {
        if (method in SAFE_METHODS) return true
        val site = headers["sec-fetch-site"]
        if (site != null) return site == "same-origin" || site == "none"
        val origin = headers["origin"] ?: return true
        val netloc = try {
            PyUrl.urlsplit(origin).netloc
        } catch (e: PyUrl.Invalid) {
            return false
        }
        return netloc.isNotEmpty() && !host.isNullOrEmpty() && PyText.lower(netloc) == PyText.lower(PyText.strip(host))
    }

    /** Whether a read of the JSON API comes from the server's own pages, or from no browser at all. */
    fun ownPageRead(headers: Map<String, String>): Boolean {
        val site = headers["sec-fetch-site"]
        return site == null || site == "same-origin" || site == "none"
    }

    /** Whether a token is the expected one, compared in constant time; nothing never matches. */
    fun sameToken(given: String?, expected: String): Boolean {
        if (given.isNullOrEmpty() || expected.isEmpty()) return false
        return MessageDigest.isEqual(given.toByteArray(Charsets.UTF_8), expected.toByteArray(Charsets.UTF_8))
    }

    /** Whether the request carries the launch's cookie, `caracole-launch=<secret>`, compared in constant time
     * (every cookie of that name, none skipped); no secret is never one. */
    fun hasSecret(headers: Map<String, String>, secret: String): Boolean {
        if (secret.isEmpty()) return false
        val cookies = headers["cookie"] ?: return false
        var found = false
        for (part in cookies.split(';')) {
            val pair = part.trim(' ', '\t')
            val eq = pair.indexOf('=')
            if (eq < 0 || pair.substring(0, eq) != SECRET_COOKIE) continue
            if (sameToken(pair.substring(eq + 1), secret)) found = true
        }
        return found
    }
}
