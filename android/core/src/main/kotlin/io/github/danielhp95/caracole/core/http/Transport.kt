package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl

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
 * The phone's own transport: `java.net.HttpURLConnection`, no redirect followed, exactly httpx's request headers,
 * gzip and deflate decoded by caracole, 30 s timeouts. While the system property `caracole.network` is `loopback`
 * (every Gradle test task, and the app under `CaracoleTestRunner`), it refuses any host but loopback and the
 * emulator's 10.0.2.2, so no test ever reaches a site.
 */
object RealTransport : Transport {
    const val NETWORK = "caracole.network"

    override fun send(request: HttpRequest): HttpAnswer {
        refuseUnderTests(request.url)
        TODO("lane http-client")
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

/** A test's seam: every request sent to the fake sites server at [base] as `GET {base}/fetch?url=<quoted url>`, its
 * Host kept, so the e2e and the device reach no site. */
class RoutedTransport(val base: String) : Transport {
    override fun send(request: HttpRequest): HttpAnswer = TODO("lane http-client")
}

/** Python's random.uniform: `low + (high - low) * u`, a draw a test records. */
fun interface Draws {
    fun uniform(low: Double, high: Double): Double
}
