package io.github.danielhp95.caracole.core.catalogues

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.zip.GZIPOutputStream

/**
 * GitHub, for the catalogues' tests (core's and the server's job): an HttpServer on 127.0.0.1 whose [routes] answer a
 * path ("/repos/…") each, a path with no route 404. [asked] records each request as "GET path · Accept", in order,
 * and [agents] each one's User-Agent.
 */
class FakeGitHub : AutoCloseable {
    /** [chunked]: sent with no Content-Length. */
    class Reply(val status: Int, val body: ByteArray = ByteArray(0), val headers: Map<String, String> = emptyMap(),
                val chunked: Boolean = false)

    val routes = java.util.concurrent.ConcurrentHashMap<String, () -> Reply>()
    val asked = CopyOnWriteArrayList<String>()
    val agents = CopyOnWriteArrayList<String>()
    private val server = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)
    val base: URI get() = URI("http://127.0.0.1:${server.address.port}")

    init {
        server.executor = Executors.newFixedThreadPool(2) { r -> Thread(r, "fake-github").apply { isDaemon = true } }
        server.createContext("/") { exchange -> answer(exchange) }
        server.start()
    }

    private fun answer(exchange: HttpExchange) {
        val path = exchange.requestURI.rawPath
        asked += "${exchange.requestMethod} $path · ${exchange.requestHeaders.getFirst("Accept")}"
        agents += exchange.requestHeaders.getFirst("User-Agent").orEmpty()
        val reply = routes[path]?.invoke() ?: Reply(404, """{"message":"Not Found"}""".toByteArray())
        for ((name, value) in reply.headers) exchange.responseHeaders.add(name, value)
        exchange.sendResponseHeaders(reply.status, when {
            reply.chunked -> 0
            reply.body.isEmpty() -> -1
            else -> reply.body.size.toLong()
        })
        exchange.responseBody.use { it.write(reply.body) }
    }

    fun route(path: String, reply: Reply) {
        routes[path] = { reply }
    }

    override fun close() = server.stop(0)

    companion object {
        fun gzip(bytes: ByteArray): ByteArray {
            val out = ByteArrayOutputStream()
            GZIPOutputStream(out).use { it.write(bytes) }
            return out.toByteArray()
        }

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
