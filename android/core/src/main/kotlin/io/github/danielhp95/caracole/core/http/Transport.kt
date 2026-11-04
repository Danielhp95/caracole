package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.util.zip.CRC32
import java.util.zip.DataFormatException
import java.util.zip.Inflater

/** One request as the phone sends it: its method, its full URL as httpx renders it, its headers in order. */
data class HttpRequest(val method: String, val url: String, val headers: List<Pair<String, String>>)

/** What a site answered: its status, its headers in order (a name as sent), its body as sent (decoded by caracole). */
class HttpAnswer(val status: Int, val headers: List<Pair<String, String>>, val body: ByteArray)

/** One request sent, no redirect followed ([PoliteClient] follows them by hand). */
fun interface Transport {
    fun send(request: HttpRequest): HttpAnswer
}

/** A request that got no answer: [kind] is httpx's exception type's name (ConnectTimeout, ConnectError…), or
 * "refused" for one a test's transport refuses to send. */
class TransportError(val kind: String, message: String) : Exception(message)

/**
 * The phone's own transport: `java.net.HttpURLConnection` (OkHttp's on Android), no redirect followed, httpx's
 * request headers (Accept any type, `Accept-Encoding: gzip, deflate`, `Connection: keep-alive`, the user agent, and the
 * Host the platform writes from the URL, which is httpx's), a URL httpx's client won't send refused as it refuses it
 * ([protocolOf]), gzip and deflate decoded by caracole as httpx decodes them (a body whose Content-Encoding is gzip
 * alone Android's OkHttp ungzips itself), 30 s timeouts, its errors named as httpx names them. Where the platform
 * does otherwise (a GET sent again on a connection that fails as it's read; Android writing a path's `|`, `^` and `\`
 * again) AGENTS.md says so. While the system property `caracole.network` is
 * `loopback` (every Gradle test task, and the app under `CaracoleTestRunner`), it refuses any host but loopback and the
 * emulator's 10.0.2.2, before a socket opens, so no test ever reaches a site.
 */
object RealTransport : Transport {
    const val NETWORK = "caracole.network"
    private const val TIMEOUT_MS = 30_000

