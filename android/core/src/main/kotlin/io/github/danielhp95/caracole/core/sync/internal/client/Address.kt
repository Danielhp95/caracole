package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.PeerError

/** peer_sync.peer_address on the phone, with what of urllib.parse.urlsplit it reads, and Python's repr of a str. */
internal object Address {
    /**
     * The address of another caracole serve as typed ("192.168.1.20:8737", "http://phone.lan:8737/"), as caracole
     * asks it: `http://` when no scheme is given, no trailing `/`. A [PeerError] in peer_address's words for one that
     * isn't: no http or https scheme, no host, a query, a fragment or a path; or a port that isn't one.
     */
    fun peerAddress(text: String): String {
        var typed = Py.strip(text)
        if ("://" !in typed) typed = "http://$typed"
        val parts = try {
            split(typed)
        } catch (e: IllegalArgumentException) {
            throw PeerError("${repr(text)} isn't an address we can ask: ${e.message}")
        }
        if (parts.scheme !in setOf("http", "https") || parts.hostname.isNullOrEmpty() || parts.query.isNotEmpty() ||
            parts.fragment.isNotEmpty() || parts.path !in setOf("", "/")) {
            throw PeerError("${repr(text)} isn't a caracole serve address (http://HOST:PORT).")
        }
        return typed.trimEnd('/')
    }

    class Parts(val scheme: String, val netloc: String, val path: String, val query: String, val fragment: String) {
        /** SplitResult._hostinfo. */
        private val hostinfo: Pair<String, String?> by lazy {
            val info = netloc.substringAfterLast('@')
            val open = info.indexOf('[')
            val (host, port) = if (open >= 0) {
                val bracketed = info.substring(open + 1)
                val close = bracketed.indexOf(']')
                if (close < 0) bracketed to "" else bracketed.substring(0, close) to bracketed.substring(close + 1).substringAfter(':', "")
            } else {
                info.substringBefore(':') to info.substringAfter(':', "")
            }
            host to port.ifEmpty { null }
        }

        /** SplitResult.hostname: lowercased (a zone id's case kept), null for none. */
        val hostname: String?
            get() {
                val host = hostinfo.first
                if (host.isEmpty()) return null
                val zone = host.indexOf('%')
                return if (zone < 0) PyUnicode.lower(host) else PyUnicode.lower(host.substring(0, zone)) + host.substring(zone)
            }

        /** SplitResult.port, checked: IllegalArgumentException in its words for a port that isn't one. */
        val port: Int?
            get() {
                val port = hostinfo.second ?: return null
                if (port.isEmpty() || !port.all { it in '0'..'9' }) {
                    throw IllegalArgumentException("Port could not be cast to integer value as ${repr(port)}")
                }
                val n = port.trimStart('0').ifEmpty { "0" }
                if (n.length > 5 || n.toInt() > 65535) throw IllegalArgumentException("Port out of range 0-65535")
                return n.toInt()
            }
    }

    /** urllib.parse.urlsplit's parts of [url], its port read (as peer_address reads `parts.port`): an
     * IllegalArgumentException in its words for brackets that don't pair, or a port that isn't one. */
    fun split(given: String): Parts {
        var url = given.trimStart { it.code <= 0x20 }.filterNot { it == '\t' || it == '\r' || it == '\n' }
        var scheme = ""
        val colon = url.indexOf(':')
        if (colon > 0 && url[0].isAsciiLetter() && url.substring(0, colon).all { it.isAsciiLetter() || it in '0'..'9' || it in "+-." }) {
            scheme = Py.asciiLower(url.substring(0, colon))
            url = url.substring(colon + 1)
        }
        var netloc = ""
        if (url.startsWith("//")) {
            val end = url.indexOfAny(charArrayOf('/', '?', '#'), 2).let { if (it < 0) url.length else it }
            netloc = url.substring(2, end)
            url = url.substring(end)
            if (('[' in netloc) != (']' in netloc)) throw IllegalArgumentException("Invalid IPv6 URL")
        }
        val fragment = url.substringAfter('#', "")
        url = url.substringBefore('#')
        val query = url.substringAfter('?', "")
        url = url.substringBefore('?')
        return Parts(scheme, netloc, url, query, fragment).also { it.port }
    }

    private fun Char.isAsciiLetter() = this in 'a'..'z' || this in 'A'..'Z'

    /** Python's repr of a str: in single quotes (double when it holds a single quote and no double), each backslash,
     * quote, tab, line break and character Python can't print escaped. */
    fun repr(s: String): String {
        val quote = if ('\'' in s && '"' !in s) '"' else '\''
        return buildString {
            append(quote)
            var i = 0
            while (i < s.length) {
                val cp = s.codePointAt(i)
                i += Character.charCount(cp)
                when {
                    cp == quote.code || cp == '\\'.code -> append('\\').appendCodePoint(cp)
                    cp == '\t'.code -> append("\\t")
                    cp == '\n'.code -> append("\\n")
                    cp == '\r'.code -> append("\\r")
                    cp < 0x20 || cp == 0x7f -> append("\\x%02x".format(cp))
                    cp < 0x7f || PyUnicode.isPrintable(cp) -> appendCodePoint(cp)
                    cp <= 0xff -> append("\\x%02x".format(cp))
                    cp <= 0xffff -> append("\\u%04x".format(cp))
                    else -> append("\\U%08x".format(cp))
                }
            }
            append(quote)
        }
    }
}
