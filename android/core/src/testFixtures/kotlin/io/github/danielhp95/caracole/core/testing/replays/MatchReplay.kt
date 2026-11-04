package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The matcher (vectors/match/) (lane matcher). Replays nothing until its lane fills it. */
object MatchReplay : AreaReplay {
    override val area = "match"

    override fun replay(misses: Misses) {}
}
