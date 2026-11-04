package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * The library page's lookups on the phone (library_routes.py's `/fetch`, search_routes.py's LaCuerda and harptabs.com
 * reads, versions_routes.py's Keep more; lane lookup-routes, which moves `/lookup` and `/request` here from
 * LibraryRoutes). Neutral: each refused as not on the phone yet, as Stubs refused them.
 */
class LookupRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/fetch", "a song fetched now (song)",
              post = PostAnswer { _, _ -> notYet("Fetching a song now") }),
        Route("POST", "/lacuerda/artist", "a LaCuerda artist's page read (artist)", page = "the page",
              post = PostAnswer { _, _ -> notYet("Reading a LaCuerda artist's page") }),
        Route("POST", "/lacuerda/search", "LaCuerda's own search (q, auto)", page = "the page",
              post = PostAnswer { _, _ -> notYet("LaCuerda's own search") }),
        Route("POST", "/harptabs/artist", "a harptabs.com artist's page read (path)", page = "the page",
              post = PostAnswer { _, _ -> notYet("Reading a harptabs.com artist's page") }),
        Route("POST", "/versions/keep-more", "a song's UG versions kept, as many as a lookup may (song)",
              post = PostAnswer { _, _ -> notYet("Keeping more versions") }),
    )
}
