package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.py.PyUrl

/**
 * URLs as httpx renders them, for caracole's requests (tests/conformance/vectors/http/urls.jsonl). A string httpx
 * can't take is an [UrlError].
 */
object Urls {
    /** `str(httpx.URL(url, params=params))`: the params in place of the query (spaces as `+`, each name's values
     * together); none drops it. PoliteClient asks with params only when there are some. */
    fun withParams(url: String, params: List<Pair<String, String>>): String = HttpxUrl.withParams(url, params).toString()

    /** `httpx.URL(url).raw_path`: the path and the query as httpx sends them. */
    fun target(url: String): String = HttpxUrl.parse(url).rawPath

    /** `httpx.URL(url).host`: lowercased, an IDNA host decoded. */
    fun host(url: String): String = HttpxUrl.parse(url).decodedHost

    /** http.py's `_site`: the last two labels of the host (each provider is on a plain .com or .net domain). */
    fun site(url: String): String = host(url).split('.').takeLast(2).joinToString(".")

    /** `str(httpx.URL(url))`: the URL as httpx normalizes it, the one a request is sent to. */
    fun normalized(url: String): String = HttpxUrl.parse(url).toString()

    /**
     * The URL a redirect from [base] to [location] goes to: httpx's `Client._redirect_url`. A Location httpx can't
     * read is a `RemoteProtocolError`; one with a scheme and no host takes [base]'s host; a relative one is joined to
     * [base] (urllib's urljoin); [base]'s fragment is kept where the new URL has none.
     */
    fun resolve(base: String, location: String): String = resolved(HttpxUrl.parse(base), location).toString()

    internal fun resolved(request: HttpxUrl, location: String): HttpxUrl {
        var url = try {
            HttpxUrl.parse(location)
        } catch (e: UrlError) {
            if (e.kind != "InvalidURL") throw e
            throw UrlError("RemoteProtocolError", "Invalid URL in location header: ${e.message}.")
        }
        if (url.scheme.isNotEmpty() && url.decodedHost.isEmpty()) url = url.withHost(request.decodedHost)
        if (!url.isAbsolute) url = HttpxUrl.parse(UrlJoin.urljoin(request.toString(), url.toString()))
        if (request.decodedFragment.isNotEmpty() && url.decodedFragment.isEmpty()) {
            url = url.withFragment(request.decodedFragment)
        }
        return url
    }
}

/** urllib.parse.urljoin as Python 3.14 has it (RFC 3986's resolution, `..` above the root dropped). */
internal object UrlJoin {
    private val USES_RELATIVE = setOf("", "ftp", "http", "gopher", "nntp", "imap", "wais", "file", "https", "shttp",
                                      "mms", "prospero", "rtsp", "rtsps", "rtspu", "sftp", "svn", "svn+ssh", "ws", "wss")
    private val USES_NETLOC = setOf("", "ftp", "http", "gopher", "nntp", "telnet", "imap", "wais", "file", "mms",
                                    "https", "shttp", "snews", "prospero", "rtsp", "rtsps", "rtspu", "rsync", "svn",
                                    "svn+ssh", "sftp", "nfs", "git", "git+ssh", "ws", "wss", "itms-services")
    private const val SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."

    private class Split(val scheme: String?, val netloc: String?, val path: String, val query: String?,
                        val fragment: String?)

    /** `_urlsplit(url, None)`: absent parts null; Python's ValueError an [UrlError] of kind ValueError. */
    private fun split(given: String): Split {
        try {
            PyUrl.urlsplit(given)  // its checks, which raise where _urlsplit does
        } catch (e: PyUrl.Invalid) {
            throw UrlError("ValueError", e.message ?: "")
        }
        var url = given.trimStart { it.code <= 0x20 }
        for (unsafe in "\t\r\n") url = url.replace(unsafe.toString(), "")
        var scheme: String? = null
        var netloc: String? = null
        var query: String? = null
        var fragment: String? = null
        val i = url.indexOf(':')
        if (i > 0 && (url[0] in 'a'..'z' || url[0] in 'A'..'Z') && url.substring(0, i).all { it in SCHEME_CHARS }) {
            scheme = buildString { for (c in url.substring(0, i)) append(if (c in 'A'..'Z') c + 32 else c) }
            url = url.substring(i + 1)
        }
        if (url.startsWith("//")) {
            val end = "/?#".map { url.indexOf(it, 2) }.filter { it >= 0 }.minOrNull() ?: url.length
            netloc = url.substring(2, end)
            url = url.substring(end)
        }
        if ('#' in url) {
            fragment = url.substringAfter('#')
            url = url.substringBefore('#')
        }
        if ('?' in url) {
            query = url.substringAfter('?')
            url = url.substringBefore('?')
        }
        return Split(scheme, netloc, url, query, fragment)
    }

    private fun unsplit(scheme: String?, netloc: String?, path: String, query: String?, fragment: String?): String {
        var url = path
        if (netloc != null) {
            if (url.isNotEmpty() && !url.startsWith("/")) url = "/$url"
            url = "//$netloc$url"
        } else if (url.startsWith("//")) {
            url = "//$url"
        }
        if (!scheme.isNullOrEmpty()) url = "$scheme:$url"
        if (query != null) url = "$url?$query"
        if (fragment != null) url = "$url#$fragment"
        return url
    }

    fun urljoin(base: String, url: String): String {
        if (base.isEmpty()) return url
        if (url.isEmpty()) return base
        val b = split(base)
        val u = split(url)
        val scheme = u.scheme ?: b.scheme
        if (scheme != b.scheme || (!scheme.isNullOrEmpty() && scheme !in USES_RELATIVE)) return url
        var netloc = u.netloc
        if (scheme.isNullOrEmpty() || scheme in USES_NETLOC) {
            if (!netloc.isNullOrEmpty()) return unsplit(scheme, netloc, u.path, u.query, u.fragment)
            netloc = b.netloc
        }
        var query = u.query
        var fragment = u.fragment
        if (u.path.isEmpty()) {
            if (query == null) {
                query = b.query
                if (fragment == null) fragment = b.fragment
            }
            return unsplit(scheme, netloc, b.path, query, fragment)
        }
        val baseParts = b.path.split('/').toMutableList()
        if (baseParts.last() != "") baseParts.removeAt(baseParts.size - 1)
        val segments: List<String> = if (u.path.startsWith("/")) {
            u.path.split('/')
        } else {
            val all = baseParts + u.path.split('/')
            if (all.size <= 2) all else listOf(all.first()) + all.subList(1, all.size - 1).filter { it.isNotEmpty() } + all.last()
        }
        val resolved = ArrayList<String>()
        for (seg in segments) {
            when (seg) {
                ".." -> if (resolved.isNotEmpty()) resolved.removeAt(resolved.size - 1)
                "." -> {}
                else -> resolved.add(seg)
            }
        }
        if (segments.last() == "." || segments.last() == "..") resolved.add("")
        return unsplit(scheme, netloc, resolved.joinToString("/").ifEmpty { "/" }, query, fragment)
    }
}
