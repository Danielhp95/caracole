package io.github.danielhp95.caracole.e2e

import java.io.IOException
import java.net.Proxy
import java.net.ProxySelector
import java.net.SocketAddress
import java.net.URI
import java.util.Collections

/**
 * Every HTTP request this JVM sends, counted with its path: mirror's Http (which PeerClient and the mirror's sync send
 * through) is java.net's HttpURLConnection, which asks the default ProxySelector for its way before each connection,
 * whatever its host. Installed before the phone is made, it answers "no proxy" to an http or https address, recording
 * it, and hands anything else (a plain socket's `socket://`) to the selector it replaced.
 *
 * A client that asked for no proxy (`openConnection(Proxy.NO_PROXY)`) would never be seen: so phase 1 checks that
 * the paths of both PeerClient and the mirror's sync were, before phase 2 trusts a count of none.
 */
object Requests : ProxySelector() {
    private val before: ProxySelector? = getDefault()
    private val sent: MutableList<String> = Collections.synchronizedList(ArrayList())

    /** The requests sent since [reset]. */
    val count: Int get() = sent.size

    /** The path of each request sent since [reset], in the order they were sent. */
    val paths: List<String> get() = synchronized(sent) { sent.toList() }

    fun install() {
        if (getDefault() !== this) setDefault(this)
    }

    fun reset() = sent.clear()

    override fun select(uri: URI): List<Proxy> {
        if (uri.scheme?.lowercase() in WEB) {
            sent.add(uri.rawPath.orEmpty())
            return listOf(Proxy.NO_PROXY)
        }
        return before?.select(uri) ?: listOf(Proxy.NO_PROXY)
    }

    override fun connectFailed(uri: URI?, address: SocketAddress?, e: IOException?) {
        if (uri?.scheme?.lowercase() !in WEB) before?.connectFailed(uri, address, e)
    }

    private val WEB = setOf("http", "https")
}
