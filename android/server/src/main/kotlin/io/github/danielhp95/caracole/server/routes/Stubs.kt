package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/** The routes out of this round, each answering "… isn't on the phone yet." (lane server-shell; until then, none). */
class Stubs : RouteModule {
    override val routes: List<Route> get() = stub("lane server-shell") { emptyList() }
}
