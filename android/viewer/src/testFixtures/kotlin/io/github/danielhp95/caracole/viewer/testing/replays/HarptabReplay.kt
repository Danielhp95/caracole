package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A harmonica tab read and laid out (vectors/viewer/harptab*) (lanes harptab-read, then harptab-layout). Replays nothing until its lane fills it. */
object HarptabReplay : AreaReplay {
    override val area = "harptab"

    override fun replay(misses: Misses) {}
}
