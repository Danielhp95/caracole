package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** gametabs.net (vectors/sites/gametabs*, vectors/lookup/gametabs*) (lane gametabs). Replays nothing until its lane fills it. */
object GameTabsReplay : AreaReplay {
    override val area = "gametabs"

    override fun replay(misses: Misses) {}
}
