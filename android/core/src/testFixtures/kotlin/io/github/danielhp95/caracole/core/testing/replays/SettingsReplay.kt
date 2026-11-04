package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The computer's settings taken (vectors/sync/settings*) (lane crossing-phone). Replays nothing until its lane fills it. */
object SettingsReplay : AreaReplay {
    override val area = "settings"

    override fun replay(misses: Misses) {}
}
