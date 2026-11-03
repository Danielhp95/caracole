package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * library_routes.py's pages on the phone:
 *
 *     GET  /             the library page, built for this request from [data] and the server's [controls]
 *     GET  /index.html   the same
 *     GET  /favicon.ico  the mark every page carries inline, for a browser that asks for it anyway
 *
 * The page's own policy is in its meta tag; its header's is `frame-ancestors 'none'` alone, as caracole serve's
 * (a header policy would apply on top of the tag's). The icon, an SVG, opened as a page of its own may load and run
 * nothing. Its data is read in one Database.read: a route never writes.
 */
class PageRoutes(val database: Database, val page: LibraryPage, val data: PageData, val controls: () -> ServerControls) :
    RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/", "the library page", get = GetAnswer { library() }),
        Route("GET", "/index.html", "the library page", get = GetAnswer { library() }),
        Route("GET", "/favicon.ico", "the page's mark, for a browser that asks for it", get = GetAnswer { icon() }),
    )

    /** The library page, as the phone serves it now. */
    fun library(): Response {
        val controls = controls()
        val now = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()
        val built = database.read { db -> data.data(db, now) }
        val html = page.served(page.withServer(built, controls), controls, LIBRARY_NAME)
        return Response(200, Body.Bytes(html.toByteArray()), mutableListOf("Content-Type" to HTML, "Content-Security-Policy" to FRAMES))
    }

    private fun icon(): Response = Response(
        200, Body.Bytes(PageIcons.svg.toByteArray()),
        mutableListOf("Content-Type" to "image/svg+xml", "Content-Security-Policy" to "default-src 'none'; $FRAMES"),
    )

    companion object {
        /** The library the phone's pages show (AppConfig's libraryName). */
        const val LIBRARY_NAME = "Phone"
        const val HTML = "text/html; charset=utf-8"

        /** web/app.py's FRAMES: no page may frame another. */
        const val FRAMES = "frame-ancestors 'none'"
    }
}
