package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * The Guitar Pro page on the phone (web/guitar_routes.py; lane guitar-alphatab): a song's kept Guitar Pro file drawn
 * by alphaTab, and alphaTab's bundle at `/assets/alphatab/` (which the app answers first in the WebView,
 * AlphaTabAssets). Neutral: each refused as not on the phone yet.
 */
class GuitarRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/guitar", "$WHAT: not on the phone yet", get = GetAnswer { notYet(WHAT) }),
        Route("GET", "/assets/alphatab/", "alphaTab's bundle: not on the phone yet", under = true,
              get = GetAnswer { notYet("alphaTab's bundle") }),
    )

    private companion object {
        const val WHAT = "The Guitar Pro page"
    }
}
