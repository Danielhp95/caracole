package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.py.IpAddress
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import java.math.BigInteger

/**
 * A string httpx can't take as a URL, or one of its parts it can't encode: [kind] is the Python exception's name
 * (`InvalidURL`, `UnicodeEncodeError` for a lone surrogate, `IDNAError` and its kinds for a host idna refuses,
 * `RemoteProtocolError` for a redirect's Location), [message] its text, as tests/conformance/vectors/http/urls.jsonl
 * records them.
 */
class UrlError(val kind: String, message: String) : IllegalArgumentException(message)

/**
 * httpx 0.28's URL (`_urlparse.urlparse` and `URL`): its parts normalized as httpx normalizes them, the scheme and an
 * ASCII host lowercased, an IDNA host encoded, a default port dropped, `.` and `..` dropped from the path, and the
 * path, the query and the fragment percent-encoded by the WHATWG sets, keeping each `%XX` already there.
 */
internal class HttpxUrl private constructor(
    val scheme: String, val userinfo: String, val host: String, val port: BigInteger?, val path: String,
    val query: String?, val fragment: String?,
) {
    val authority: String
        get() = buildString {
            if (userinfo.isNotEmpty()) append(userinfo).append('@')
            append(if (':' in host) "[$host]" else host)
            if (port != null) append(':').append(port.toString())
        }

    /** `URL.netloc`: what the Host header says. */
    val netloc: String get() = (if (':' in host) "[$host]" else host) + (port?.let { ":$it" } ?: "")

    /** `URL.raw_path`: the request's target. */
    val rawPath: String get() = path.ifEmpty { "/" } + (query?.let { "?$it" } ?: "")

    val isAbsolute: Boolean get() = scheme.isNotEmpty() && host.isNotEmpty()

    /** `URL.host`: the host, an IDNA one decoded ([UrlError] where idna can't). */
    val decodedHost: String get() = if (host.startsWith("xn--")) Idna.decode(host) else host

    /** `URL.fragment`: unquoted. */
    val decodedFragment: String get() = PyUrl.unquote(fragment ?: "")

    /** `_port_or_default`. */
    val portOrDefault: BigInteger?
        get() = port ?: when (scheme) {
            "http" -> BigInteger.valueOf(80)
            "https" -> BigInteger.valueOf(443)
            else -> null
        }

    override fun toString(): String = buildString {
        if (scheme.isNotEmpty()) append(scheme).append(':')
        val a = authority
        if (a.isNotEmpty()) append("//").append(a)
        append(path)
        if (query != null) append('?').append(query)
        if (fragment != null) append('#').append(fragment)
    }

    /** `URL(self, host=…)` (copy_with). */
    fun withHost(newHost: String): HttpxUrl =
        parse("", Parts(scheme = scheme, authority = authority, path = path, query = query, fragment = fragment, host = newHost))

    /** `URL(self, fragment=…)`. */
    fun withFragment(newFragment: String): HttpxUrl =
        parse("", Parts(scheme = scheme, authority = authority, path = path, query = query, fragment = newFragment))

    /** The keyword arguments of `urlparse(url, **kwargs)` caracole passes: each null when not given. */
    class Parts(val scheme: String? = null, val authority: String? = null, val path: String? = null,
                val query: String? = null, val fragment: String? = null, val host: String? = null,
                val givenQuery: Boolean = query != null, val givenFragment: Boolean = fragment != null)

    companion object {
        const val MAX_URL_LENGTH = 65536
        private const val UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        private const val SUB_DELIMS = "!$&'()*+,;="

        private fun safeSet(vararg excluded: Int): String =
            buildString { for (i in 0x20 until 0x7F) if (i !in excluded) append(i.toChar()) }

        private val FRAG_SAFE = safeSet(0x20, 0x22, 0x3C, 0x3E, 0x60)
        private val QUERY_SAFE = safeSet(0x20, 0x22, 0x23, 0x3C, 0x3E)
        private val PATH_SAFE = safeSet(0x20, 0x22, 0x23, 0x3C, 0x3E, 0x3F, 0x60, 0x7B, 0x7D)
        private val USERINFO_SAFE = safeSet(0x20, 0x22, 0x23, 0x3C, 0x3E, 0x3F, 0x60, 0x7B, 0x7D, 0x2F, 0x3B, 0x3D,
                                            0x40, 0x5B, 0x5C, 0x5D, 0x5E, 0x7C)
        private const val WHATWG_SAFE = "\"`{}%|\\"

        private fun invalid(message: String) = UrlError("InvalidURL", message)

        /** httpx.URL(url): its parts, or [UrlError]. */
        fun parse(url: String): HttpxUrl = parse(url, null)

        /** `str(httpx.URL(url, params=params))`: the params in place of the URL's query, as urlencode writes them
         * (each name's values together, in the order each name came first); none drops the query. */
        fun withParams(url: String, params: List<Pair<String, String>>): HttpxUrl {
            val grouped = LinkedHashMap<String, MutableList<String>>()
            for ((k, v) in params) grouped.getOrPut(k) { ArrayList() }.add(v)
            val query = if (params.isEmpty()) null else grouped.entries.flatMap { (k, vs) -> vs.map { k to it } }
                .joinToString("&") { (k, v) -> quotePlus(k) + "=" + quotePlus(v) }
            return parse(url, Parts(query = query, givenQuery = true))
        }

        private fun checkPrintable(value: String, component: String?) {
            var cpIndex = 0
            var i = 0
            while (i < value.length) {
                val c = value[i]
                if (c.code < 0x20 || c.code == 0x7F) {
                    val where = if (component == null) "URL," else "URL $component component,"
                    throw invalid("Invalid non-printable ASCII character in $where ${PyStr.repr(c.toString())} at position $cpIndex.")
                }
                i += if (Character.isHighSurrogate(c) && i + 1 < value.length && Character.isLowSurrogate(value[i + 1])) 2 else 1
                cpIndex++
            }
        }

        private fun parse(url: String, kw: Parts?): HttpxUrl {
            if (Py.len(url) > MAX_URL_LENGTH) throw invalid("URL too long")
            checkPrintable(url, null)
            var hostKw = kw?.host
            if (hostKw != null && ':' in hostKw && !(hostKw.startsWith("[") && hostKw.endsWith("]"))) hostKw = "[$hostKw]"
            if (kw != null) {
                val given = listOf("scheme" to kw.scheme, "authority" to kw.authority, "path" to kw.path,
                                   "query" to (if (kw.givenQuery) kw.query else null),
                                   "fragment" to (if (kw.givenFragment) kw.fragment else null), "host" to hostKw)
                for ((key, value) in given) {
                    if (value == null) continue
                    if (Py.len(value) > MAX_URL_LENGTH) throw invalid("URL component '$key' too long")
                    checkPrintable(value, key)
                    if (!componentMatches(key, value)) throw invalid("Invalid URL component '$key'")
                }
            }
            // URL_REGEX
            var rest = url
            var schemeIn: String? = null
            run {
                var i = 0
                if (rest.isNotEmpty() && isAsciiLetter(rest[0])) {
                    i = 1
                    while (i < rest.length && isSchemeChar(rest[i])) i++
                }
                if (i < rest.length && rest[i] == ':') {
                    schemeIn = rest.substring(0, i)
                    rest = rest.substring(i + 1)
                }
            }
            var authorityIn: String? = null
            if (rest.startsWith("//")) {
                val end = rest.indexOfFirst(2) { it == '/' || it == '?' || it == '#' }
                authorityIn = rest.substring(2, end)
                rest = rest.substring(end)
            }
            val pathEnd = rest.indexOfFirst(0) { it == '?' || it == '#' }
            val pathIn = rest.substring(0, pathEnd)
            rest = rest.substring(pathEnd)
            var queryIn: String? = null
            if (rest.startsWith("?")) {
                val end = rest.indexOfFirst(1) { it == '#' }
                queryIn = rest.substring(1, end)
                rest = rest.substring(end)
            }
            val fragmentIn: String? = if (rest.startsWith("#")) rest.substring(1) else null

            val scheme = (kw?.scheme ?: schemeIn) ?: ""
            val authority = (kw?.authority ?: authorityIn) ?: ""
            val path = (kw?.path ?: pathIn)
            val query = if (kw != null && kw.givenQuery) kw.query else queryIn
            val frag = if (kw != null && kw.givenFragment) kw.fragment else fragmentIn

            // AUTHORITY_REGEX
            val at = authority.lastIndexOf('@')
            val userinfoIn = if (at >= 0) authority.substring(0, at) else ""
            val hostAndPort = if (at >= 0) authority.substring(at + 1) else authority
            val hostIn: String
            var portIn: String
            if (hostAndPort.startsWith("[") && hostAndPort.lastIndexOf(']') > 0) {
                val close = hostAndPort.lastIndexOf(']')
                hostIn = hostAndPort.substring(0, close + 1)
                portIn = hostAndPort.substring(close + 1)
            } else {
                val end = hostAndPort.indexOfFirst(0) { it == ':' || it == '@' }
                hostIn = hostAndPort.substring(0, end)
                portIn = hostAndPort.substring(end)
            }
            if (portIn.startsWith(":")) portIn = portIn.substring(1)
            val userinfo = userinfoIn
            val host = hostKw ?: hostIn
            val port = portIn

            val parsedScheme = Py.asciiLower(scheme)
            val parsedUserinfo = quote(userinfo, USERINFO_SAFE)
            val parsedHost = encodeHost(host)
            val parsedPort = normalizePort(port, scheme)
            val hasScheme = parsedScheme.isNotEmpty()
            val hasAuthority = parsedUserinfo.isNotEmpty() || parsedHost.isNotEmpty() || parsedPort != null
            validatePath(path, hasScheme, hasAuthority)
            val normalized = if (hasScheme || hasAuthority) normalizePath(path) else path
            val parsedPath = quote(normalized, PATH_SAFE)
            val parsedQuery = query?.let { quote(it, QUERY_SAFE) }
            val parsedFrag = frag?.let { quote(it, FRAG_SAFE) }
            return HttpxUrl(parsedScheme, parsedUserinfo, parsedHost, parsedPort, parsedPath, parsedQuery, parsedFrag)
        }

        private inline fun String.indexOfFirst(from: Int, predicate: (Char) -> Boolean): Int {
            var i = from
            while (i < length) {
                if (predicate(this[i])) return i
                i++
            }
            return length
        }

        private fun isAsciiLetter(c: Char) = c in 'a'..'z' || c in 'A'..'Z'

        private fun isSchemeChar(c: Char) = isAsciiLetter(c) || c in '0'..'9' || c == '+' || c == '.' || c == '-'

        /** COMPONENT_REGEX[key].fullmatch(value). */
        private fun componentMatches(key: String, value: String): Boolean = when (key) {
            "scheme" -> value.isEmpty() || (isAsciiLetter(value[0]) && value.all { isSchemeChar(it) })
            "authority" -> value.none { it == '/' || it == '?' || it == '#' }
            "path" -> value.none { it == '?' || it == '#' }
            "query" -> '#' !in value
            "host" -> (value.startsWith("[") && value.endsWith("]") && value.length >= 2) || ':' !in value
            else -> true
        }

        private fun encodeHost(host: String): String {
            if (host.isEmpty()) return ""
            if (isIpv4Style(host)) {
                if (IpAddress.version(host) != 4) throw invalid("Invalid IPv4 address: ${PyStr.repr(host)}")
                return host
            }
            if (host.startsWith("[") && host.endsWith("]") && host.length >= 2) {
                if (IpAddress.version(host.substring(1, host.length - 1)) != 6) {
                    throw invalid("Invalid IPv6 address: ${PyStr.repr(host)}")
                }
                return host.substring(1, host.length - 1)
            }
            if (host.all { it.code < 0x80 }) return quote(Py.asciiLower(host), SUB_DELIMS + WHATWG_SAFE)
            return try {
                Idna.encode(PyUnicode.lower(host))
            } catch (e: UrlError) {
                throw invalid("Invalid IDNA hostname: ${PyStr.repr(host)}")
            }
        }

        /** `^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$`. */
        private fun isIpv4Style(host: String): Boolean {
            val parts = host.split('.')
            return parts.size == 4 && parts.all { p -> p.isNotEmpty() && p.all { it in '0'..'9' } }
        }

        private fun normalizePort(port: String?, scheme: String): BigInteger? {
            if (port.isNullOrEmpty()) return null
            val n = PyInt.parse(port) ?: throw invalid("Invalid port: ${PyStr.repr(port)}")
            val default = when (scheme) {
                "ftp" -> 21
                "http", "ws" -> 80
                "https", "wss" -> 443
                else -> null
            }
            return if (default != null && n == BigInteger.valueOf(default.toLong())) null else n
        }

        private fun validatePath(path: String, hasScheme: Boolean, hasAuthority: Boolean) {
            if (hasAuthority && path.isNotEmpty() && !path.startsWith("/")) {
                throw invalid("For absolute URLs, path must be empty or begin with '/'")
            }
            if (!hasScheme && !hasAuthority) {
                if (path.startsWith("//")) throw invalid("Relative URLs cannot have a path starting with '//'")
                if (path.startsWith(":")) throw invalid("Relative URLs cannot have a path starting with ':'")
            }
        }

        private fun normalizePath(path: String): String {
            if ('.' !in path) return path
            val components = path.split('/')
            if ("." !in components && ".." !in components) return path
            val output = ArrayList<String>()
            for (component in components) {
                when (component) {
                    "." -> {}
                    ".." -> if (output.isNotEmpty() && output != listOf("")) output.removeAt(output.size - 1)
                    else -> output.add(component)
                }
            }
            return output.joinToString("/")
        }

        private fun isHex(c: Char) = c in '0'..'9' || c in 'a'..'f' || c in 'A'..'F'

        /** `_urlparse.quote`: each `%XX` kept, every other character not unreserved nor in [safe] as its UTF-8's
         * `%XX`; a lone surrogate the UnicodeEncodeError Python's encoder raises for one character. */
        fun quote(s: String, safe: String): String {
            val out = StringBuilder(s.length)
            var i = 0
            while (i < s.length) {
                val c = s[i]
                if (c == '%' && i + 2 < s.length && isHex(s[i + 1]) && isHex(s[i + 2])) {
                    out.append(s, i, i + 3)
                    i += 3
                    continue
                }
                if (c.code < 0x80 && (c in UNRESERVED || c in safe)) {
                    out.append(c)
                    i++
                    continue
                }
                val cp = s.codePointAt(i)
                val n = Character.charCount(cp)
                if (cp in 0xD800..0xDFFF) throw surrogate(s.substring(i, i + 1), 0, 1)
                for (b in String(Character.toChars(cp)).toByteArray(Charsets.UTF_8)) {
                    out.append('%').append(HEX[(b.toInt() shr 4) and 15]).append(HEX[b.toInt() and 15])
                }
                i += n
            }
            return out.toString()
        }

        private const val HEX = "0123456789ABCDEF"
        private const val ALWAYS_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~"

        /** urllib.parse.quote_plus(s, safe=''): spaces as `+`; a lone surrogate the UnicodeEncodeError Python
         * raises encoding the whole string. */
        fun quotePlus(s: String): String {
            val cps = Py.codePoints(s)
            val first = cps.indexOfFirst { it in 0xD800..0xDFFF }
            if (first >= 0) {
                var end = first
                while (end < cps.size && cps[end] in 0xD800..0xDFFF) end++
                throw surrogate(Py.string(cps, first, end), first, end)
            }
            val out = StringBuilder()
            for (b in s.toByteArray(Charsets.UTF_8)) {
                val c = b.toInt() and 0xFF
                when {
                    c == 0x20 -> out.append('+')
                    c < 0x80 && c.toChar() in ALWAYS_SAFE -> out.append(c.toChar())
                    else -> out.append('%').append(HEX[c shr 4]).append(HEX[c and 15])
                }
            }
            return out.toString()
        }

        /** Python's UnicodeEncodeError for the surrogates [run], at [start] to [end] of the string encoded. */
        private fun surrogate(run: String, start: Int, end: Int): UrlError =
            if (end - start == 1) {
                UrlError("UnicodeEncodeError", "'utf-8' codec can't encode character ${PyStr.repr(run)} in position " +
                    "$start: surrogates not allowed")
            } else {
                UrlError("UnicodeEncodeError", "'utf-8' codec can't encode characters in position $start-${end - 1}: " +
                    "surrogates not allowed")
            }
    }
}
