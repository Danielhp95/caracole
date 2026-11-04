package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * The Requests tab on the phone (web/feed.py's `/requests.json`, jobs_routes.py's Try again; lane requests-feed).
 * Neutral: each refused as not on the phone yet.
 */
class RequestsRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/requests.json", "the Requests tab's requests, for the page's script (open)", scriptOnly = true,
              get = GetAnswer { notYet("The Requests tab") }),
        Route("POST", "/jobs/again", "a request over queued again (job)",
              post = PostAnswer { _, _ -> notYet("Trying a request again") }),
    )
}
