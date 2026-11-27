package io.github.danielhp95.caracole.server.routes.share

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response

/**
 * What the page of an audio file shared to the app shows ([AudioSharePage]): the staged upload's id ([upload], null
 * where none was staged), its [name], [format] and length ([length], "3:18"), the names its tags or its name give
 * ([artist], [title]: the guess, editable), the library's song of them ([song], its display, and [sheet]: what it
 * holds now, [SHEET_SITES], [SHEET_AUTO] or [SHEET_NONE]), whether its auto sheet has words heard on the computer
 * ([heard]: a transcript's, which a sheet made here can't have), and why no sheet can be made here ([why], the
 * refusal's words whole), or why there is no upload to make it of ([gone]).
 */
internal data class AudioShareView(
    val upload: String?, val name: String, val format: String = "", val length: String = "",
    val artist: String = "", val title: String = "", val song: String? = null, val sheet: String = SHEET_NONE,
    val heard: Boolean = false, val why: String? = null, val gone: String? = null,
) {
    companion object {
        const val SHEET_SITES = "sites"
        const val SHEET_AUTO = "auto"
        const val SHEET_NONE = "none"
    }
}

/**
 * The page of an audio file shared to the app (ShareRoutes' `GET /share/audio?upload=ID`; the chords-on-the-phone
 * design's §8.2), in the message page's frame, style and policy (no script, its style by its hash, forms to the server
 * alone): the file ("song.mp3 · MP3 · 3:18"), Artist and Title filled with the guess, the library's song of it and
 * its sheet's state, the note where its sheet has words heard on the computer, and Make sheet (`POST /audio`, the
 * library page's own route, with the form token: its answer the Journal) and Cancel ([CANCEL], with the form token:
 * the upload dropped, then the share left); or why no sheet is made here, which names Settings, and Cancel.
 */
internal object AudioSharePage {
    const val PATH = "/share/audio"
    const val CANCEL = "/share/audio/cancel"

    /** §8.2's words where the song's sheet has words heard on the computer. */
    const val HEARD = "Its sheet now has words heard on the computer. A sheet made here has words only where a " +
        "lyrics site has them."

    private const val TITLE = "Sheet from an audio file"

    fun page(view: AudioShareView, csrf: String, name: LibraryName, status: Int = 200): Response {
        val html = MessagePage.html(TITLE, "<div class=\"pick-page\">\n${body(view, csrf)}</div>", name)
        return Response(status, Body.Bytes(html.toByteArray(Charsets.UTF_8)),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to MessagePage.csp))
    }

    private fun body(v: AudioShareView, csrf: String): String = buildString {
        append("<p class=\"lede\">${file(v)}</p>\n")
        val upload = v.upload
        when {
            v.why != null -> append("<p class=\"message\">${esc(v.why)}</p>\n")
            v.gone != null -> append("<p class=\"message\">${esc(v.gone)}</p>\n")
            upload != null -> append(make(v, upload, csrf))
        }
        if (upload != null && v.why == null && v.gone == null) {
            append("<form class=\"confirm\" method=\"post\" action=\"$CANCEL\">")
            append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">")
            append("<input type=\"hidden\" name=\"upload\" value=\"${esc(upload)}\">")
            append("<button class=\"btn\" type=\"submit\">Cancel</button></form>\n")
        } else {
            append("<p class=\"confirm\"><a class=\"btn\" href=\"${SharePage.CANCEL}\">Cancel</a></p>\n")
        }
    }

    /** "song.mp3 · MP3 · 3:18": what is known of the file. */
    private fun file(v: AudioShareView): String =
        listOf("<strong>${esc(v.name)}</strong>", esc(v.format), esc(v.length)).filter { it.isNotEmpty() }
            .joinToString(" · ")

    /** The names, the library's song, and Make sheet: `POST /audio` with the upload and the names as typed. */
    private fun make(v: AudioShareView, upload: String, csrf: String): String = buildString {
        append("<form class=\"pick-form\" method=\"post\" action=\"/audio\">\n")
        append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">\n")
        append("<input type=\"hidden\" name=\"upload\" value=\"${esc(upload)}\">\n")
        append("<label class=\"f\">Artist <input name=\"artist\" value=\"${esc(v.artist)}\" required autocomplete=\"off\" " +
                   "autocapitalize=\"words\"></label>\n")
        append("<label class=\"f\">Title <input name=\"title\" value=\"${esc(v.title)}\" required autocomplete=\"off\" " +
                   "autocapitalize=\"sentences\"></label>\n")
        v.song?.let { song ->
            val state = when (v.sheet) {
                AudioShareView.SHEET_SITES -> "it has a sheet from the sites: a sheet from an audio file is for a song " +
                    "with none"
                AudioShareView.SHEET_AUTO -> "its auto sheet is made again from this file"
                else -> "no sheet yet"
            }
            append("<p class=\"message\">In your library: <strong>${esc(song)}</strong> · ${esc(state)}.</p>\n")
        }
        if (v.heard) append("<p class=\"message\">${esc(HEARD)}</p>\n")
        append("<p class=\"confirm\"><button class=\"btn primary\" type=\"submit\">Make sheet</button></p>\n")
        append("</form>\n")
    }

    private fun esc(s: String): String = PyText.escape(s)
}
