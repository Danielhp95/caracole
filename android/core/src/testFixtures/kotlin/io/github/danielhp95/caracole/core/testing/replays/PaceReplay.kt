package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The lookup pace (vectors/pace/) (lane health-pace). Replays nothing until its lane fills it. */
object PaceReplay : AreaReplay {
    override val area = "pace"

    override fun replay(misses: Misses) {}
}
