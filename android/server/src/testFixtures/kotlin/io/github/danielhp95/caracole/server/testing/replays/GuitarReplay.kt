package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The Guitar Pro page and alphaTab's bundle (vectors/web/guitar*) (lane guitar-alphatab). Replays nothing until its lane fills it. */
object GuitarReplay : AreaReplay {
    override val area = "guitar"

    override fun replay(misses: Misses) {}
}
