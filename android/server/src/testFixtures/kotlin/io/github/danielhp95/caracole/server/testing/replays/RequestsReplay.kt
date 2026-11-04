package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The Requests tab's feed (vectors/web/requests*) (lane requests-feed). Replays nothing until its lane fills it. */
object RequestsReplay : AreaReplay {
    override val area = "requests"

    override fun replay(misses: Misses) {}
}
