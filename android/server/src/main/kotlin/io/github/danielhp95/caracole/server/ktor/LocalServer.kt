package io.github.danielhp95.caracole.server.ktor

import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.ByteArrayContent
import io.ktor.http.content.OutgoingContent
import io.ktor.server.application.ApplicationCallPipeline
import io.ktor.server.application.call
import io.ktor.server.cio.CIO
import io.ktor.server.cio.CIOApplicationEngine
import io.ktor.server.engine.EmbeddedServer
import io.ktor.server.engine.embeddedServer
import io.ktor.server.request.httpMethod
import io.ktor.server.request.receiveChannel
import io.ktor.server.request.uri
import io.ktor.server.response.respond
import io.ktor.util.cio.readChannel
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.net.BindException
import java.util.logging.Level
import java.util.logging.Logger

/**
 * The phone's server: Ktor CIO listening on 127.0.0.1 alone, every request handed whole to [app] (server.py's part
 * of caracole serve): its method, its target exactly as sent (`%2F` and all), its headers by lowercase name (a
 * header sent twice, its last value, as http.server keeps one; cookies all, joined), and its body read up to its
 * route's limit and one byte more, which App refuses as too long. The answer is written as App made it, a file
 * streamed; a HEAD gets its GET's headers and length, and no body. A bug in a route is a 500 that says so; the log
 * has it.
 */
class LocalServer(val app: App) : AutoCloseable {
    private var server: EmbeddedServer<CIOApplicationEngine, CIOApplicationEngine.Configuration>? = null
    private var port = 0

    /** Listens on [preferred], else on an ephemeral port; the port. */
    fun start(preferred: Int = 8738): Int {
        check(server == null) { "the server has started already" }
        val started = try {
            listen(preferred)
        } catch (e: Exception) {
            if (preferred == 0 || !bindFailed(e)) throw e
            listen(0)
        }
        server = started
        port = runBlocking { started.engine.resolvedConnectors().first().port }
        return port
    }

    /** http://127.0.0.1:<port>, once started. */
    val origin: String
        get() {
            check(server != null) { "the server hasn't started" }
            return "http://$HOST:$port"
        }

    override fun close() {
        server?.stop(100, 1_000)
        server = null
    }

    private fun bindFailed(e: Throwable?): Boolean = generateSequence(e) { it.cause }.any { it is BindException }

    private fun listen(port: Int): EmbeddedServer<CIOApplicationEngine, CIOApplicationEngine.Configuration> {
        val server = embeddedServer(CIO, host = HOST, port = port) {
            intercept(ApplicationCallPipeline.Call) {
                val method = call.request.httpMethod.value
                val target = call.request.uri
                val headers = LinkedHashMap<String, String>()
                for ((name, values) in call.request.headers.entries()) {
                    val key = name.lowercase()
                    headers[key] = if (key == "cookie") values.joinToString("; ") else values.last()
                }
                val body = read(call.receiveChannel(), app.bodyLimit(method, target) + 1)
                val response = try {
                    withContext(Dispatchers.IO) { app.handle(Request(method, target, headers, body)) }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    log.log(Level.SEVERE, "caracole: $method $target failed", e)
                    app.finish(Response(500, Body.Bytes("caracole hit a bug; its log says where.\n".toByteArray()),
                                        mutableListOf("Content-Type" to "text/plain; charset=utf-8")))
                }
                call.respond(outgoing(response, head = method == "HEAD", call.response.headers))
                finish()
            }
        }
        try {
            server.start(wait = false)
        } catch (e: Exception) {
            runCatching { server.stop(0, 0) }
            throw e
        }
        return server
    }

    /** Up to [most] bytes of the body: what App needs to read a form, or to know it is too long. */
    private suspend fun read(channel: ByteReadChannel, most: Int): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (out.size() < most) {
            val n = channel.readAvailable(buffer, 0, minOf(buffer.size, most - out.size()))
            if (n < 0) break
            out.write(buffer, 0, n)
        }
        return out.toByteArray()
    }

    private fun outgoing(response: Response, head: Boolean, into: io.ktor.server.response.ResponseHeaders): OutgoingContent {
        val status = HttpStatusCode.fromValue(response.status)
        var type: ContentType? = null
        for ((name, value) in response.headers) {
            when {
                name.equals("Content-Type", ignoreCase = true) -> type = ContentType.parse(value)
                name.equals("Content-Length", ignoreCase = true) -> Unit
                else -> into.append(name, value, safeOnly = false)
            }
        }
        val body = response.body
        val length = when (body) {
            Body.Empty -> 0L
            is Body.Bytes -> body.bytes.size.toLong()
            is Body.FromFile -> body.length
        }
        val contentType = type
        if (head || body == Body.Empty) {
            return object : OutgoingContent.NoContent() {
                override val status = status
                override val contentType = contentType
                override val contentLength = length
            }
        }
        return when (body) {
            is Body.Bytes -> ByteArrayContent(body.bytes, contentType, status)
            is Body.FromFile -> object : OutgoingContent.ReadChannelContent() {
                override val status = status
                override val contentType = contentType
                override val contentLength = length
                override fun readFrom(): ByteReadChannel = body.file.readChannel()
            }
            Body.Empty -> error("answered above")
        }
    }

    private companion object {
        const val HOST = "127.0.0.1"
        val log: Logger = Logger.getLogger("caracole.server")
    }
}
