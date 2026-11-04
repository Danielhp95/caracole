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
        if (!url.isAbsolute) {
            val joined = try {
                PyUrl.urljoin(request.toString(), url.toString())
            } catch (e: PyUrl.Invalid) {
                throw UrlError("ValueError", e.message ?: "")
            }
            url = HttpxUrl.parse(joined)
        }
        if (request.decodedFragment.isNotEmpty() && url.decodedFragment.isEmpty()) {
            url = url.withFragment(request.decodedFragment)
        }
        return url
    }
}
