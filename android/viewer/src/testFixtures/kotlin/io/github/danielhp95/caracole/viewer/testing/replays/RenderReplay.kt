package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The phone's own pages (vectors/viewer/render*) (lane phone-render). Replays nothing until its lane fills it. */
object RenderReplay : AreaReplay {
    override val area = "render"

    override fun replay(misses: Misses) {}
}
