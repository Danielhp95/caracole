package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * A sheet's versions chosen on the phone (web/versions_routes.py; lane versions-harmonica): its page, reached from the
 * sandboxed viewer by a plain GET, and its forms, each a job under the song's key. Neutral: each refused as not on
 * the phone yet, as Stubs refused them.
 */
class VersionsRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/versions", "Choosing a sheet's version: not on the phone yet",
              get = GetAnswer { notYet("Choosing a sheet's version") }),
        Route("POST", "/versions/choose", "Choosing a sheet's version: not on the phone yet", page = "the version's page",
              post = PostAnswer { _, _ -> notYet("Choosing a sheet's version") }),
        Route("POST", "/versions/keep", "Keeping a sheet's version: not on the phone yet", page = "the version's page",
              post = PostAnswer { _, _ -> notYet("Keeping a sheet's version") }),
        Route("POST", "/versions/clear", "Going back to caracole's version: not on the phone yet",
              page = "the version's page", post = PostAnswer { _, _ -> notYet("Going back to caracole's version") }),
    )
}
