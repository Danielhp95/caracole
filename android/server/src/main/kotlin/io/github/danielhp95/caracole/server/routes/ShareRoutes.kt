package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.share.SharedText
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.routes.search.Looked
import io.github.danielhp95.caracole.server.routes.search.SearchQuery
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
 *     GET /share/cancel                              Cancel: the library page (303); the app leaves the share instead
 *
 * Nothing is asked of any site, nor of the music app: the names come of the text alone (SharedText, then
 * SongNames.readNames, the one parser of a free text), and the search is /api/search's (SearchRoutes.answer: your
 * library and the offline indexes). The page ([SharePage]) offers the best match, its sites and your song when the
 * library has it, and Get it posts the library page's own `POST /lookup`, the one that asks the sites, at a lookup's
 * pace, once the owner taps it.
 */
class ShareRoutes(private val database: Database, private val search: SearchRoutes, private val csrf: String,
                  private val libraryName: () -> String = { "" }) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/share", "a song shared to the app (text, subject, extra_title, from; or artist, title, app): " +
                  "what it names, searched in your library and the offline indexes, and Get it", get = GetAnswer {
            SharePage.page(view(PyUrl.query(it.target)), csrf, LibraryName.phone(libraryName()))
        }),
        Route("GET", SharePage.CANCEL, "the share left: the library page",
              get = GetAnswer { Response(303, Body.Empty, mutableListOf("Location" to "/")) }),
    )

    /**
     * What the page shows of what was shared ([SharedText.read], then read_names), or of the names typed: both, never
     * read, as `caracole get ARTIST TITLE` takes them; one alone, read as every page reads one text.
     */
    internal fun view(asked: Map<String, String>): ShareView {
        val typed = "artist" in asked || "title" in asked
        val songs = database.read { db -> Songs.list(db) }
        val artist = field(asked, "artist")
        val title = field(asked, "title")
        val app: String?
        val sent: List<Pair<String, String>>
        val said: String?
        val link: String?
        if (typed) {
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
        }
        val names = when {
            typed && artist.isNotEmpty() && title.isNotEmpty() -> artist to title
            said != null -> database.read { db -> SongNames.readNames(db, said, songs) }
            else -> null
        }
        // The names read, else the text as read_names cleans it (a video's words gone), as the search box would take it.
        val q = SearchQuery.of(names?.let { "${it.first} ${it.second}" } ?: said?.let { SongNames.clean(it).ifEmpty { it } }.orEmpty())
        val answer = if (SearchQuery.short(q)) null else search.answer(q)
        val lines = answer?.let { SongLine.of(it) }.orEmpty()
        val best = answer?.let { SongLine.best(it, lines, names) }
        val ugEmpty = (answer?.get("hint") as? JsonPrimitive)?.content == Looked.UG_EMPTY
        return ShareView(
            app = app, sent = sent, said = said, names = names, link = link, typed = typed, best = best,
            others = lines.filter { it !== best }.take(OTHERS), note = if (ugEmpty) NO_INDEX else null,
            artist = names?.first ?: artist, title = names?.second ?: if (typed) title else said.orEmpty(),
        )
    }

    /** A field of the address, stripped and cut at [LIMIT] code points; "" for none. */
    private fun field(asked: Map<String, String>, name: String): String = Py.slice(Py.strip(asked[name].orEmpty()), 0, LIMIT)

    private companion object {
        /** The other songs the page offers beside the best. */
        const val OTHERS = 3

        /** The code points of a field read (a share's text is a line or two). */
        const val LIMIT = 2000

        /** The search's answer with no Ultimate Guitar index (Looked.UG_EMPTY, the computer's words), the phone's. */
        const val NO_INDEX = "The phone has no Ultimate Guitar index yet: Settings › Import indexes brings the " +
            "computer's, so that a search finds the sites' songs."
    }
}
