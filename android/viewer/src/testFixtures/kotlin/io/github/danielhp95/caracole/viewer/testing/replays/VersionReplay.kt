package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Versions of a sheet and progressions (vectors/viewer/version*, progressions*) (lane version-progressions). Replays nothing until its lane fills it. */
object VersionReplay : AreaReplay {
    override val area = "version"

    override fun replay(misses: Misses) {}
}
