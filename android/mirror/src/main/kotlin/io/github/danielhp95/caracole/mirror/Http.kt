package io.github.danielhp95.caracole.mirror

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URI
import java.net.UnknownHostException

/**
 * Asks caracole serve, and nowhere else: one request at a time, no redirect followed (a redirect is an answer like
 * any other, never a way to another host), no cache, no cookie, no compression (the sizes the list gives are the
 * bytes on the wire). A GET ([get]) or a POST ([post]: a body of a type, its length known), each with the headers
 * its caller adds (Accept, the form token's) and, when the call says so, a read timeout of its own (a phone's state
 * takes a minute to read; an index streamed, as long as it takes: 0). A POST sends no Origin and no Sec-Fetch-Site:
 * it is no browser's, which caracole serve's cross-origin check lets through.
 */
class Http(
    private val connectTimeoutMs: Int = 10_000,
    private val readTimeoutMs: Int = 30_000,
    private val userAgent: String = "caracole-android",
) {
    /** The answer's status, its Content-Length (-1 when it gives none), its headers and its body, open while the
     * caller's read runs. */
    class Answer(val status: Int, val contentLength: Long, val body: InputStream,
                 private val headers: Map<String, String> = emptyMap()) {
        /** The answer's header of that name, in any case; null for none. */
        fun header(name: String): String? = headers[name.lowercase()]
    }

    /**
     * GETs [uri] with [headers] besides its own and hands the answer to [read]; [SyncError.NoAnswer] when nothing
     * answers or the connection breaks, named after [address]. [readTimeoutMs]: this call's, 0 for none.
     */
    fun <T> get(address: ServerAddress, uri: URI, headers: Map<String, String> = emptyMap(),
                readTimeoutMs: Int = this.readTimeoutMs, read: (Answer) -> T): T =
        ask(address, uri, "GET", headers, readTimeoutMs, null, read)

    /** POSTs [body], of [type], to [uri], as [get] asks. */
    fun <T> post(address: ServerAddress, uri: URI, type: String, headers: Map<String, String>, body: ByteArray,
                 readTimeoutMs: Int = this.readTimeoutMs, read: (Answer) -> T): T =
        post(address, uri, type, headers, body.size.toLong(), { it.write(body) }, readTimeoutMs, read)

    /** POSTs a body of [length] bytes, of [type], that [write] writes as it goes (a file's, read in chunks). */
    fun <T> post(address: ServerAddress, uri: URI, type: String, headers: Map<String, String>, length: Long,
                 write: (OutputStream) -> Unit, readTimeoutMs: Int = this.readTimeoutMs, read: (Answer) -> T): T {
        require(length >= 0) { "a body's length is known" }
        return ask(address, uri, "POST", headers + ("Content-Type" to type), readTimeoutMs, Body(length, write), read)
    }

    private class Body(val length: Long, val write: (OutputStream) -> Unit)

    private fun <T> ask(address: ServerAddress, uri: URI, method: String, headers: Map<String, String>,
                        readTimeoutMs: Int, body: Body?, read: (Answer) -> T): T {
        require(readTimeoutMs >= 0) { "a read timeout is 0 (none) or more" }
        val connection = try {
            uri.toURL().openConnection() as HttpURLConnection
        } catch (e: IOException) {
            throw SyncError.NoAnswer(address, describe(e), e)
        }
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.setRequestProperty("User-Agent", userAgent)
            connection.setRequestProperty("Accept-Encoding", "identity")
            for ((name, value) in headers) connection.setRequestProperty(name, value)
            if (body != null) {
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(body.length)
            }
            val status = try {
                if (body != null) connection.outputStream.use { body.write(it) }
                connection.responseCode
            } catch (e: SyncError) {
                throw e
            } catch (e: IOException) {
                // The server may have answered before it read the whole body (413, say): that answer, if it came.
                answeredAnyway(connection) ?: throw SyncError.NoAnswer(address, describe(e), e)
            }
            val length = connection.getHeaderField("Content-Length")?.trim()?.toLongOrNull() ?: -1L
            val got = connection.headerFields.entries.filter { it.key != null }
                .associate { (name, values) -> name.lowercase() to values.joinToString(", ") }
            val stream = (if (status >= 400) connection.errorStream else connection.inputStream) ?: ByteArrayInputStream(ByteArray(0))
            return stream.use {
                try {
                    read(Answer(status, length, it, got))
                } catch (e: SyncError) {
                    throw e
                } catch (e: IOException) {
                    throw SyncError.NoAnswer(address, "connection broke: ${describe(e)}", e)
                }
            }
        } catch (e: IOException) {
            throw SyncError.NoAnswer(address, describe(e), e)
        } finally {
            connection.disconnect()
        }
    }

    /** The status of an answer that came though the body couldn't all be sent; null when none came. */
    private fun answeredAnyway(connection: HttpURLConnection): Int? = try {
        connection.responseCode.takeIf { it > 0 }
    } catch (e: IOException) {
        null
    }

    private fun describe(e: IOException): String = when (e) {
        is ConnectException -> "refused, or nothing listens there"
        is NoRouteToHostException -> "no route: is the phone on the same network?"
        is UnknownHostException -> "name unknown on this network"
        is SocketTimeoutException -> "timed out"
        else -> e.message ?: e.javaClass.simpleName
    }
}
