package io.github.danielhp95.caracole

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import androidx.core.content.FileProvider
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.web.DownloadNames
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import java.security.SecureRandom

/**
 * The sync sheet's Export on the phone: the page makes the file (`POST /sync/export`), then follows a link with
 * `download` to `GET /api/sync/export?export=<id>`, which the phone's server sends once. That link never reaches
 * Android's DownloadManager, which carries no launch cookie: the WebView's download listener (and its request
 * interceptor, should the WebView ask the address itself first) hands it here ([isExport]), and the file is read from
 * the server in this process ([LocalFiles], as a file another app opens is), copied whole into the cache's
 * [FOLDER] under the name the server's attachment gives it ([nameOf]), then handed to Android's share sheet
 * ([share]: ACTION_SEND of [TYPE] through a chooser, the copy exposed by the FileProvider), to send it or save it to
 * Files.
 *
 * An export is read once ([copy]: a second ask of the same address is the copy made), and a copy a day old goes.
 */
object Exports {
    /** The cache's folder of the copies shared (res/xml/file_paths.xml's `exports`). */
    const val FOLDER = "exports"

    /** The type the share sheet is given: most apps take a zip (the redesign's Q9), and the name says `.caracole`. */
    const val TYPE = "application/zip"

    /** The export's route on the phone's server (the redesign's §3.4.2). */
    const val PATH = "/api/sync/export"

    /** A file's name when the server's attachment names none (sync.js's own). */
    const val DEFAULT_NAME = "caracole.caracole"

    private const val KEEP_MS = 24 * 60 * 60 * 1000L
    private const val PART = ".part"
    private const val MAX_NAME_BYTES = 255
    private val random = SecureRandom()

    /** What [copy] came to: the copy, with the attachment it was sent as; or the server's refusal. */
    sealed interface Copied {
        data class File(val file: java.io.File, val disposition: String) : Copied
        data class Refused(val status: Int, val message: String?) : Copied
    }

    private val lock = Any()
    private val copies = HashMap<String, Copied.File>()

    /** Whether [url] is an export of the phone's server at [origin] (its scheme, host and port): [PATH] with an
     * `export` named. */
    fun isExport(url: String, origin: String?): Boolean {
        origin ?: return false
        val u = parse(url) ?: return false
        val o = parse(origin) ?: return false
        if (u.scheme?.lowercase() != o.scheme?.lowercase() || u.host?.lowercase() != o.host?.lowercase() ||
            port(u) != port(o) || u.rawUserInfo != null) return false
        if (u.rawPath != PATH) return false
        return exportOf(u.rawQuery).isNotEmpty()
    }

    /**
     * The file's name as [disposition] (a Content-Disposition, download_names.content_disposition's) names it:
     * `filename*` (RFC 5987, UTF-8 or Latin-1) read first, else `filename`; cut to its last part (no folder of a path
     * typed into it, either way's slash), with no control character; [DEFAULT_NAME] for none, `.` or `..`.
     */
    fun nameOf(disposition: String?): String {
        val params = params(disposition ?: return DEFAULT_NAME)
        val named = params["filename*"]?.let(::extended) ?: params["filename"]
        val last = named.orEmpty().split('/', '\\').last()
        val clean = buildString { for (c in last) append(if (c.code < 0x20 || c.code == 0x7f) '_' else c) }.trim()
        if (clean.isEmpty() || clean == "." || clean == ".." || clean.toByteArray().size > MAX_NAME_BYTES) return DEFAULT_NAME
        return clean
    }

    /**
     * The export at [url] read from the phone's server ([files], in this process) and copied into [root], in a folder
     * of its own, under its name ([nameOf] of the server's attachment, else of [disposition], the download listener's):
     * written under a temporary name and renamed whole, so one cut short leaves nothing. The same [url] again is the
     * copy made (the server sends an export once). Copies a day old ([now]) go first.
     */
    fun copy(files: LocalFiles, url: String, root: File, disposition: String? = null,
             now: Long = System.currentTimeMillis()): Copied = synchronized(lock) {
        copies[url]?.takeIf { it.file.isFile }?.let { return it }
        root.mkdirs()
        root.listFiles()?.forEach { if (now - it.lastModified() > KEEP_MS) it.deleteRecursively() }
        val target = parse(url)?.let { u -> u.rawPath + (u.rawQuery?.let { "?$it" } ?: "") }
            ?: return Copied.Refused(400, null)
        when (val got = files.at(target)) {
            is Fetched.Refused -> Copied.Refused(got.status, got.message)
            is Fetched.File -> {
                val name = nameOf(got.disposition ?: disposition)
                val dir = File(root, token())
                val part = File(dir, PART)
                try {
                    if (!dir.mkdirs()) throw IOException("can't make the folder ${dir.name}")
                    got.open().use { input -> part.outputStream().use { input.copyTo(it, 256 * 1024) } }
                    val file = File(dir, name)
                    if (!part.renameTo(file)) throw IOException("can't name the copy $name")
                    dir.setLastModified(now)
                    Copied.File(file, got.disposition ?: DownloadNames.contentDisposition(name)).also { copies[url] = it }
                } catch (e: IOException) {
                    dir.deleteRecursively()
                    throw e
                }
            }
        }
    }

