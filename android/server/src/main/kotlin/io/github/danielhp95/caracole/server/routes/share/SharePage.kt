package io.github.danielhp95.caracole.server.routes.share

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.share.ShareLinks
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response

/**
 * What the page of a song shared to the app shows ([SharePage]): the app that shared it ([app], null for one caracole
 * doesn't know), what it sent ([sent], each extra's text, for the owner to see), the text that names the song
 * ([said]), the names read from it ([names], read_names'; null when they can't be), the link alone ([link]) when it
 * names none, whether the names were typed ([typed], Edit's), what the link's service said of it ([read], asked once:
 * ShareLinks; null for a link of no service caracole asks, or none), the best match ([best]) and the others
 * ([others]), a note on what the phone could search ([note]), and the Edit form's fields ([artist], [title]); the
 * service of a link the page didn't ask by itself and the cache doesn't answer ([unread]: another site sent the page),
 * and the share's own fields ([fields]), which Read the link posts again; and, for a YouTube video shared ([video]:
 * its plain address, kept through Edit), whether its sheet may be made from it ([fromVideo]).
 */
internal data class ShareView(
    val app: String?, val sent: List<Pair<String, String>>, val said: String?, val names: Pair<String, String>?,
    val link: String?, val typed: Boolean, val best: SongLine?, val others: List<SongLine>, val note: String?,
    val artist: String, val title: String, val read: ShareLinks.Read? = null,
    val unread: ShareLinks.Service? = null, val fields: List<Pair<String, String>> = emptyList(),
    val video: String? = null, val fromVideo: FromVideo? = null,
)

/**
 * A sheet from the YouTube video shared (the phone-youtube design's §5.2): [why] null where this phone makes one for
 * the song named (YouTubeRoutes.whyNotFromVideo: the route ready, a song with no human sheet, not ignored, no audio of
 * its own), else the one hint the page says in its place; [first] where no site has the song's sheet, so that Make
 * its sheet from this video is the page's main button and Fetch comes second.
 */
internal data class FromVideo(val why: String?, val first: Boolean)

/**
 * The page of a song shared to the app (ShareRoutes' `GET /share`), in the message page's frame, style and policy (no
 * script, its style by its hash, forms to the server alone): what caracole read, the best match and its sites, and
 * the owner's choices, each a plain form or link: Read the link (POST /share, with the form token: a link the page
 * didn't ask its service of by itself), Fetch (POST /lookup, the library page's own, with the form token), Make its
 * sheet from this video for a YouTube video shared (POST /request with `youtube`, the library page's request form's
 * own, with the form token: nothing downloaded before the owner presses it),
 * Open (a song of yours), Edit (the names typed, `GET /share` again) and Cancel (`/share/cancel`, which the app takes
 * as leaving the share).
 */
internal object SharePage {
    const val CANCEL = "/share/cancel"

