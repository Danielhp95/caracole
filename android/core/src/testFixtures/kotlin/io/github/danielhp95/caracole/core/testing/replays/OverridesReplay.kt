package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Overrides read and written (vectors/library/overrides*) (lane overrides-model). Replays nothing until its lane fills it. */
object OverridesReplay : AreaReplay {
    override val area = "overrides"

    override fun replay(misses: Misses) {}
}
