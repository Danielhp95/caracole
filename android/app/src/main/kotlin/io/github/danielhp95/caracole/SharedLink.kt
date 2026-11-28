package io.github.danielhp95.caracole

import java.net.URI
import java.net.URISyntaxException
import java.net.URLEncoder

/**
 * A song's link shared to the app as text (ShareLinkActivity): the page of the phone's server that shows it (the
 * server's `/share`, ShareRoutes', which reads the song it names and offers Fetch), handed to the library screen as
 * [PAGE], and the line [TAG] logs of what the app sent, for the owner to read what each music app sends.
 */
internal object SharedLink {
    /** logcat's tag for every share's raw extras: `adb logcat -s caracole-share`. */
    const val TAG = "caracole-share"

    /** The intent's extra that hands the library screen the page to show (a share's alone). */
    const val PAGE = "io.github.danielhp95.caracole.PAGE"

    /** The share page's path on the phone's server, and its Cancel's. */
    private const val SHARE = "/share"
    private const val CANCEL = "/share/cancel"

    /** The page of an audio file shared to the app (ShareRoutes' `/share/audio`, ShareActivity's). */
    private const val AUDIO = "/share/audio"

    /** The page of the audio file staged as [upload]. */
    fun audioPage(upload: String): String = "$AUDIO?upload=${encode(upload)}"

    /** The page of an audio file [name] where none was staged (the phone makes no sheet here: the page says why). */
    fun audioPageOf(name: String): String = "$AUDIO?name=${encode(name)}"

    /** The share page of what an app sent: EXTRA_TEXT, EXTRA_SUBJECT, EXTRA_TITLE and the sender's package, each
     * left out when there is none. */
    fun page(text: String?, subject: String?, title: String?, from: String?): String {
        val fields = listOf("text" to text, "subject" to subject, "extra_title" to title, "from" to from)
            .filter { !it.second.isNullOrEmpty() }
        if (fields.isEmpty()) return SHARE
        return SHARE + "?" + fields.joinToString("&") { (name, value) -> name + "=" + encode(value!!) }
    }

    /** [page] when it is a share's page, a song's or an audio file's (the one page the library screen takes from an
     * intent), else null. */
    fun shown(page: String?): String? =
        page?.takeIf { it == SHARE || it.startsWith("$SHARE?") || it == AUDIO || it.startsWith("$AUDIO?") }

    /** Whether [url], a link followed in the WebView, is the share page's Cancel at the phone's server ([origin]). */
    fun isCancel(url: String, origin: String?): Boolean = origin != null && pathAt(url, origin) == CANCEL

    /** Whether [url] is a share page of the phone's server at [origin]. */
    fun isSharePage(url: String?, origin: String?): Boolean =
        url != null && origin != null && pathAt(url, origin).let { it == SHARE || it == AUDIO }

    /** What logcat says of a share: every extra as it came, quoted (null: none), and the sender. */
    fun said(text: String?, subject: String?, title: String?, from: String?, type: String?): String =
        "from=${from ?: "?"} type=${type ?: "?"} text=${quoted(text)} subject=${quoted(subject)} title=${quoted(title)}"

    private fun quoted(s: String?): String =
        if (s == null) "null" else "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\""

    private fun encode(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    /** [url]'s path at [origin] (scheme, host and port the same), else null. */
    private fun pathAt(url: String, origin: String): String? = try {
        val u = URI(url)
        val o = URI(origin)
        if (u.scheme == o.scheme && u.host == o.host && u.port == o.port) u.path else null
    } catch (e: URISyntaxException) {
        null
    }
}
