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
 * Host the platform writes from the URL, which is httpx's), gzip and deflate decoded by caracole as httpx decodes
 * them (a body whose Content-Encoding is gzip alone Android's OkHttp ungzips itself), 30 s timeouts, its errors named
 * as httpx names them. While the system property `caracole.network` is
 * `loopback` (every Gradle test task, and the app under `CaracoleTestRunner`), it refuses any host but loopback and the
 * emulator's 10.0.2.2, before a socket opens, so no test ever reaches a site.
 */
object RealTransport : Transport {
    const val NETWORK = "caracole.network"
    private const val TIMEOUT_MS = 30_000

    override fun send(request: HttpRequest): HttpAnswer {
        refuseUnderTests(request.url)
        val connection = try {
            URL(request.url).openConnection() as HttpURLConnection
        } catch (e: IOException) {
            throw TransportError("UnsupportedProtocol", e.message ?: e.toString())
        }
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

    /** [TransportError] ("refused") for a site's URL while `caracole.network` is `loopback`. */
    fun refuseUnderTests(url: String) {
        if (System.getProperty(NETWORK) != "loopback") return
        val netloc = try {
            PyUrl.urlsplit(url).netloc.substringAfterLast('@')
        } catch (e: PyUrl.Invalid) {
            ""
        }
        val host = Py.asciiLower(if (netloc.startsWith("[")) netloc.substringBefore(']') + "]" else netloc.substringBefore(':'))
        if (host !in LOOPBACK) throw TransportError("refused", "no request to $host from a test (caracole.network=loopback)")
    }

    private val LOOPBACK = setOf("127.0.0.1", "localhost", "[::1]", "10.0.2.2")
}

/**
 * httpx's content decoders: each `Content-Encoding` named (the headers' values, split at commas, trimmed and
 * lowercased) applied last first, `gzip` one member as zlib reads it, `deflate` zlib's stream or else a raw one,
 * `identity` and any other left as they are. A body that won't decode is httpx's DecodingError.
 */
internal object ContentDecoding {
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

    private fun error(e: Exception): TransportError = TransportError("DecodingError", e.message ?: e.toString())

    /** Inflate what [data] holds from [offset]: everything a whole stream gives, or what a cut-short one gave. */
    private fun inflate(inflater: Inflater, data: ByteArray, offset: Int): ByteArray {
        inflater.setInput(data, offset, data.size - offset)
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (!inflater.finished()) {
            val n = inflater.inflate(buffer)
            if (n == 0) {
                if (inflater.needsInput() || inflater.needsDictionary()) break
            }
            out.write(buffer, 0, n)
        }
        return out.toByteArray()
    }

    fun inflate(data: ByteArray): ByteArray {
        val zlib = Inflater(false)
        try {
            return inflate(zlib, data, 0)
        } catch (e: DataFormatException) {
            // httpx's DeflateDecoder: a body that isn't a zlib stream is read again as a raw deflate one
        } finally {
            zlib.end()
        }
        val raw = Inflater(true)
        try {
            return inflate(raw, data, 0)
        } catch (e: DataFormatException) {
            throw error(e)
        } finally {
            raw.end()
        }
    }

    fun gunzip(data: ByteArray): ByteArray {
        if (data.isEmpty()) return data
        if (data.size < 10) return ByteArray(0)  // a header cut short: zlib waits for more, and flush gives nothing
        if ((data[0].toInt() and 0xFF) != 0x1F || (data[1].toInt() and 0xFF) != 0x8B) {
            throw TransportError("DecodingError", "Error -3 while decompressing data: incorrect header check")
        }
        if ((data[2].toInt() and 0xFF) != 8) {
            throw TransportError("DecodingError", "Error -3 while decompressing data: unknown compression method")
        }
        val flags = data[3].toInt() and 0xFF
        var at = 10
        if (flags and 4 != 0) {
            if (at + 2 > data.size) return ByteArray(0)
            at += 2 + ((data[at].toInt() and 0xFF) or ((data[at + 1].toInt() and 0xFF) shl 8))
        }
        if (flags and 8 != 0) {
            while (at < data.size && data[at].toInt() != 0) at++
            at++
        }
        if (flags and 16 != 0) {
            while (at < data.size && data[at].toInt() != 0) at++
            at++
        }
        if (flags and 2 != 0) at += 2
        if (at > data.size) return ByteArray(0)
        val inflater = Inflater(true)
        try {
            val out = inflate(inflater, data, at)
            if (inflater.finished()) {
                val trailer = data.size - inflater.remaining
                if (trailer + 8 <= data.size) {
                    val crc = CRC32().also { it.update(out) }.value
                    val said = le32(data, trailer)
                    if (said != crc) throw TransportError("DecodingError", "Error -3 while decompressing data: incorrect data check")
                    if (le32(data, trailer + 4) != (out.size.toLong() and 0xFFFFFFFFL)) {
                        throw TransportError("DecodingError", "Error -3 while decompressing data: incorrect length check")
                    }
                }
            }
            return out
        } catch (e: DataFormatException) {
            throw error(e)
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
