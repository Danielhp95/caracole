package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** harptabs.com (vectors/sites/harptabs*, vectors/lookup/harptabs*) (lane harptabs). Replays nothing until its lane fills it. */
object HarpTabsReplay : AreaReplay {
    override val area = "harptabs"

    override fun replay(misses: Misses) {}
}
