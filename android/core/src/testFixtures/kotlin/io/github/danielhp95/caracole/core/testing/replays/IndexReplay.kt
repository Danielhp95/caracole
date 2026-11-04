package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The index vectors on the device (lane device-replays). Replays nothing until its lane fills it. */
object IndexReplay : AreaReplay {
    override val area = "index"

    override fun replay(misses: Misses) {}
}
