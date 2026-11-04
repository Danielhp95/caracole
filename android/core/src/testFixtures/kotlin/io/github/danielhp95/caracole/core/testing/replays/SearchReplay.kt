package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The search vectors on the device (lane device-replays). Replays nothing until its lane fills it. */
object SearchReplay : AreaReplay {
    override val area = "search"

    override fun replay(misses: Misses) {}
}
