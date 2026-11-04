package io.github.danielhp95.caracole.core.py


/**
 * urllib.parse as Python 3.14 has it, for what caracole serve reads with it: `urlsplit` (an address's parts, or
 * [Invalid] where Python raises ValueError), `unquote` (each ASCII run's escapes decoded as UTF-8, strictly or
 * replaced; a `%` that escapes nothing stays), `unquote_plus`, `parse_qs` and `quote`.
 */
object PyUrl {
    /** Python's ValueError from urlsplit or parse_qsl, or a strict unquote's UnicodeDecodeError. */
    class Invalid(message: String) : Exception(message)

    data class Split(val scheme: String, val netloc: String, val path: String, val query: String, val fragment: String)

    private const val C0_OR_SPACE = "\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\u0008\t\n\u000b\u000c\r" +
        "\u000e\u000f\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f "
    private const val SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."
    private val FUTURE = Regex("[vV][a-fA-F0-9]+\\..+", RegexOption.DOT_MATCHES_ALL)  // \n is gone already

    fun urlsplit(given: String): Split {
        var url = given.trimStart { it in C0_OR_SPACE }
        for (unsafe in "\t\r\n") url = url.replace(unsafe.toString(), "")
        var scheme = ""
        var netloc = ""
        var query = ""
        var fragment = ""
        val i = url.indexOf(':')
        if (i > 0 && (url[0] in 'a'..'z' || url[0] in 'A'..'Z') && url.substring(0, i).all { it in SCHEME_CHARS }) {
            scheme = Py.asciiLower(url.substring(0, i))
            url = url.substring(i + 1)
        }
        if (url.startsWith("//")) {
            val end = "/?#".map { url.indexOf(it, 2) }.filter { it >= 0 }.minOrNull() ?: url.length
            netloc = url.substring(2, end)
            url = url.substring(end)
            if (('[' in netloc) != (']' in netloc)) throw Invalid("Invalid IPv6 URL")
            if ('[' in netloc) checkBracketedNetloc(netloc)
        }
        if ('#' in url) {
            fragment = url.substringAfter('#')
            url = url.substringBefore('#')
        }
        if ('?' in url) {
            query = url.substringAfter('?')
            url = url.substringBefore('?')
        }
        checkNetloc(netloc)
        return Split(scheme, netloc, url, query, fragment)
    }

    private fun checkBracketedNetloc(netloc: String) {
        val hostAndPort = netloc.substringAfterLast('@')
        val open = hostAndPort.indexOf('[')
        val hostname = if (open >= 0) {
            if (open > 0) throw Invalid("Invalid IPv6 URL")
            val bracketed = hostAndPort.substring(open + 1)
            val close = bracketed.indexOf(']')
            val port = if (close >= 0) bracketed.substring(close + 1) else ""
            if (port.isNotEmpty() && !port.startsWith(":")) throw Invalid("Invalid IPv6 URL")
            if (close >= 0) bracketed.substring(0, close) else bracketed
        } else {
            hostAndPort.substringBefore(':')
        }
        if (hostname.startsWith("v") || hostname.startsWith("V")) {
            if (!FUTURE.matches(hostname)) throw Invalid("IPvFuture address is invalid")
        } else {
            when (IpAddress.version(hostname)) {
                null -> throw Invalid("does not appear to be an IPv4 or IPv6 address")
                4 -> throw Invalid("An IPv4 address cannot be in brackets")
            }
        }
    }

    private fun checkNetloc(netloc: String) {
        if (netloc.isEmpty() || PyText.isAscii(netloc)) return
        val n = netloc.replace("@", "").replace(":", "").replace("#", "").replace("?", "")
        val normalized = PyUnicode.nfkc(n)
        if (n == normalized) return
        if (normalized.any { it in "/?#@:" }) throw Invalid("netloc '$netloc' contains invalid characters under NFKC normalization")
    }

