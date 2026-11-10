package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * The Songbooks tab's forms on the phone (web/songbook_routes.py; lane songbook-routes): each a job of the songbook
 * runner keyed as web/songbooks._job. Neutral: each refused as not on the phone yet, as Stubs refused them.
 */
class SongbookRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = FORMS.map { (path, what) ->
        Route("POST", path, "$what: not on the phone yet", post = PostAnswer { _, _ -> notYet(what) })
    }

    private companion object {
        val FORMS = listOf(
            "/songbook/make" to "Making a songbook",
            "/songbook/add" to "Adding to a songbook",
            "/songbook/add-song" to "Adding to a songbook",
            "/songbook/get" to "Fetching a songbook's songs",
            "/songbook/remove" to "Taking a song out of a songbook",
            "/songbook/move" to "Moving a song in a songbook",
            "/songbook/set" to "Changing where a songbook plays a song",
            "/songbook/rename" to "Renaming a songbook",
            "/songbook/delete" to "Deleting a songbook",
        )
    }
}
