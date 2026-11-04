package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The sync vectors on the device (lane device-replays). Replays nothing until its lane fills it. */
object SyncReplay : AreaReplay {
    override val area = "sync"

    override fun replay(misses: Misses) {}
}
