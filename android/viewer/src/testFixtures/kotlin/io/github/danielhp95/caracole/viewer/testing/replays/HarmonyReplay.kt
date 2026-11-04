package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Harmony, its progressions and tables (vectors/viewer/harmony_*) (lanes harmony, then harmony-progressions). Replays nothing until its lane fills it. */
object HarmonyReplay : AreaReplay {
    override val area = "harmony"

    override fun replay(misses: Misses) {}
}
