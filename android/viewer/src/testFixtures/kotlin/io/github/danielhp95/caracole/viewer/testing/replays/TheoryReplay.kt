package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Music theory (vectors/viewer/theory*) (lane theory). Replays nothing until its lane fills it. */
object TheoryReplay : AreaReplay {
    override val area = "theory"

    override fun replay(misses: Misses) {}
}
