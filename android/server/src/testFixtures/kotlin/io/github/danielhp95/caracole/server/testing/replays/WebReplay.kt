package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** M1–3's web vectors on the device (lane device-replays). Replays nothing until its lane fills it. */
object WebReplay : AreaReplay {
    override val area = "web"

    override fun replay(misses: Misses) {}
}
