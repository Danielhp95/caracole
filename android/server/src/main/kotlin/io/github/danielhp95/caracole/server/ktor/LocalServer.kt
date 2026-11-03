package io.github.danielhp95.caracole.server.ktor

import io.github.danielhp95.caracole.server.http.App

/** Ktor CIO on 127.0.0.1, every request handed whole to [app] (lane server-shell). */
class LocalServer(val app: App) : AutoCloseable {
    /** Listens on [preferred], else on an ephemeral port; the port. */
    fun start(preferred: Int = 8738): Int = TODO("lane server-shell")

    /** http://127.0.0.1:<port>, once started. */
    val origin: String get() = TODO("lane server-shell")

    override fun close(): Unit = TODO("lane server-shell")
}
