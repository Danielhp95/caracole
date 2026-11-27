package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/** What a route not on the phone yet answers: the message page, 409, "…: not on the phone yet." (a neutral route
 * module's until its lane lands, and every stub's). */
fun notYet(what: String): Nothing = throw Refused(409, "Not on the phone yet", "$what: not on the phone yet.")

/**
 * The routes of caracole serve the phone answers with no module of its own: `GET /lookup`, the computer's lookup page,
 * whose work the library page's search does on the phone, for good, and `POST /youtube/search`, YouTube's first video
 * for a search, until the phone suggests one (the phone-YouTube plan's Y4.1): each the message page, 409, "…: not on
 * the phone yet.", once a form's own checks pass, which the library page says on the line. A sheet from a video
 * pasted and the pasted video's panel are YouTubeRoutes'. Every other route a lane will answer is its module's,
 * neutral until then, and a stub answers only where no module does (App).
 */
class Stubs : RouteModule {
    override val routes: List<Route> = buildList {
        for ((path, what) in PAGES) {
            add(Route("GET", path, "$what: not on the phone yet", get = GetAnswer { notYet(what) }))
        }
        for ((path, what, page) in FORMS) {
            add(Route("POST", path, "$what: not on the phone yet", page = page, post = PostAnswer { _, _ -> notYet(what) }))
        }
    }

    private companion object {
        /** The pages caracole serve writes itself that the phone has none of. */
        val PAGES = listOf(
            "/lookup" to "The lookup page",
        )

        /** The forms the phone answers none of yet, and the page each comes from (its refusals'). */
        val FORMS = listOf(
            Triple("/youtube/search", "YouTube's search", "the library"),
        )
    }
}
