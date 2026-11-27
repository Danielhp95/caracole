package io.github.danielhp95.caracole.core.catalogues

import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncError
import java.io.EOFException
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.URI
import java.net.URISyntaxException
import java.security.MessageDigest
import java.time.DateTimeException
import java.time.Instant
import java.util.zip.GZIPInputStream
import java.util.zip.ZipException

/** A catalogue downloaded: the export unpacked into [file], [raw] bytes of it (Python's `raw_bytes`). */
class Fetched(val file: File, val raw: Long)

/**
 * [file]'s bytes, asked at its `url` with `Accept: [accept]` (`application/octet-stream`, an asset's bytes), a
 * redirect followed once and only to one of [hosts] over https (the source's `redirects`, always given, so that no
 * other set is passed by omission: GitHub's API sends an asset's bytes from `release-assets.githubusercontent.com`),
 * streamed: the bytes sent hashed as they come ([onProgress] told how many so far), unpacked through
 * [GZIPInputStream] (gzip's own check of its CRC and size) into [to], stopped past [capFor] the `.gz` size listed or
 * past that size itself, then the hash checked against [Listed.sha256]. With [gzip] false (the chord models, sent as
 * they are) the bytes go to [to] as they come, exactly [Listed.bytes] of them: a Content-Length that says otherwise
 * refused before the body is read, else refused at the first byte past it, and a body that ends before it cut short.
 * An answer but a 200 is [refused]'s error where it gives one, else a 404 the file gone, else [refusal]'s. On any
 * failure [to] is deleted and a [CatalogueError] (a [Limited] for GitHub's hourly share spent) says why; under tests a
 * host but loopback is refused (`RealTransport.refuseUnderTests`) before a socket.
 */
fun download(http: Http, file: Listed, to: File, hosts: Set<String>, gzip: Boolean = true,
             accept: String = "application/octet-stream", refused: (Http.Answer) -> CatalogueError? = { null },
             onProgress: (Long) -> Unit): Fetched {
    try {
        val uri = try {
            URI(file.url)
        } catch (e: URISyntaxException) {
            throw CatalogueError("GitHub listed an address the phone can't read; nothing was downloaded.")
        }
        return ask(http, uri, accept, hosts, DOWNLOAD_TIMEOUT_MS) { answer ->
            if (answer.status != 200) refused(answer)?.let { throw it }
            if (answer.status == 404) throw CatalogueError("The file GitHub listed is gone. Try again.")
            if (answer.status != 200) throw refusal(answer)
            if (gzip) unpack(answer.body, file, to, onProgress) else {
                if (answer.contentLength >= 0 && answer.contentLength != file.bytes) throw CatalogueError(OTHER_SIZE)
                copy(answer.body, file, to, onProgress)
            }
        }
    } catch (e: Throwable) {
        to.delete()
        throw e
    }
}

/** The most a download waits between two reads. */
private const val DOWNLOAD_TIMEOUT_MS = 60_000
private const val CHUNK = 64 * 1024
private const val MISMATCH = "The download isn't the file GitHub listed. Try again."

private fun unpack(body: InputStream, file: Listed, to: File, onProgress: (Long) -> Unit): Fetched {
    val counted = Counted(body, file.bytes)
    val cap = capFor(file.bytes)
    val out = try {
        FileOutputStream(to)
    } catch (e: IOException) {
        throw storage(e)
    }
    var raw = 0L
    out.use {
        try {
            GZIPInputStream(counted, CHUNK).use { gz ->
                val buffer = ByteArray(CHUNK)
                while (true) {
                    val n = gz.read(buffer)
                    if (n < 0) break
                    raw += n
                    if (raw > cap) throw CatalogueError("The file unpacks to more than it should; nothing was imported.")
                    try {
                        out.write(buffer, 0, n)
                    } catch (e: IOException) {
                        throw storage(e)
                    }
                    onProgress(counted.count)
                }
                // What comes after gzip's end is hashed too: the digest is of every byte sent.
                while (counted.read(buffer) >= 0) Unit
            }
        } catch (e: ZipException) {
            throw CatalogueError(MISMATCH, e)
        } catch (e: EOFException) {
            throw CatalogueError(CUT_SHORT, e)
        } catch (e: IOException) {
            throw CatalogueError(CUT_SHORT, e)
        }
        try {
            out.fd.sync()
        } catch (e: IOException) {
            throw storage(e)
        }
    }
    onProgress(counted.count)
    if (counted.hex() != Py.asciiLower(file.sha256)) throw CatalogueError(MISMATCH)
    return Fetched(to, raw)
}

/** [body] into [to] as it is, exactly [Listed.bytes] of it (Counted refuses a byte past them), then its hash. */
private fun copy(body: InputStream, file: Listed, to: File, onProgress: (Long) -> Unit): Fetched {
    val counted = Counted(body, file.bytes)
    val out = try {
        FileOutputStream(to)
    } catch (e: IOException) {
        throw storage(e)
    }
    out.use {
        val buffer = ByteArray(CHUNK)
        while (true) {
            val n = try {
                counted.read(buffer)
            } catch (e: IOException) {
                throw CatalogueError(CUT_SHORT, e)
            }
            if (n < 0) break
            try {
                out.write(buffer, 0, n)
            } catch (e: IOException) {
                throw storage(e)
            }
            onProgress(counted.count)
        }
        if (counted.count != file.bytes) throw CatalogueError(CUT_SHORT)
        try {
            out.fd.sync()
        } catch (e: IOException) {
            throw storage(e)
        }
    }
    if (counted.hex() != Py.asciiLower(file.sha256)) throw CatalogueError(MISMATCH)
    return Fetched(to, counted.count)
}

