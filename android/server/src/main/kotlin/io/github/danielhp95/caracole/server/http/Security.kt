package io.github.danielhp95.caracole.server.http

/** web/security.py, and the launch's secret cookie (lane server-shell). */
object Security {
    const val SECRET_COOKIE = "caracole-launch"

    fun hostName(h: String?): String? = TODO("lane server-shell")
    fun answersTo(name: String?, allowed: Set<String>): Boolean = TODO("lane server-shell")
    fun crossOriginOk(method: String, headers: Map<String, String>, host: String?): Boolean = TODO("lane server-shell")
    fun ownPageRead(headers: Map<String, String>): Boolean = TODO("lane server-shell")
    fun sameToken(given: String?, expected: String): Boolean = TODO("lane server-shell")
    fun hasSecret(headers: Map<String, String>, secret: String): Boolean = TODO("lane server-shell")
}