    private fun hex(c: Char): Int = when (c) {
        in '0'..'9' -> c - '0'
        in 'a'..'f' -> c - 'a' + 10
        in 'A'..'F' -> c - 'A' + 10
        else -> -1
    }

    /** _unquote_impl over an ASCII run: its escapes as bytes, a `%` that escapes nothing kept. */
    private fun unquoteToBytes(run: String): ByteArray {
        val out = java.io.ByteArrayOutputStream(run.length)
        var i = 0
        while (i < run.length) {
            val c = run[i]
            if (c == '%' && i + 2 < run.length && hex(run[i + 1]) >= 0 && hex(run[i + 2]) >= 0) {
                out.write(hex(run[i + 1]) * 16 + hex(run[i + 2]))
                i += 3
            } else {
                out.write(c.code)
                i++
            }
        }
        return out.toByteArray()
    }

    /** unquote(s, errors="strict" or "replace"): [Invalid] where strict decoding fails. */
    fun unquote(s: String, strict: Boolean = false): String {
        if ('%' !in s) return s
        val out = StringBuilder(s.length)
        var i = 0
        while (i < s.length) {
            var j = i
            if (s[i].code < 0x80) {
                while (j < s.length && s[j].code < 0x80) j++
                val bytes = unquoteToBytes(s.substring(i, j))
                out.append(PyText.utf8(bytes, replace = !strict) ?: throw Invalid("can't decode as UTF-8"))
            } else {
                while (j < s.length && s[j].code >= 0x80) j++
                out.append(s, i, j)
            }
            i = j
        }
        return out.toString()
    }

    fun unquotePlus(s: String): String = unquote(s.replace('+', ' '))

    /**
     * parse_qs(qs, keep_blank_values, max_num_fields): each name's values in order, the names in the order each first
     * came; [Invalid] for more than [maxFields] fields (counted as 1 + its `&`s, empty ones too).
     */
    fun parseQs(qs: String, keepBlank: Boolean = false, maxFields: Int? = null): LinkedHashMap<String, MutableList<String>> {
        val found = LinkedHashMap<String, MutableList<String>>()
        if (qs.isEmpty()) return found
        if (maxFields != null && maxFields < 1 + qs.count { it == '&' }) throw Invalid("Max number of fields exceeded")
        for (field in qs.split('&')) {
            if (field.isEmpty()) continue
            val name = field.substringBefore('=')
            val value = if ('=' in field) field.substringAfter('=') else ""
            if (value.isNotEmpty() || keepBlank) found.getOrPut(unquotePlus(name)) { ArrayList() }.add(unquotePlus(value))
        }
        return found
    }

    /** The first value of each field of a query (parse_qs's, blank values left out, as query() reads one). */
    fun query(target: String): Map<String, String> = try {
        parseQs(urlsplit(target).query).mapValues { it.value.first() }
    } catch (e: Invalid) {
        emptyMap()
    }

    private const val ALWAYS_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~"

    /** quote(s, safe=[safe]): UTF-8, every other byte %XX. */
    fun quote(s: String, safe: String = "/"): String = buildString {
        for (b in s.toByteArray(Charsets.UTF_8)) {
            val c = (b.toInt() and 0xFF)
            if (c < 0x80 && (c.toChar() in ALWAYS_SAFE || c.toChar() in safe)) append(c.toChar()) else append("%%%02X".format(c))
        }
    }

    // --- milestone 4's additions (lane py-sites) ---------------------------------------------------------------------

    /** urllib.parse.urljoin(base, url), Python 3.14's. */
    fun urljoin(base: String, url: String): String = TODO("lane py-sites")

    /** urllib.parse.urlencode of pairs, as httpx and caracole's site modules call it (quote_plus, `doseq`). */
    fun urlencode(pairs: List<Pair<String, String>>, doseq: Boolean = false): String = TODO("lane py-sites")

    /** urllib.parse.urlunsplit. */
    fun urlunsplit(parts: Split): String = TODO("lane py-sites")
}