    fun page(view: ShareView, csrf: String, name: LibraryName): Response {
        val title = view.app?.let { "Shared from $it" } ?: "A shared song"
        val html = MessagePage.html(title, "<div class=\"pick-page\">\n${body(view, csrf)}</div>", name)
        return Response(200, Body.Bytes(html.toByteArray(Charsets.UTF_8)),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to MessagePage.csp))
    }

    private fun body(v: ShareView, csrf: String): String = buildString {
        append(read(v))
        v.unread?.let { append(readTheLink(v, it, csrf)) }
        if (v.sent.isNotEmpty() || v.read is ShareLinks.Read.Named) append(sent(v))
        val video = v.fromVideo
        val first = video?.first == true && video.why == null  // the main button: Fetch's no longer
        if (video?.first == true) append(fromVideo(v, video, csrf))
        val best = v.best
        if (best != null) {
            append("<h2 class=\"sub\">Best match</h2>\n<ul class=\"readings\">\n")
            append(line(best, csrf, primary = !first))
            append("</ul>\n")
        }
        if (v.others.isNotEmpty()) {
            append("<h2 class=\"sub\">${if (best == null) "No sure match. Maybe one of these" else "Or one of these"}</h2>\n")
            append("<ul class=\"readings\">\n")
            for (other in v.others) append(line(other, csrf, primary = false))
            append("</ul>\n")
        }
        if (best == null && v.names != null) append(byName(v.names, csrf, found = v.others.isNotEmpty(), primary = !first))
        if (video != null && !video.first) append(fromVideo(v, video, csrf))
        v.note?.let { append("<p class=\"message\">${esc(it)}</p>\n") }
        append(edit(v))
        append("<p class=\"confirm\"><a class=\"btn\" href=\"$CANCEL\">Cancel</a></p>\n")
    }

    /** What caracole read, or why it read nothing: from the text, or from the link's service, asked once. */
    private fun read(v: ShareView): String {
        val sender = v.app ?: "The app"
        val asked = v.read
        val link = v.link?.let { "<code>${esc(it)}</code>" }.orEmpty()
        val text = when {
            v.names != null && v.typed -> "We searched for <strong>${esc(dashed(v.names))}</strong>."
            asked is ShareLinks.Read.Named && v.names != null ->
                "Read from ${esc(asked.service.source)}: <strong>${esc(dashed(v.names))}</strong>."
            asked is ShareLinks.Read.Named -> "Read from ${esc(asked.service.source)}: <strong>“${esc(v.said.orEmpty())}”" +
                "</strong>, but caracole can't tell who its artist is: edit the names if they're wrong."
            asked is ShareLinks.Read.NoSong -> "$sender shared a link that names no song ($link): ${esc(asked.why)}. Type " +
                "the artist and the title."
            asked is ShareLinks.Read.NotRead -> "$sender shared a link alone ($link), and caracole couldn't read it: " +
                "${esc(asked.why)}. Type the artist and the title, or share it again later."
            v.unread != null -> "$sender shared a link alone ($link). We can read the song it names from " +
                "${esc(v.unread.source)}: one request to ${esc(v.unread.name)}."
            v.names != null -> "We read <strong>${esc(dashed(v.names))}</strong>."
            v.said != null && v.typed -> "We searched for <strong>“${esc(v.said)}”</strong> but can't tell the " +
                "artist. Type both names."
            v.said != null -> "We read <strong>“${esc(v.said)}”</strong> but can't tell the artist. Edit the names " +
                "if wrong."
            v.link != null -> "$sender shared a bare link, no song named: <code>${esc(v.link)}</code>. We don't " +
                "ask ${esc(v.app ?: "the app")}. Type the artist and title."
            v.typed -> "Type the artist and title."
            else -> "Nothing shared names a song. Type the artist and title."
        }
        return "<p class=\"lede\">$text</p>\n"
    }

    /** Read the link: the share posted again with the form token (POST /share), which asks the link's service once. */
    private fun readTheLink(v: ShareView, service: ShareLinks.Service, csrf: String): String = buildString {
        append("<div class=\"confirm\"><form class=\"pick-form\" method=\"post\" action=\"/share\">")
        append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">")
        for ((name, value) in v.fields) append("<input type=\"hidden\" name=\"${esc(name)}\" value=\"${esc(value)}\">")
        append("<button class=\"btn primary\" type=\"submit\" aria-label=\"Read the link: ask ${esc(service.name)} " +
                   "once\">Read the link</button></form></div>\n")
    }

    /** What the app sent, folded: each extra as it came, and what the link's service said of it. */
    private fun sent(v: ShareView): String = buildString {
        append("<details class=\"picker\"><summary>What ${esc(v.app ?: "the app")} sent</summary>\n<ul class=\"plan\">\n")
        for ((what, text) in v.sent) append("<li>${esc(what)}: <code>${esc(text)}</code></li>\n")
        (v.read as? ShareLinks.Read.Named)?.let { named ->
            val source = named.service.source.replaceFirstChar { c -> if (c in 'a'..'z') c - 32 else c }
            val said = if (named.video) "${named.title}, by ${named.artist}" else "${named.artist} – ${named.title}"
            append("<li>${esc(source)}: <code>${esc(said)}</code></li>\n")
        }
        append("</ul>\n</details>\n")
    }

    /** One song: its names, what each site has of it, yours or not, its Fetch and, for yours, its Open. */
    private fun line(l: SongLine, csrf: String, primary: Boolean): String = buildString {
        append("<li class=\"reading${if (primary) " now" else ""}\">")
        append("<span class=\"said\">${esc(l.display)}</span>")
        val facts = l.facts()
        if (facts.isNotEmpty()) append(" <span class=\"choice-why\">${esc(facts.joinToString(" · "))}</span>")
        if (l.songId != null) append(" <span class=\"says ${if (l.held) "ready" else "waiting"}\">In your logbook</span>")
        append(" <div class=\"confirm\">")
        val open = l.open()
        // Your song with a sheet opens first; any other's Fetch is the line's main button.
        append(getIt(l.pick(), if (l.songId != null) "Fetch again" else "Fetch", primary && !(open != null && l.held),
                     l.display, csrf))
        if (open != null) {
            append(" <a class=\"btn${if (primary && l.held) " primary" else ""}\" href=\"${esc(open)}\" " +
                       "aria-label=\"Open ${esc(l.display)}\">Open</a>")
        }
        append("</div></li>\n")
    }

    /** Make its sheet from this video: POST /request with `youtube`, as the library page's request form posts it
     * (the names read, or typed through Edit), the form token first; else its one hint, in the route's words. */
    private fun fromVideo(v: ShareView, video: FromVideo, csrf: String): String = buildString {
        video.why?.let { return "<p class=\"message\">${esc(it)}</p>\n" }
        val names = v.names ?: return ""
        append("<div class=\"confirm\"><form class=\"pick-form\" method=\"post\" action=\"/request\">")
        append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">")
        for ((name, value) in listOf("artist" to names.first, "title" to names.second, "youtube" to v.video.orEmpty())) {
            append("<input type=\"hidden\" name=\"$name\" value=\"${esc(value)}\">")
        }
        append("<button class=\"btn${if (video.first) " primary" else ""}\" type=\"submit\" aria-label=\"Make the sheet " +
                   "of ${esc(names.second)} by ${esc(names.first)} from this video\">$MAKE</button></form></div>\n")
    }

    /** The design's §5.2: the share page's button for a YouTube video. */
    const val MAKE = "Make its sheet from this video"

    /** No line is the song read: Fetch by its names, which the lookup matches on the sites. */
    private fun byName(names: Pair<String, String>, csrf: String, found: Boolean, primary: Boolean = true): String {
        val said = if (found) "None of them? Fetch looks up" else "Not in the phone's indexes. Fetch looks up"
        return "<p class=\"message\">$said <strong>${esc(dashed(names))}</strong> on the sites anyway.</p>\n" +
            "<div class=\"confirm\">" +
            getIt(listOf("artist" to names.first, "title" to names.second), "Fetch", !found && primary, dashed(names), csrf) +
            "</div>\n"
    }

    /** Fetch: POST /lookup, the library page's, its fields hidden, the form token first. */
    private fun getIt(fields: List<Pair<String, String>>, label: String, primary: Boolean, display: String,
                      csrf: String): String = buildString {
        append("<form class=\"pick-form\" method=\"post\" action=\"/lookup\">")
        append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">")
        for ((name, value) in fields) append("<input type=\"hidden\" name=\"${esc(name)}\" value=\"${esc(value)}\">")
        append("<button class=\"btn${if (primary) " primary" else ""}\" type=\"submit\" " +
                   "aria-label=\"${esc(if (label == "Fetch again") "Fetch $display again" else "Fetch $display")}\">")
        append("${esc(label)}</button></form>")
    }

    /** Edit: the names as read, typed again, searched again (`GET /share`); open when there are none to search. */
    private fun edit(v: ShareView): String = buildString {
        append("<details class=\"picker\"${if (v.names == null) " open" else ""}><summary class=\"btn\">Edit</summary>\n")
        append("<form class=\"pick-form\" method=\"get\" action=\"/share\">\n")
        v.app?.let { append("<input type=\"hidden\" name=\"app\" value=\"${esc(it)}\">\n") }
        v.video?.let { append("<input type=\"hidden\" name=\"youtube\" value=\"${esc(it)}\">\n") }
        append("<label class=\"f\">Artist <input name=\"artist\" value=\"${esc(v.artist)}\" autocomplete=\"off\" " +
                   "autocapitalize=\"words\"></label>\n")
        append("<label class=\"f\">Title <input name=\"title\" value=\"${esc(v.title)}\" autocomplete=\"off\" " +
                   "autocapitalize=\"sentences\"></label>\n")
        append("<p class=\"confirm\"><button class=\"btn primary\" type=\"submit\">Search again</button></p>\n")
        append("</form>\n</details>\n")
    }

    /** "Artist – Title", as the owner reads a song's names. */
    fun dashed(names: Pair<String, String>): String = "${names.first} – ${names.second}"

    private fun esc(s: String): String = PyText.escape(s)
}