    /**
     * The export at [url] to Android's share sheet: [copy] in the cache's [FOLDER], off the main thread, then
     * ACTION_SEND of [TYPE] with the copy's FileProvider URI (read permission granted, through the chooser too); a
     * refusal or a copy that failed said in a toast.
     */
    suspend fun share(activity: Activity, files: LocalFiles, url: String, disposition: String?) {
        val got = try {
            withContext(Dispatchers.IO) { copy(files, url, File(activity.cacheDir, FOLDER), disposition) }
        } catch (e: IOException) {
            Handoff.toast(activity, activity.getString(R.string.export_failed, e.message ?: e.javaClass.simpleName))
            return
        }
        when (got) {
            is Copied.File -> send(activity, got.file)
            is Copied.Refused -> Handoff.toast(activity, when {
                got.status == 404 -> activity.getString(R.string.export_gone)
                got.message != null -> got.message
                else -> activity.getString(R.string.export_refused, got.status)
            })
        }
    }

    private fun send(activity: Activity, file: File) {
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", file)
        val send = Intent(Intent.ACTION_SEND)
            .setType(TYPE)
            .putExtra(Intent.EXTRA_STREAM, uri)
            .putExtra(Intent.EXTRA_TITLE, file.name)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newRawUri(file.name, uri)
        try {
            activity.startActivity(Intent.createChooser(send, file.name))
        } catch (e: ActivityNotFoundException) {
            Handoff.toast(activity, activity.getString(R.string.no_app, file.name, TYPE))
        }
    }

    /** A query's `export` (its first), "" for none. */
    private fun exportOf(query: String?): String =
        query.orEmpty().split('&').firstOrNull { it.startsWith("export=") }?.removePrefix("export=").orEmpty()

    /** A Content-Disposition's parameters by lowercase name: `name=token` or `name="quoted \" string"`. */
    private fun params(header: String): Map<String, String> {
        val found = HashMap<String, String>()
        var i = header.indexOf(';').takeIf { it >= 0 } ?: return found
        while (i < header.length) {
            i++ // the ';'
            while (i < header.length && header[i] == ' ') i++
            val eq = header.indexOf('=', i)
            if (eq < 0) break
            val semi = header.indexOf(';', i)
            if (semi in 0 until eq) { // a parameter with no value
                i = semi
                continue
            }
            val name = header.substring(i, eq).trim().lowercase()
            i = eq + 1
            val value = StringBuilder()
            if (i < header.length && header[i] == '"') {
                i++
                while (i < header.length && header[i] != '"') {
                    if (header[i] == '\\' && i + 1 < header.length) i++
                    value.append(header[i++])
                }
                i++ // the closing quote
                while (i < header.length && header[i] != ';') i++
                found.putIfAbsent(name, value.toString())
            } else {
                while (i < header.length && header[i] != ';') value.append(header[i++])
                found.putIfAbsent(name, value.toString().trim())
            }
        }
        return found
    }

    /** RFC 5987's `charset'language'percent-encoded`: UTF-8 (or Latin-1) decoded; null for one that isn't. */
    private fun extended(value: String): String? {
        val parts = value.split('\'', limit = 3)
        if (parts.size != 3) return null
        return when (parts[0].trim().lowercase()) {
            "utf-8" -> PyUrl.unquote(parts[2])
            "iso-8859-1" -> String(percentBytes(parts[2]), Charsets.ISO_8859_1)
            else -> null
        }
    }

    /** [text]'s bytes, each `%XX` the byte it names, anything else its own (ASCII) byte. */
    private fun percentBytes(text: String): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        var i = 0
        while (i < text.length) {
            val hex = if (text[i] == '%' && i + 2 < text.length) text.substring(i + 1, i + 3) else null
            val byte = hex?.takeIf { h -> h.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' } }?.toInt(16)
            if (byte != null) {
                out.write(byte)
                i += 3
            } else {
                out.write(text[i].code and 0xff)
                i++
            }
        }
        return out.toByteArray()
    }

    private fun parse(url: String): URI? = try {
        URI(url)
    } catch (e: URISyntaxException) {
        null
    }

    private fun port(uri: URI): Int = if (uri.port != -1) uri.port else if (uri.scheme?.lowercase() == "https") 443 else 80

    private fun token(): String = ByteArray(8).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
}
