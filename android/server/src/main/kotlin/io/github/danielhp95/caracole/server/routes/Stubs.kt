package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/** What a route not on the phone yet answers: the message page, 409, "…: not on the phone yet." (a neutral route
 * module's until its lane lands, and every stub's). */
fun notYet(what: String): Nothing = throw Refused(409, "Not on the phone yet", "$what: not on the phone yet.")

/**
 * The route of caracole serve the phone answers with no module of its own: `GET /lookup`, the computer's lookup page,
 * whose work the library page's search does on the phone, for good: the message page, 409, "…: not on the phone yet."
 * YouTube's routes (a sheet from a video, a pasted video's panel, a search's suggested video) are YouTubeRoutes'.
 * Every other route a lane will answer is its module's, neutral until then, and a stub answers only where no module
 * does (App).
 */
class Stubs : RouteModule {
    override val routes: List<Route> = buildList {
        for ((path, what) in PAGES) {
            add(Route("GET", path, "$what: not on the phone yet", get = GetAnswer { notYet(what) }))
        }
    }

    private companion object {
        /** The pages caracole serve writes itself that the phone has none of. */
        val PAGES = listOf(
            "/lookup" to "The lookup page",
        )
    }
}