    override fun send(request: HttpRequest): HttpAnswer {
        val opened = protocolOf(request.url)
        refuseUnderTests(opened)
        val connection = try {
            URL(opened).openConnection()
        } catch (e: IOException) {
            throw TransportError("UnsupportedProtocol", e.message ?: e.toString())
        } as? HttpURLConnection ?: throw TransportError("UnsupportedProtocol", unsupported(URL(opened).protocol))
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            connection.requestMethod = request.method
            for ((name, value) in request.headers) {
                if (Py.asciiLower(name) != "host") connection.setRequestProperty(name, value)
            }
            try {
                connection.connect()
            } catch (e: SocketTimeoutException) {
                throw TransportError("ConnectTimeout", e.message ?: "timed out")
            } catch (e: IOException) {
                throw TransportError("ConnectError", e.message ?: e.toString())
            }
            val status: Int
            val headers: List<Pair<String, String>>
            val raw: ByteArray
            try {
                status = connection.responseCode
                if (status < 0) throw TransportError("RemoteProtocolError", "not an HTTP answer")
                headers = headersOf(connection)
                val stream: InputStream? = if (status >= 400) connection.errorStream else connection.inputStream
                raw = stream?.use { it.readBytes() } ?: ByteArray(0)
            } catch (e: SocketTimeoutException) {
                throw TransportError("ReadTimeout", e.message ?: "timed out")
            } catch (e: ConnectException) {
                throw TransportError("ConnectError", e.message ?: e.toString())
            } catch (e: IOException) {
                throw TransportError(if (platformDecoding(e)) "DecodingError" else "ReadError", e.message ?: e.toString())
            }
            return HttpAnswer(status, headers, ContentDecoding.decode(headers, raw))
        } finally {
            connection.disconnect()
        }
    }

    /** Android's OkHttp ungzips a body whose Content-Encoding is gzip alone itself, whatever the request's
     * Accept-Encoding, and takes the header away: a body it can't read fails as Okio's GzipSource says
     * ("ID1ID2: actual 0x… != expected 0x…"), which is httpx's DecodingError. */
    private fun platformDecoding(e: IOException): Boolean =
        e is java.util.zip.ZipException || e.message?.contains(": actual 0x") == true

    /** The answer's headers in order, read as httpx reads them: the whole set as ASCII, else UTF-8, else Latin-1. */
    private fun headersOf(connection: HttpURLConnection): List<Pair<String, String>> {
        val read = ArrayList<Pair<String, String>>()
        var i = 0
        while (true) {
            val value = connection.getHeaderField(i) ?: if (i == 0) { i++; continue } else break
            val name = connection.getHeaderFieldKey(i)
            // Android's OkHttp adds its own (X-Android-Sent-Millis…), which no site sent and httpx never sees.
            if (name != null && !Py.asciiLower(name).startsWith("x-android-")) read += name to value
            i++
            if (i > 10_000) break
        }
        // The JDK gives each byte as a char (Latin-1); Android's OkHttp gives UTF-8 already (a char above U+00FF).
        if (read.any { (n, v) -> (n + v).any { it.code > 0xFF } }) return read
        val bytes = read.map { (n, v) -> n.toByteArray(Charsets.ISO_8859_1) to v.toByteArray(Charsets.ISO_8859_1) }
        if (bytes.all { (n, v) -> (n + v).all { it >= 0 } }) return read
        val utf8 = bytes.map { (n, v) -> PyText.utf8(n) to PyText.utf8(v) }
        if (utf8.all { (n, v) -> n != null && v != null }) return utf8.map { (n, v) -> n!! to v!! }
        return read
    }

    private fun unsupported(scheme: String) = "Request URL has an unsupported protocol '$scheme://'."

    /**
     * The URL to open for [url], as httpx's client and httpcore take it: one with no scheme or no host (httpx merges
     * it with its empty base URL) is "missing an 'http://' or 'https://' protocol", a scheme but http, https, ws and
     * wss an unsupported protocol (both httpx's UnsupportedProtocol, before any socket), and ws and wss are asked as
     * http and https are (httpcore's ports and TLS for them), so HttpURLConnection can open them.
     */
    private fun protocolOf(url: String): String {
        val parsed = try {
            HttpxUrl.parse(url)
        } catch (e: UrlError) {
            throw TransportError(e.kind, e.message ?: "")
        }
        if (!parsed.isAbsolute) throw TransportError("UnsupportedProtocol", "Request URL is missing an 'http://' or 'https://' protocol.")
        return when (parsed.scheme) {
            "http", "https" -> url
            "ws" -> "http" + url.substring(2)
            "wss" -> "https" + url.substring(3)
            else -> throw TransportError("UnsupportedProtocol", unsupported(parsed.scheme))
        }
    }

    /**
     * [TransportError] ("refused") for a site's URL while `caracole.network` is `loopback`: its host as urlsplit reads
     * it (after the netloc's last `@`), as Android's OkHttp reads it (its authority ends at the first of `/\?#`, so
     * `http://site\@127.0.0.1/` is the site's) and as java.net.URL reads it must each be loopback or 10.0.2.2.
     */
    fun refuseUnderTests(url: String) {
        if (System.getProperty(NETWORK) != "loopback") return
        val split = try {
            PyUrl.urlsplit(url).netloc
        } catch (e: PyUrl.Invalid) {
            ""
        }
        val okHttp = url.substringAfter(':', "").trimStart('/', '\\').takeWhile { it !in "/\\?#" }
        val javaNet = try {
            URL(url).host ?: ""
        } catch (e: IOException) {
            ""
        }
        for (host in listOf(hostOf(split), hostOf(okHttp), Py.asciiLower(javaNet))) {
            if (host !in LOOPBACK) throw TransportError("refused", "no request to $host from a test (caracole.network=loopback)")
        }
    }

    private fun hostOf(authority: String): String {
        val at = authority.substringAfterLast('@')
        return Py.asciiLower(if (at.startsWith("[")) at.substringBefore(']') + "]" else at.substringBefore(':'))
    }

    private val LOOPBACK = setOf("127.0.0.1", "localhost", "[::1]", "10.0.2.2")
}

/**
 * httpx's content decoders (`Response.content` read whole): each `Content-Encoding` named (the headers' values, split
 * at commas, stripped and lowercased) applied last first, `gzip` one member as zlib's gzip mode reads it, `deflate`
 * zlib's stream or, when that fails, a raw one, `identity` and any other left as they are. A body that won't decode
 * is httpx's DecodingError, its words zlib's (`Error -3 while decompressing data: …`); one cut short gives what it
 * gave, as zlib's decompressobj and its flush do (vectors/http/rules.jsonl's `decode`).
 */
internal object ContentDecoding {
    private val EMPTY = ByteArray(0)

    fun decode(headers: List<Pair<String, String>>, body: ByteArray): ByteArray {
        val codings = headers.filter { Py.asciiLower(it.first) == "content-encoding" }
            .flatMap { it.second.split(',') }
            .map { Py.asciiLower(PyText.strip(it)) }
            .filter { it == "gzip" || it == "deflate" || it == "identity" }
        var data = body
        for (coding in codings.reversed()) {
            data = when (coding) {
                "gzip" -> gunzip(data)
                "deflate" -> inflate(data)
                else -> data
            }
        }
        return data
    }

    /** Z_DATA_ERROR as CPython's zlib words it. */
    private fun decoding(why: String?): TransportError =
        TransportError("DecodingError", "Error -3 while decompressing data: ${why ?: "invalid input data"}")

