package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A sheet's versions and a harmonica tab's readings chosen (vectors/web/versions_routes*, harmonica_routes*) (lane versions-harmonica). Replays nothing until its lane fills it. */
object ChoicesReplay : AreaReplay {
    override val area = "choices"

    override fun replay(misses: Misses) {}
}
