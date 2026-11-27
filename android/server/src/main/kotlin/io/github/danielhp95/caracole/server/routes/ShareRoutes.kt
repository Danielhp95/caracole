package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.share.ShareLinks
import io.github.danielhp95.caracole.core.share.SharedText
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.routes.search.Looked
import io.github.danielhp95.caracole.server.routes.search.SearchQuery
import io.github.danielhp95.caracole.server.routes.share.FromVideo
import io.github.danielhp95.caracole.server.routes.share.SharePage
import io.github.danielhp95.caracole.server.routes.share.ShareView
import io.github.danielhp95.caracole.server.routes.share.SongLine
import kotlinx.serialization.json.JsonPrimitive

/**
 * A song shared to the app from a music app (the app's ShareLinkActivity: Android's share sheet, text alone), the
 * phone's own page, which caracole serve has none of:
 *
 *     GET /share?text=&subject=&extra_title=&from=   what the app sent (EXTRA_TEXT, EXTRA_SUBJECT, EXTRA_TITLE, the
 *                                                    sender's package): the song it names read (SharedText, then
 *                                                    read_names), searched as /api/search searches, and the menu
 *     GET /share?artist=&title=&app=                 the names typed (its Edit), searched again
 *     POST /share                                    Read the link: the share's fields again (text, subject,
 *                                                    extra_title, from) with the form token, its link's service asked
 *     GET /share/cancel                              Cancel: the library page (303); the app leaves the share instead
 *
 * The names come of the text (SharedText, then SongNames.readNames, the one parser of a free text), and the search
 * is /api/search's (SearchRoutes.answer: your library and the offline indexes). A text that names no song but a link
 * of Apple Music's, Spotify's, TIDAL's, YouTube's or YouTube Music's is read by asking its service once, the owner's
 * choice of 2026-11-10 ([links]: ShareLinks, ShareAsk, at a lookup's pace, inside one write as a lookup's runner
 * asks; its cached answer first, with no request and no write), and that page's names are read as the text's would
 * be. A GET asks the service by itself only when the browser says no other site sent it there (`Sec-Fetch-Site`
 * `none`, the app's own loadUrl of a share's page, or `same-origin`, a link of caracole's pages, [asks]); else (another
 * site's link or form, the header missing) the page shows what the cache alone says and, for a link it doesn't hold,
 * Read the link, a form that POSTs the share with the form token, so that no other page makes the phone ask a service
 * or write. Nothing is asked of a tab site: the page ([SharePage]) offers the best match, its sites and your song when the
 * library has it, and Fetch posts the library page's own `POST /lookup`, the one that asks the sites, at a lookup's
 * pace, once the owner taps it. A YouTube video shared ([youtube]: its link's id, kept through Edit as `youtube`)
 * offers Make its sheet from this video where this phone makes one for the song named (the phone-youtube design's
 * §5.2, YouTubeRoutes.whyNotFromVideo), first where no site has the song's sheet, else second to Fetch; it posts the
 * library page's own `POST /request` with `youtube` and the form token, which queues `youtube --sheet --url`: nothing
 * downloads before the owner presses it, and its names are Edit's to change first. Where none can be made, one hint
 * says why in its place. The video's names are still oEmbed's, the page's one request.
 */
