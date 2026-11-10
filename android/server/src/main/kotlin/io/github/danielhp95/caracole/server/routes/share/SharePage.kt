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
 * ([others]), a note on what the phone could search ([note]), and the Edit form's fields ([artist], [title]).
 */
internal data class ShareView(
    val app: String?, val sent: List<Pair<String, String>>, val said: String?, val names: Pair<String, String>?,
    val link: String?, val typed: Boolean, val best: SongLine?, val others: List<SongLine>, val note: String?,
    val artist: String, val title: String, val read: ShareLinks.Read? = null,
)

/**
 * The page of a song shared to the app (ShareRoutes' `GET /share`), in the message page's frame, style and policy (no
 * script, its style by its hash, forms to the server alone): what caracole read, the best match and its sites, and
 * the owner's choices, each a plain form or link: Get it (POST /lookup, the library page's own, with the form token),
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
        if (v.sent.isNotEmpty() || v.read is ShareLinks.Read.Named) append(sent(v))
        val best = v.best
        if (best != null) {
            append("<h2 class=\"sub\">The best match</h2>\n<ul class=\"readings\">\n")
            append(line(best, csrf, primary = true))
            append("</ul>\n")
        }
        if (v.others.isNotEmpty()) {
            append("<h2 class=\"sub\">${if (best == null) "No sure match: maybe one of these" else "Or one of these"}</h2>\n")
            append("<ul class=\"readings\">\n")
            for (other in v.others) append(line(other, csrf, primary = false))
            append("</ul>\n")
        }
        if (best == null && v.names != null) append(byName(v.names, csrf, found = v.others.isNotEmpty()))
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
            v.names != null && v.typed -> "caracole searched for <strong>${esc(dashed(v.names))}</strong>."
            asked is ShareLinks.Read.Named && v.names != null ->
                "Read from ${esc(asked.service.source)}: <strong>${esc(dashed(v.names))}</strong>."
            asked is ShareLinks.Read.Named -> "Read from ${esc(asked.service.source)}: <strong>“${esc(v.said.orEmpty())}”" +
                "</strong>, but caracole can't tell who its artist is: edit the names if they're wrong."
            asked is ShareLinks.Read.NoSong -> "$sender shared a link that names no song ($link): ${esc(asked.why)}. Type " +
                "the artist and the title."
            asked is ShareLinks.Read.NotRead -> "$sender shared a link alone ($link), and caracole couldn't read it: " +
                "${esc(asked.why)}. Type the artist and the title, or share it again later."
            v.names != null -> "caracole read <strong>${esc(dashed(v.names))}</strong>."
            v.said != null && v.typed -> "caracole searched for <strong>“${esc(v.said)}”</strong>, but can't tell " +
                "who its artist is: type both names."
            v.said != null -> "caracole read <strong>“${esc(v.said)}”</strong>, but can't tell who its artist is: " +
                "edit the names if they're wrong."
            v.link != null -> "$sender shared a link alone, which names no song: <code>${esc(v.link)}</code>. caracole " +
                "doesn't ask ${esc(v.app ?: "the app")} what it is: type the artist and the title."
            v.typed -> "Type the artist and the title."
            else -> "Nothing that was shared names a song: type the artist and the title."
        }
        return "<p class=\"lede\">$text</p>\n"
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

    /** One song: its names, what each site has of it, yours or not, its Get it and, for yours, its Open. */
    private fun line(l: SongLine, csrf: String, primary: Boolean): String = buildString {
        append("<li class=\"reading${if (primary) " now" else ""}\">")
        append("<span class=\"said\">${esc(l.display)}</span>")
        val facts = l.facts()
        if (facts.isNotEmpty()) append(" <span class=\"choice-why\">${esc(facts.joinToString(" · "))}</span>")
        if (l.songId != null) append(" <span class=\"says ${if (l.held) "ready" else "waiting"}\">In your library</span>")
        append(" <div class=\"confirm\">")
        val open = l.open()
        // Your song with a sheet opens first; any other's Get it is the line's main button.
        append(getIt(l.pick(), if (l.songId != null) "Get it again" else "Get it", primary && !(open != null && l.held),
                     l.display, csrf))
        if (open != null) {
            append(" <a class=\"btn${if (primary && l.held) " primary" else ""}\" href=\"${esc(open)}\" " +
                       "aria-label=\"Open ${esc(l.display)}\">Open</a>")
        }
        append("</div></li>\n")
    }

    /** No line is the song read: Get it by its names, which the lookup matches on the sites. */
    private fun byName(names: Pair<String, String>, csrf: String, found: Boolean): String {
        val said = if (found) "None of them? Get it looks up" else "The phone's indexes have no such song. Get it looks up"
        return "<p class=\"message\">$said <strong>${esc(dashed(names))}</strong> on the sites all the same, at a " +
            "lookup's pace.</p>\n<div class=\"confirm\">" +
            getIt(listOf("artist" to names.first, "title" to names.second), "Get it", !found, dashed(names), csrf) +
            "</div>\n"
    }

    /** Get it: POST /lookup, the library page's, its fields hidden, the form token first. */
    private fun getIt(fields: List<Pair<String, String>>, label: String, primary: Boolean, display: String,
                      csrf: String): String = buildString {
        append("<form class=\"pick-form\" method=\"post\" action=\"/lookup\">")
        append("<input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">")
        for ((name, value) in fields) append("<input type=\"hidden\" name=\"${esc(name)}\" value=\"${esc(value)}\">")
        append("<button class=\"btn${if (primary) " primary" else ""}\" type=\"submit\" " +
                   "aria-label=\"${esc(if (label == "Get it again") "Get $display again" else "Get $display")}\">")
        append("${esc(label)}</button></form>")
    }

    /** Edit: the names as read, typed again, searched again (`GET /share`); open when there are none to search. */
    private fun edit(v: ShareView): String = buildString {
        append("<details class=\"picker\"${if (v.names == null) " open" else ""}><summary class=\"btn\">Edit</summary>\n")
        append("<form class=\"pick-form\" method=\"get\" action=\"/share\">\n")
        v.app?.let { append("<input type=\"hidden\" name=\"app\" value=\"${esc(it)}\">\n") }
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
