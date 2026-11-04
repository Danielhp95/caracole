package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * A harmonica tab's readings chosen on the phone (web/harmonica_routes.py; lane versions-harmonica): its page of
 * readings, and each pinned or cleared as a job under jobs.READING. Neutral: each refused as not on the phone yet,
 * as Stubs refused them.
 */
class HarmonicaRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/harmonica", "$WHAT: not on the phone yet", get = GetAnswer { notYet(WHAT) }),
        Route("POST", "/harmonica/pin", "$WHAT: not on the phone yet", page = PAGE,
              post = PostAnswer { _, _ -> notYet(WHAT) }),
        Route("POST", "/harmonica/clear", "$WHAT: not on the phone yet", page = PAGE,
              post = PostAnswer { _, _ -> notYet(WHAT) }),
    )

    private companion object {
        const val WHAT = "Choosing how a harmonica tab is read"
        const val PAGE = "the tab's page of readings"
    }
}
