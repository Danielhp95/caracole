package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The library page's lookups on the phone (vectors/web/lookup_routes*, api_search_gate*) (lane lookup-routes). Replays nothing until its lane fills it. */
object LookupRoutesReplay : AreaReplay {
    override val area = "lookup-routes"

    override fun replay(misses: Misses) {}
}
