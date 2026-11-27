package io.github.danielhp95.caracole.server.ktor

import io.github.danielhp95.caracole.core.py.Py
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
import io.ktor.utils.io.jvm.javaio.toByteReadChannel
import io.ktor.utils.io.jvm.javaio.toInputStream
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.BindException
import java.util.logging.Level
import java.util.logging.Logger

/**
 * The phone's server: Ktor CIO listening on 127.0.0.1 alone, every request handed whole to [app] (server.py's part
 * of caracole serve): its method, its target exactly as sent (`%2F` and all), its headers by lowercase name (a
 * header sent twice, its last value, as http.server keeps one; cookies all, joined), and its body read up to its
 * route's limit and one byte more, which App refuses as too long (413), or for a route that spools its body
 * ([spooled]: POST /audio/upload) as a stream; a body the client cut short is a 400. A
 * request its headers refuse already (no launch secret, another host name: App.refusedUnread) is answered before its
 * body is read, and its connection closed. The
 * rest of a body too long is Ktor's to drop: CIO reads a request's whole Content-Length before the next request on
 * the connection, so nothing in it is read as one (where server.py closes the connection instead, which CIO, reading
 * requests ahead, can't be told to from an answer). The answer is written as App made it, a file streamed; a HEAD
 * gets its GET's headers and length, and no body. A bug in a route is a 500 that says so; the log has it.
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
        val server = CoroutineScope(BIND_FAILED).embeddedServer(CIO, port = port, host = HOST,
                                                                parentCoroutineContext = BIND_FAILED) {
            intercept(ApplicationCallPipeline.Call) {
                val method = call.request.httpMethod.value
                val target = call.request.uri
                val headers = LinkedHashMap<String, String>()
                for ((name, values) in call.request.headers.entries()) {
                    val key = Py.asciiLower(name)
                    headers[key] = if (key == "cookie") values.joinToString("; ") else values.last()
                }
                val refused = app.refusedUnread(headers)
                if (refused != null) {
                    // Answered on its headers, its body never read, and the connection closed after it (server.py's
                    // close_connection), so nothing of that body is read as a request.
                    refused.headers.add("Connection" to "close")
                    call.respond(outgoing(refused, head = method == "HEAD", call.response.headers))
                    finish()
                    return@intercept
                }
                if (app.spools(method, target)) {
                    spooled(call.receiveChannel(), method, target, headers)
                        .also { call.respond(outgoing(it, head = false, call.response.headers)) }
                    finish()
                    return@intercept
                }
                val response = try {
                    val body = try {
                        read(call.receiveChannel(), app.bodyLimit(method, target) + 1)
                    } catch (e: IOException) {
                        null // the client went, or sent less than it said
                    }
                    if (body == null) {
                        app.finish(Response(400, Body.Bytes(UNREAD.toByteArray()), mutableListOf("Content-Type" to TEXT)))
                    } else {
                        withContext(Dispatchers.IO) { app.handle(Request(method, target, headers, body)) }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    log.log(Level.SEVERE, "caracole: $method $target failed", e)
                    app.finish(Response(500, Body.Bytes(BUG.toByteArray()), mutableListOf("Content-Type" to TEXT)))
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

    /**
     * A request to a route that spools its body (Route.spool: POST /audio/upload): refused unread past the route's
     * limit by its Content-Length, as server.py refuses one (413, its words); else handed to App with its body as a
     * stream, read as the route reads it, never held whole. An answer that leaves the body unread (that refusal, or
     * the route's: the store stops at the first chunk that isn't audio, or past its limit) says `Connection: close`;
     * what the client still sends of it CIO drops, as it drops the rest of a form too long, never reading any of it as
     * a request (LocalServerTest), and never resets the connection under a client still sending, which would lose
     * the refusal it is to read.
     */
    private suspend fun spooled(channel: ByteReadChannel, method: String, target: String,
                                headers: Map<String, String>): Response {
        val length = headers["content-length"]?.let { Py.strip(it).toLongOrNull() }
        if (length != null && length > app.bodyLimit(method, target)) {
            return app.finish(Response(413, Body.Bytes(TOO_LONG.toByteArray()),
                                       mutableListOf("Content-Type" to TEXT, "Connection" to "close")))
        }
        val stream = Ended(channel.toInputStream())
        val response = try {
            withContext(Dispatchers.IO) {
                app.handle(Request(method, target, headers, ByteArray(0), stream))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            log.log(Level.SEVERE, "caracole: $method $target failed", e)
            app.finish(Response(500, Body.Bytes(BUG.toByteArray()), mutableListOf("Content-Type" to TEXT)))
        }
        // Never cancelled: a reset while the client still sends would lose the answer it is to read (its refusal).
        if (!stream.ended) response.headers.add("Connection" to "close")
        return response
    }

    /** A body's stream that says whether it was read to its end. Its close (the route's, which closes what it is
     * handed whatever came of it) lets the channel be: closing the channel's own stream cancels it, which resets a
     * connection the client still sends on, losing the refusal it is to read; CIO drops the rest. */
    private class Ended(private val input: InputStream) : InputStream() {
        @Volatile var ended = false
            private set

        override fun read(): Int = input.read().also { if (it < 0) ended = true }
        override fun read(b: ByteArray, off: Int, len: Int): Int = input.read(b, off, len).also { if (it < 0) ended = true }
        override fun available(): Int = input.available()
        override fun close() {}
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
                Py.asciiLower(name) == "content-type" -> type = ContentType.parse(value)
                Py.asciiLower(name) == "content-length" -> Unit
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
                override fun readFrom(): ByteReadChannel = body.open().toByteReadChannel()
            }
            Body.Empty -> error("answered above")
        }
    }

    private companion object {
        const val HOST = "127.0.0.1"
        const val TEXT = "text/plain; charset=utf-8"
        const val BUG = "caracole hit a bug; its log says where.\n"
        const val UNREAD = "That request's body can't be read.\n"
        const val TOO_LONG = "That is too long to send here.\n"  // server.py's, past a route's limit
        val log: Logger = Logger.getLogger("caracole.server")

        /**
         * CIO binds in a coroutine of its own: a port another app holds (the owner's caracole beside a copy of it)
         * fails [start] with the BindException, and that coroutine throws it too, which, uncaught, kills an Android
         * process. Here it is the failure [start] falls back from; any other is the thread's to handle, as before.
         */
        val BIND_FAILED = CoroutineExceptionHandler { _, e ->
            if (generateSequence(e) { it.cause }.any { it is BindException }) {
                log.log(Level.FINE, "caracole: the preferred port is taken", e)
            } else {
                val thread = Thread.currentThread()
                thread.uncaughtExceptionHandler?.uncaughtException(thread, e)
            }
        }
    }
}
