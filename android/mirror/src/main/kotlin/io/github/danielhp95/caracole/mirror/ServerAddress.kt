package io.github.danielhp95.caracole.mirror

import java.net.URI
import java.net.URISyntaxException

/**
 * caracole serve's address, as typed in the settings ("192.168.1.20:8737", "http://my-server:8737/"): a scheme
 * (http when none is typed; caracole serve has no TLS), a host and a port. A path typed after it is dropped,
 * since the server's URLs are absolute paths.
 */
class ServerAddress private constructor(private val base: URI) {
    override fun toString(): String = base.toString()
    override fun equals(other: Any?) = other is ServerAddress && other.base == base
    override fun hashCode() = base.hashCode()

    /** The manifest's address. */
    val manifest: URI get() = resolve(MANIFEST_PATH)

    /**
     * [path], a path on the server ("/Estopa/Tu%20calorro/sheet.pdf"), on this server: never another host,
     * whatever the path says.
     */
    fun resolve(path: String): URI {
        require(path.startsWith("/") && !path.startsWith("//")) { "not a path on the server: $path" }
        val uri = URI(base.toString() + path)
        require(uri.scheme == base.scheme && uri.rawAuthority == base.rawAuthority) { "another host: $path" }
        return uri
    }

    companion object {
        const val MANIFEST_PATH = "/api/offline"

        /** The address [text] names; [SyncError.NoAddress] or [SyncError.BadAddress] when it names none. */
        fun parse(text: String): ServerAddress {
            val typed = text.trim()
            if (typed.isEmpty()) throw SyncError.NoAddress()
            val withScheme = if (Regex("^[A-Za-z][A-Za-z0-9+.-]*://").containsMatchIn(typed)) typed else "http://$typed"
            val uri = try {
                URI(withScheme)
            } catch (e: URISyntaxException) {
                throw SyncError.BadAddress(typed)
            }
            val scheme = uri.scheme?.lowercase()
            if (scheme != "http" && scheme != "https") throw SyncError.BadAddress(typed)
            if (uri.host.isNullOrEmpty() || uri.rawUserInfo != null) throw SyncError.BadAddress(typed)
            val authority = uri.rawAuthority
            return ServerAddress(URI("$scheme://$authority"))
        }
    }
}
