package io.github.danielhp95.caracole.youtube

import java.io.Closeable
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.KeyStore
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext

/**
 * A file served on 127.0.0.1 in the test's (the main) process, the one place a test's yt-dlp is pointed at: `GET
 * /clip.m4a` answers [body] as `audio/mp4` (any other path 404), each connection one request, `Connection: close`.
 * Plain HTTP, or HTTPS by the test certificate of the androidTest assets (`youtube/loopback.p12`, a self-signed EC key
 * for 127.0.0.1, made for these tests: no secret of anyone's). With [trickle], the body goes [trickle] bytes at a time,
 * [pause] ms apart, and [bodyBegun] opens at its first byte. [paths] are the paths asked, in order.
 */
class LoopbackServer(
    private val body: ByteArray,
    tls: InputStream? = null,
    private val trickle: Int = 0,
    private val pause: Long = 0,
) : Closeable {
    private val server: ServerSocket = if (tls == null) {
        ServerSocket(0, 10, InetAddress.getByName("127.0.0.1"))
    } else {
        val store = KeyStore.getInstance("PKCS12").apply { tls.use { load(it, PASSWORD) } }
        val keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply { init(store, PASSWORD) }
        SSLContext.getInstance("TLS").apply { init(keys.keyManagers, null, null) }
            .serverSocketFactory.createServerSocket(0, 10, InetAddress.getByName("127.0.0.1"))
    }
    val port: Int = server.localPort
    val paths = ConcurrentLinkedQueue<String>()
    val bodyBegun = CountDownLatch(1)
    private val accepting = Thread({ accept() }, "loopback-server-$port").apply { isDaemon = true; start() }

    fun url(scheme: String = "http"): String = "$scheme://127.0.0.1:$port/clip.m4a"

    private fun accept() {
        while (!server.isClosed) {
            val socket = try {
                server.accept()
            } catch (_: Exception) {
                return
            }
            Thread({ serve(socket) }, "loopback-serve").apply { isDaemon = true; start() }
        }
    }

    private fun serve(socket: Socket) = try {
        socket.use {
            val head = StringBuilder()
            val input = it.getInputStream()
            while (!head.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) return
                head.append(b.toChar())
            }
            val path = head.lineSequence().first().split(' ').getOrElse(1) { "" }
            paths.add(path)
            val out = it.getOutputStream()
            if (path != "/clip.m4a") {
                out.write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
                return
            }
            out.write(("HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nContent-Length: ${body.size}\r\n" +
                "Connection: close\r\n\r\n").toByteArray())
            if (trickle <= 0) {
                out.write(body)
                bodyBegun.countDown()
            } else {
                var at = 0
                while (at < body.size) {
                    val n = minOf(trickle, body.size - at)
                    out.write(body, at, n)
                    out.flush()
                    bodyBegun.countDown()
                    at += n
                    Thread.sleep(pause)
                }
            }
            out.flush()
        }
    } catch (_: Exception) {
        // A client gone (a run killed mid-body): nothing to answer.
    }

    override fun close() {
        server.close()
        accepting.join(2_000)
    }

    companion object {
        private val PASSWORD = "loopback".toCharArray()
    }
}
