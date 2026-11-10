package io.github.danielhp95.caracole.server.pages

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import java.io.File
import java.io.IOException
import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.attribute.BasicFileAttributes

/**
 * What the versions page and the page of a harmonica tab's readings share (web/versions_routes.py and
 * web/harmonica_routes.py): pages.page with a head of its own (a page that follows a request reloads every
 * [REFRESH] seconds), an address read as parse_qsl reads it, the songs a library folder is, the files the phone wrote
 * for a song (WrittenPages, render.written_file's), a kept file read, and the job a page shows; each in Python's
 * words.
 */
internal object Choices {
    /** pages.REFRESH: seconds between reloads of a page that follows a request while it waits or runs. */
    const val REFRESH = 10

    /** The answer the address can't be read gets, for either page. */
    val NOT_AN_ADDRESS get() = Refused(400, "Not an address", "That address can't be read.")

    /** pages.page: [body] under the header, the library the phone shows in the header and the tab's title, [head]
     * before the icon (the refresh of a page that follows a request); the message pages' style and policy, no
     * script. */
    fun page(status: Int, title: String, body: String, name: LibraryName, head: String = ""): Response {
        var html = MessagePage.html(title, body, name)
        if (head.isNotEmpty()) {
            val at = name.icon() + "<title>"
            html = html.replaceFirst(at, head + at)
        }
        return Response(status, Body.Bytes(html.toByteArray()),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to MessagePage.csp))
    }

    /** The refresh of a page that follows [job] while it waits or runs, else none. */
    fun refresh(job: Job?): String =
        if (job != null && job.active) "<meta http-equiv=\"refresh\" content=\"$REFRESH\">\n" else ""

    /** html.escape(s, quote=True). */
    fun esc(s: String): String = PyText.escape(s)

    /** urllib.parse.quote(s): every byte but the letters, the digits, `_.-~` and `/` as %XX. */
    fun quote(s: String): String = PyUrl.quote(s)

    /**
     * `dict(parse_qsl(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=10))`: each
     * field's last value; [NOT_AN_ADDRESS] for an address urlsplit refuses, more than [maxFields] fields, or an
     * escape that isn't UTF-8.
     */
    fun query(target: String, maxFields: Int = 10): Map<String, String> {
        val qs = try {
            PyUrl.urlsplit(target).query
        } catch (e: PyUrl.Invalid) {
            throw NOT_AN_ADDRESS
        }
        val fields = LinkedHashMap<String, String>()
        if (qs.isEmpty()) return fields
        if (maxFields < 1 + qs.count { it == '&' }) throw NOT_AN_ADDRESS
        for (field in qs.split('&')) {
            if (field.isEmpty()) continue
            val at = field.indexOf('=')
            val name = if (at >= 0) field.substring(0, at) else field
            val value = if (at >= 0) field.substring(at + 1) else ""
            try {
                fields[PyUrl.unquote(name.replace('+', ' '), strict = true)] =
                    PyUrl.unquote(value.replace('+', ' '), strict = true)
            } catch (e: PyUrl.Invalid) {
                throw NOT_AN_ADDRESS
            }
        }
        return fields
    }

    /** `s.isascii() and s.isdigit()`, at most [most] characters (or fewer than [fewer]). */
    fun digits(s: String, most: Int): Boolean = s.isNotEmpty() && s.length <= most && s.all { it in '0'..'9' }

    /** A page's `&job=`: none, or the job the queue has by it (null for one it hasn't); [NOT_AN_ADDRESS] for one
     * that is no number of fewer than twelve digits. */
    fun job(asked: String?, jobOf: (Int) -> Job?): Job? {
        if (asked == null) return null
        if (!digits(asked, 11)) throw NOT_AN_ADDRESS
        return asked.toIntOrNull()?.let(jobOf)
    }

    /** library.songs_in_folder: the songs whose folder (library.song_folder) is [folder], newest first; only a folder
     * of two names (artist, title) is a song's. */
    fun songsInFolder(db: Db, folder: List<String>): List<SongRow> {
        if (folder.size != 2) return emptyList()
        return Songs.list(db).filter { SafeName.songFolder(it.artist, it.title).toList() == folder }
    }

    /** render.written_file: whether the phone recorded writing the file [name] in the song's folder. */
    fun written(db: Db, songId: Long, name: String): Boolean = WrittenPages.written(db, songId, name) != null

    /** library.read_regular of a kept file: its bytes, never through a symbolic link in its place, or null for
     * anything but a regular file (or one that can't be read). */
    fun readRegular(file: File): ByteArray? {
        val path = file.toPath()
        val attrs = try {
            Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        } catch (_: NoSuchFileException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (!attrs.isRegularFile) return null
        return try {
            Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (_: IOException) {
            null
        }
    }

    /** The last line a failed job said that isn't blank: the first command's that said one, its last such line
     * (versions_routes' and harmonica_routes' `last`). */
    fun lastLine(job: Job): String =
        job.steps.firstNotNullOfOrNull { step -> step.output.lastOrNull { PyText.strip(it).isNotEmpty() } } ?: ""

    /** `format(x, "g")`: six significant digits, correctly rounded, trailing zeros dropped; an exponent below -4
     * or from 6 on written as `1e+06`. */
    fun g(x: Double): String {
        if (x.isNaN()) return "nan"
        if (x.isInfinite()) return if (x > 0) "inf" else "-inf"
        if (x == 0.0) return if (1.0 / x < 0) "-0" else "0"
        val rounded = BigDecimal(x).round(MathContext(6, RoundingMode.HALF_EVEN))
        val exponent = rounded.precision() - rounded.scale() - 1
        return if (exponent < -4 || exponent >= 6) {
            val digits = rounded.unscaledValue().abs().toString().trimEnd('0').ifEmpty { "0" }
            val mantissa = if (digits.length > 1) "${digits[0]}.${digits.substring(1)}" else digits
            val sign = if (rounded.signum() < 0) "-" else ""
            "$sign${mantissa}e${if (exponent < 0) "-" else "+"}${Math.abs(exponent).toString().padStart(2, '0')}"
        } else {
            rounded.stripTrailingZeros().toPlainString()
        }
    }
}
