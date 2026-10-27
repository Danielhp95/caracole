package io.github.danielhp95.caracole.mirror

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetAddress
import java.net.InetSocketAddress
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * A caracole serve on 127.0.0.1 for the tests: `GET /api/offline` answers the list of the files [publish]ed,
 * each at its own URL; [answers] replaces what one URL answers; [requests] records every path asked for.
 */
class FakeCaracole : AutoCloseable {
    val requests = CopyOnWriteArrayList<String>()
    val answers = ConcurrentHashMap<String, (HttpExchange) -> Unit>()
    private val bodies = ConcurrentHashMap<String, ByteArray>()
    private val server = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)

    @Volatile var manifest: ByteArray = "{}".toByteArray()

    init {
        server.createContext("/") { exchange ->
            try {
                val raw = exchange.requestURI.rawPath + (exchange.requestURI.rawQuery?.let { q -> "?$q" } ?: "")
                requests.add(raw)
                val answer = answers[raw]
                when {
                    answer != null -> answer(exchange)
                    raw == ServerAddress.MANIFEST_PATH -> send(exchange, 200, manifest, "application/json; charset=utf-8")
                    bodies.containsKey(raw) -> send(exchange, 200, bodies.getValue(raw), "application/octet-stream")
                    else -> send(exchange, 404, "not here".toByteArray(), "text/plain")
                }
            } finally {
                exchange.close()
            }
        }
        server.start()
    }

    val address: ServerAddress get() = ServerAddress.parse("127.0.0.1:${server.address.port}")

    /**
     * Serves [files] (path to bytes) and lists them, [start] first; [extra] adds raw entries' JSON to the list.
     * Returns the list's entries as the app should read them.
     */
    fun publish(
        files: Map<String, ByteArray>,
        start: String = files.keys.first(),
        headers: Map<String, Map<String, String>> = emptyMap(),
        extra: List<String> = emptyList(),
    ): List<Entry> {
        bodies.clear()
        val entries = (listOf(start) + files.keys.filter { it != start }.sorted()).map { path ->
            val bytes = files.getValue(path)
            val url = urlOf(path)
            bodies[url] = bytes
            Entry(path, url, bytes.size.toLong(), sha256(bytes), typeOf(path), headers[path] ?: emptyMap())
        }
        manifest = manifestJson(start, entries.map { entryJson(it) } + extra).toByteArray()
        return entries
    }

    override fun close() = server.stop(0)

    companion object {
        fun send(exchange: HttpExchange, status: Int, body: ByteArray, type: String) {
            exchange.responseHeaders.add("Content-Type", type)
            exchange.sendResponseHeaders(status, if (body.isEmpty()) -1 else body.size.toLong())
            if (body.isNotEmpty()) exchange.responseBody.write(body)
        }

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

        fun urlOf(path: String): String = Links.address(path).removePrefix("https://${Links.HOST}")

        fun typeOf(path: String): String = when (path.substringAfterLast('.')) {
            "html" -> "text/html; charset=utf-8"
            "pdf" -> "application/pdf"
            "cho", "txt" -> "text/plain; charset=utf-8"
            else -> "application/octet-stream"
        }

        fun manifestJson(start: String, entries: List<String>, format: String = "1"): String =
            """{"format": $format, "start": ${quote(start)}, "files": [${entries.joinToString(",\n")}]}"""

        fun entryJson(e: Entry): String {
            val headers = e.headers.entries.joinToString(", ") { (k, v) -> "${quote(k)}: ${quote(v)}" }
            return """{"path": ${quote(e.path)}, "url": ${quote(e.url)}, "size": ${e.size}, """ +
                """"sha256": ${quote(e.sha256)}, "type": ${quote(e.type)}, "headers": {$headers}}"""
        }

        fun quote(text: String): String = buildString {
            append('"')
            for (c in text) when {
                c == '"' -> append("\\\"")
                c == '\\' -> append("\\\\")
                c < ' ' -> append("\\u%04x".format(c.code))
                else -> append(c)
            }
            append('"')
        }
    }
}