class ShareRoutes(private val database: Database, private val search: SearchRoutes, private val csrf: String,
                  private val libraryName: () -> String = { "" }, private val links: LinkReader = LinkReader.NONE,
                  private val youtube: YouTubeRoutes? = null) :
    RouteModule {
    /** What a shared link's service says of it ([ShareLinks.Read]): what is known with no request (the service off,
     * the cache's answer), else, when [ask], the service asked once; null for none known and none asked. [NONE] asks
     * nothing (the link is read as no song's, with nothing said). */
    fun interface LinkReader {
        fun read(linked: ShareLinks.Linked, ask: Boolean): ShareLinks.Read?

        companion object {
            val NONE: LinkReader = LinkReader { _, _ -> null }
        }
    }

    override val routes: List<Route> = listOf(
        Route("GET", "/share", "a song shared to the app (text, subject, extra_title, from; or artist, title, app): " +
                  "what it names, searched in your library and the offline indexes, and Fetch", get = GetAnswer {
            SharePage.page(view(PyUrl.query(it.target), ask = asks(it)), csrf, LibraryName.phone(libraryName()))
        }),
        Route("POST", "/share", "Read the link: a link shared alone (text, subject, extra_title, from), its service " +
                  "asked once", page = "the share's page", post = PostAnswer { _, form ->
            SharePage.page(view(form.filterKeys { it in SHARED }, ask = true), csrf, LibraryName.phone(libraryName()))
        }),
        Route("GET", SharePage.CANCEL, "the share left: the library page",
              get = GetAnswer { Response(303, Body.Empty, mutableListOf("Location" to "/")) }),
    )

    /**
     * What the page shows of what was shared ([SharedText.read], then read_names), or of the names typed: both, never
     * read, as `caracole get ARTIST TITLE` takes them; one alone, read as every page reads one text.
     */
    internal fun view(asked: Map<String, String>, ask: Boolean = true): ShareView {
        val typed = "artist" in asked || "title" in asked
        val songs = database.read { db -> Songs.list(db) }
        val artist = field(asked, "artist")
        val title = field(asked, "title")
        val app: String?
        val sent: List<Pair<String, String>>
        var said: String?
        val link: String?
        val video: String?
        if (typed) {
            video = YouTubeRoutes.videoIdOf(field(asked, "youtube"))
            app = field(asked, "app").ifEmpty { null }
            sent = emptyList()
            said = listOf(artist, title).filter { it.isNotEmpty() }.joinToString(" ").ifEmpty { null }
            link = null
        } else {
            val text = field(asked, "text")
            val subject = field(asked, "subject")
            val extra = field(asked, "extra_title")
            val shared = SharedText.read(text, subject, extra, field(asked, "from"))
            app = shared.app
            sent = listOf("Text" to text, "Subject" to subject, "Title" to extra).filter { it.second.isNotEmpty() }
            said = shared.said
            link = shared.link
            video = link?.let(YouTubeRoutes::videoIdOf)
        }
        // A link alone of a service caracole may ask: its answer's names, as a text that said them would give them.
        val linked = if (typed || said != null) null else link?.let { ShareLinks.of(it) }
        val read = linked?.let { links.read(it, ask) }
        val named = read as? ShareLinks.Read.Named
        if (named != null) said = if (named.video) named.title else "${named.artist} - ${named.title}"
        val text = said
        val names = when {
            typed && artist.isNotEmpty() && title.isNotEmpty() -> artist to title
            named?.video == true -> database.read { db -> SongNames.readNames(db, named.title, songs, channel = named.artist) }
            text != null -> database.read { db -> SongNames.readNames(db, text, songs) }
            else -> null
        }
        // The names read, else the text as read_names cleans it (a video's words gone), as the search box would take it.
        val q = SearchQuery.of(names?.let { "${it.first} ${it.second}" } ?: text?.let { SongNames.clean(it).ifEmpty { it } }.orEmpty())
        val answer = if (SearchQuery.short(q)) null else search.answer(q)
        val lines = answer?.let { SongLine.of(it) }.orEmpty()
        val best = answer?.let { SongLine.best(it, lines, names) }
        val ugEmpty = (answer?.get("hint") as? JsonPrimitive)?.content == Looked.UG_EMPTY
        val unread = if (linked != null && read == null && !ask) linked.service else null
        // A video's sheet offered once its names are known (none while Read the link is still to be pressed).
        val fromVideo = if (video == null || youtube == null || unread != null) null else {
            FromVideo(youtube.whyNotFromVideo(names), first = best?.sheetOnSites() != true)
        }
        return ShareView(
            app = app, sent = sent, said = said, names = names, link = link, typed = typed, read = read, best = best,
            others = lines.filter { it !== best }.take(OTHERS), note = if (ugEmpty) NO_INDEX else null,
            artist = names?.first ?: artist, title = names?.second ?: if (typed) title else said.orEmpty(),
            unread = unread,
            fields = if (typed) emptyList() else SHARED.map { it to field(asked, it) }.filter { it.second.isNotEmpty() },
            video = video?.let { YouTubeData.read().watchUrl(it) }, fromVideo = fromVideo,
        )
    }

    /** A field of the address, stripped and cut at [LIMIT] code points; "" for none. */
    private fun field(asked: Map<String, String>, name: String): String = Py.slice(Py.strip(asked[name].orEmpty()), 0, LIMIT)

    companion object {
        /** Whether a GET of the share's page may ask a link's service by itself: the browser says no other site sent
         * it (`Sec-Fetch-Site` `none`, the app's own loadUrl, or `same-origin`, a link of caracole's pages). */
        fun asks(request: Request): Boolean = request.headers["sec-fetch-site"] in ASKING

        private val ASKING = setOf("none", "same-origin")

        /** The fields of a share as the app sends them (SharedLink.page), which Read the link posts again. */
        private val SHARED = listOf("text", "subject", "extra_title", "from")

        /** The other songs the page offers beside the best. */
        private const val OTHERS = 3

        /** The code points of a field read (a share's text is a line or two). */
        private const val LIMIT = 2000

        /** The search's answer with no Ultimate Guitar index (Looked.UG_EMPTY, the computer's words), the phone's. */
        private const val NO_INDEX = "No UG index on the phone yet. Settings › Import indexes brings the computer's."
    }
}
