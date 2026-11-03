package io.github.danielhp95.caracole.e2e

import java.io.IOException
import java.net.Proxy
import java.net.ProxySelector
import java.net.SocketAddress
import java.net.URI
import java.util.concurrent.atomic.AtomicInteger

/**
 * Every HTTP request this JVM sends, counted: mirror's Http (which PeerClient and the mirror's sync send through) is
 * java.net's HttpURLConnection, which asks the default ProxySelector for its way before each connection, whatever its
 * host. Installed before the phone is made, it answers "no proxy" to an http or https address, counting it, and hands
 * anything else (a plain socket's `socket://`) to the selector it replaced.
 */
object Requests : ProxySelector() {
    private val before: ProxySelector? = getDefault()
    private val sent = AtomicInteger()

    /** The requests sent since [reset]. */
    val count: Int get() = sent.get()

    fun install() {
        if (getDefault() !== this) setDefault(this)
    }

    fun reset() = sent.set(0)

    override fun select(uri: URI): List<Proxy> {
        if (uri.scheme?.lowercase() in WEB) {
            sent.incrementAndGet()
            return listOf(Proxy.NO_PROXY)
        }
        return before?.select(uri) ?: listOf(Proxy.NO_PROXY)
    }

    override fun connectFailed(uri: URI?, address: SocketAddress?, e: IOException?) {
        if (uri?.scheme?.lowercase() !in WEB) before?.connectFailed(uri, address, e)
    }

    private val WEB = setOf("http", "https")
}
