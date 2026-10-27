package io.github.danielhp95.caracole.mirror

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URI
import java.net.UnknownHostException

/**
 * GETs from caracole serve, and from nowhere else: one request at a time, no redirect followed (a redirect is
 * an answer like any other, never a way to another host), no cache, no cookie, no compression (the sizes the
 * list gives are the bytes on the wire).
 */
class Http(
    private val connectTimeoutMs: Int = 10_000,
    private val readTimeoutMs: Int = 30_000,
    private val userAgent: String = "caracole-android",
) {
    /** The answer's status, its Content-Length (-1 when it gives none) and its body, open while [read] runs. */
    class Answer(val status: Int, val contentLength: Long, val body: InputStream)

    /**
     * GETs [uri] and hands the answer to [read]; [SyncError.NoAnswer] when nothing answers or the connection
     * breaks, named after [address].
     */
    fun <T> get(address: ServerAddress, uri: URI, read: (Answer) -> T): T {
        val connection = try {
            uri.toURL().openConnection() as HttpURLConnection
        } catch (e: IOException) {
            throw SyncError.NoAnswer(address, describe(e), e)
        }
        try {
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.setRequestProperty("User-Agent", userAgent)
            connection.setRequestProperty("Accept-Encoding", "identity")
            val status = try {
                connection.responseCode
            } catch (e: IOException) {
                throw SyncError.NoAnswer(address, describe(e), e)
            }
            val length = connection.getHeaderField("Content-Length")?.trim()?.toLongOrNull() ?: -1L
            val body = (if (status >= 400) connection.errorStream else connection.inputStream) ?: ByteArrayInputStream(ByteArray(0))
            return body.use {
                try {
                    read(Answer(status, length, it))
                } catch (e: SyncError) {
                    throw e
                } catch (e: IOException) {
                    throw SyncError.NoAnswer(address, "the connection broke: ${describe(e)}", e)
                }
            }
        } catch (e: IOException) {
            throw SyncError.NoAnswer(address, describe(e), e)
        } finally {
            connection.disconnect()
        }
    }

    private fun describe(e: IOException): String = when (e) {
        is ConnectException -> "the connection was refused, or nothing listens there"
        is NoRouteToHostException -> "no route to it: is the phone on the same network?"
        is UnknownHostException -> "the name isn't known on this network"
        is SocketTimeoutException -> "it took too long"
        else -> e.message ?: e.javaClass.simpleName
    }
}