private const val CUT_SHORT = "The download was cut short. Try again."
private const val OTHER_SIZE =
    "GitHub is sending a file of another size than the one listed; nothing was downloaded. Try again."

/** The most a file of [bytes] `.gz` bytes may unpack to: [Catalogues.CAP_FACTOR] times them, and never less than
 * [Catalogues.CAP_FLOOR], so that a small file that compresses well is no bomb. */
internal fun capFor(bytes: Long): Long = maxOf(Catalogues.CAP_FACTOR.toLong() * bytes, Catalogues.CAP_FLOOR)

private fun storage(e: IOException) = CatalogueError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", e)

/** [body] counted and hashed as it is read; past [most] bytes the download isn't the file listed. */
private class Counted(private val body: InputStream, private val most: Long) : InputStream() {
    private val digest = MessageDigest.getInstance("SHA-256")
    var count = 0L
        private set

    override fun read(): Int {
        val one = ByteArray(1)
        return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xff
    }

    override fun read(b: ByteArray, off: Int, len: Int): Int {
        val n = body.read(b, off, len)
        if (n > 0) {
            count += n
            if (count > most) throw CatalogueError(MISMATCH)
            digest.update(b, off, n)
        }
        return n
    }

    override fun close() = body.close()

    fun hex(): String = digest.digest().joinToString("") { HEX[(it.toInt() shr 4) and 0xf] + HEX[it.toInt() and 0xf] }

    companion object {
        private val HEX = (('0'..'9') + ('a'..'f')).map { it.toString() }
    }
}

// --- asking GitHub --------------------------------------------------------------------------------------------------

private val REDIRECT_STATUSES = setOf(301, 302, 303, 307, 308)

/** One answer of [uri] read, or where it redirects to. */
private sealed interface Step<out T> {
    class Done<T>(val value: T) : Step<T>
    class Hop(val location: String) : Step<Nothing>
}

/**
 * GETs [uri] with [accept] and hands the answer to [read]: a redirect (with a Location) followed once, only where
 * [redirectAllowed] allows it among [redirects] (none followed for an empty set: the redirect is [read]'s answer).
 * Each URI asked is checked by `RealTransport.refuseUnderTests` first; no answer is a [CatalogueError].
 */
internal fun <T> ask(http: Http, uri: URI, accept: String, redirects: Set<String>,
                     readTimeoutMs: Int = LIST_TIMEOUT_MS, read: (Http.Answer) -> T): T {
    val location = when (val first = step(http, uri, accept, readTimeoutMs, redirects.isNotEmpty(), read)) {
        is Step.Done -> return first.value
        is Step.Hop -> first.location
    }
    val next = try {
        uri.resolve(location)
    } catch (e: IllegalArgumentException) {
        throw CatalogueError("GitHub sent the download somewhere the phone can't read; nothing was downloaded.")
    }
    if (!redirectAllowed(uri, next, redirects)) {
        throw CatalogueError("GitHub sent the download to ${next.host ?: location}; nothing was downloaded.")
    }
    return when (val second = step(http, next, accept, readTimeoutMs, true, read)) {
        is Step.Done -> second.value
        is Step.Hop -> throw CatalogueError("GitHub sent the download on more than once; nothing was downloaded.")
    }
}

private const val LIST_TIMEOUT_MS = 30_000

private fun <T> step(http: Http, uri: URI, accept: String, readTimeoutMs: Int, follow: Boolean,
                     read: (Http.Answer) -> T): Step<T> {
    RealTransport.refuseUnderTests(uri.toString())
    val scheme = uri.scheme?.let(Py::asciiLower)
    if ((scheme != "https" && scheme != "http") || uri.host.isNullOrEmpty()) {
        throw CatalogueError("GitHub listed an address the phone can't read; nothing was downloaded.")
    }
    val address = try {
        ServerAddress.parse(scheme + "://" + uri.rawAuthority)
    } catch (e: SyncError) {
        throw CatalogueError("GitHub listed an address the phone can't read; nothing was downloaded.", e)
    }
    return try {
        http.get(address, uri, mapOf("Accept" to accept), readTimeoutMs) { answer ->
            val location = answer.header("location")
            if (follow && answer.status in REDIRECT_STATUSES && location != null) Step.Hop(location)
            else Step.Done(read(answer))
        }
    } catch (e: SyncError) {
        throw CatalogueError(e.message ?: "No answer from GitHub.", e)
    }
}

/**
 * Whether a redirect from [from] to [to] may be followed: to one of [hosts] (in any case), with no user, over https,
 * or over the scheme [from] was asked over (never from https down to http).
 */
internal fun redirectAllowed(from: URI, to: URI, hosts: Set<String>): Boolean {
    val scheme = to.scheme?.let(Py::asciiLower) ?: return false
    val host = to.host?.let(Py::asciiLower) ?: return false
    if (to.rawUserInfo != null) return false
    if (scheme != "https" && scheme != from.scheme?.let(Py::asciiLower)) return false
    return host in hosts
}

/** GitHub's answer that isn't the one asked for: [Limited] for its hourly share spent (a 403 or 429 with
 * `x-ratelimit-remaining: 0` and a reset), else its status. */
internal fun refusal(answer: Http.Answer): CatalogueError {
    if ((answer.status == 403 || answer.status == 429) && answer.header("x-ratelimit-remaining") == "0") {
        val reset = answer.header("x-ratelimit-reset")?.toLongOrNull()
        if (reset != null) {
            try {
                return Limited(Instant.ofEpochSecond(reset))
            } catch (e: DateTimeException) {
                // A reset no clock reads: said as any refusal.
            }
        }
    }
    return CatalogueError("GitHub answered HTTP ${answer.status}. Try again later.")
}
