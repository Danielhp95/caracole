package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/** GET /, /index.html and /favicon.ico (lane library-page; until then, a page that says so). */
class PageRoutes(val database: Database, val page: LibraryPage, val data: PageData, val controls: () -> ServerControls) :
    RouteModule {
    override val routes: List<Route> = listOf("/", "/index.html", "/favicon.ico").map { path ->
        Route("GET", path, "the library page", get = GetAnswer { stub("lane library-page") { notBuilt() } })
    }

    private fun notBuilt(): Response = Response(
        409,
        Body.Bytes("<!doctype html>\n<meta charset=\"utf-8\"><title>caracole</title><p>Not built yet.</p>\n".toByteArray()),
        mutableListOf("Content-Type" to "text/html; charset=utf-8"),
    )
}
