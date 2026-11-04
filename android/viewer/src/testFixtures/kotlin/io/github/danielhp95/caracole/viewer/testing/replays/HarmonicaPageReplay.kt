package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A harmonica tab's page and its harp (vectors/viewer/harpfit*, harmonica_pages*) (lane harmonica-page). Replays nothing until its lane fills it. */
object HarmonicaPageReplay : AreaReplay {
    override val area = "harmonica-page"

    override fun replay(misses: Misses) {}
}
