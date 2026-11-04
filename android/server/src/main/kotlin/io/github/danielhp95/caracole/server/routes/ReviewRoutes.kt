package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * An uncertain match reviewed on the phone (web/review_routes.py; lane review): the picker, and its answer, the
 * review runner's job. Neutral: each refused as not on the phone yet, as Stubs refused them.
 */
class ReviewRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/review", "$WHAT: not on the phone yet", get = GetAnswer { notYet(WHAT) }),
        Route("POST", "/review", "$WHAT: not on the phone yet", post = PostAnswer { _, _ -> notYet(WHAT) }),
    )

    private companion object {
        const val WHAT = "Picking a song's match"
    }
}
