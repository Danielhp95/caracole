package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.SongCards

/** POST /request, /lookup and /remove on the phone (lane phone-sync-routes; until then, refused). */
class LibraryRoutes(val store: LibraryStore, val queue: JobQueue, val cards: SongCards, val database: Database) :
    RouteModule {
    override val routes: List<Route> = listOf(
        "/request" to "a song for the library", "/lookup" to "a song looked up", "/remove" to "a song removed",
    ).map { (path, doc) -> Route("POST", path, doc, post = PostAnswer { _, _ -> notBuilt() }) }

    private fun notBuilt(): Response = stub("lane phone-sync-routes") {
        throw Refused(409, "Not on the phone yet", "Adding and removing songs isn't on the phone yet.")
    }
}