    /** Inflate what [data] holds from [offset]: everything a whole stream gives, or what a cut-short one gave; a
     * stream that needs a preset dictionary gives nothing ([Inflater.needsDictionary] then says so). */
    private fun inflate(inflater: Inflater, data: ByteArray, offset: Int): ByteArray {
        inflater.setInput(data, offset, data.size - offset)
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (!inflater.finished()) {
            val n = inflater.inflate(buffer)
            if (n == 0 && (inflater.needsInput() || inflater.needsDictionary())) break
            out.write(buffer, 0, n)
        }
        return out.toByteArray()
    }

    /** httpx's DeflateDecoder: zlib's stream; when its first attempt fails (an error, or zlib's Z_NEED_DICT, its
     * "Error 2"), the whole body again as a raw deflate stream, whose error is the body's. */
    fun inflate(data: ByteArray): ByteArray {
        val zlib = Inflater(false)
        try {
            val out = inflate(zlib, data, 0)
            if (!zlib.needsDictionary()) return out
        } catch (e: DataFormatException) {
            // read again as raw
        } finally {
            zlib.end()
        }
        val raw = Inflater(true)
        try {
            return inflate(raw, data, 0)
        } catch (e: DataFormatException) {
            throw decoding(e.message)
        } finally {
            raw.end()
        }
    }

    /**
     * httpx's GZipDecoder, zlib's inflate with windowBits 16 + 15 (inflate.c's header states): the magic once two
     * bytes are there, the method and the reserved flags once four are, then the time and the OS, FEXTRA, FNAME,
     * FCOMMENT and FHCRC (the CRC-32 of the header before it, its low 16 bits) as their flags say, the deflate data,
     * and the trailer's CRC-32 once its four bytes are there and its length once the next four are. A header or a
     * trailer cut short is no error (zlib waits for more, and flush gives nothing more); what follows the member is
     * left unread (unused_data).
     */
    fun gunzip(data: ByteArray): ByteArray {
        val n = data.size
        fun at(i: Int) = data[i].toInt() and 0xFF
        if (n < 2) return EMPTY
        if (at(0) != 0x1F || at(1) != 0x8B) throw decoding("incorrect header check")
        if (n < 4) return EMPTY
        if (at(2) != 8) throw decoding("unknown compression method")
        val flags = at(3)
        if (flags and 0xE0 != 0) throw decoding("unknown header flags set")
        var pos = 10
        if (n < pos) return EMPTY
        if (flags and 0x04 != 0) {
            if (n < pos + 2) return EMPTY
            pos += 2 + (at(pos) or (at(pos + 1) shl 8))
            if (n < pos) return EMPTY
        }
        for (flag in intArrayOf(0x08, 0x10)) {
            if (flags and flag == 0) continue
            while (pos < n && at(pos) != 0) pos++
            if (pos >= n) return EMPTY
            pos++
        }
        if (flags and 0x02 != 0) {
            if (n < pos + 2) return EMPTY
            val crc = CRC32().apply { update(data, 0, pos) }.value and 0xFFFF
            if ((at(pos) or (at(pos + 1) shl 8)).toLong() != crc) throw decoding("header crc mismatch")
            pos += 2
        }
        val inflater = Inflater(true)
        try {
            val out = inflate(inflater, data, pos)
            if (!inflater.finished()) return out
            val trailer = n - inflater.remaining
            if (n - trailer < 4) return out
            if (le32(data, trailer) != CRC32().apply { update(out) }.value) throw decoding("incorrect data check")
            if (n - trailer < 8) return out
            if (le32(data, trailer + 4) != (out.size.toLong() and 0xFFFFFFFFL)) throw decoding("incorrect length check")
            return out
        } catch (e: DataFormatException) {
            throw decoding(e.message)
        } finally {
            inflater.end()
        }
    }

    private fun le32(b: ByteArray, at: Int): Long =
        (0 until 4).fold(0L) { acc, i -> acc or ((b[at + i].toLong() and 0xFF) shl (8 * i)) }
}

/** A test's seam: every request sent to the fake sites server at [base] as `GET {base}/fetch?url=<quoted url>`, the
 * site's URL in the query and never in a Host header (the server's own is the platform's), its other headers as they
 * are, through [RealTransport], so the e2e and the device reach no site. */
class RoutedTransport(val base: String) : Transport {
    override fun send(request: HttpRequest): HttpAnswer {
        val routed = base.trimEnd('/') + "/fetch?url=" + HttpxUrl.quotePlus(request.url)
        return RealTransport.send(HttpRequest("GET", routed, request.headers.filter { Py.asciiLower(it.first) != "host" }))
    }
}

/** Python's random.uniform: `low + (high - low) * u`, a draw a test records. */
fun interface Draws {
    fun uniform(low: Double, high: Double): Double
}
