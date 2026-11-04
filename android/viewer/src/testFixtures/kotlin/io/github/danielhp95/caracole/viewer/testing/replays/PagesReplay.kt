package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The sheet page, byte for byte (vectors/viewer/pages*, page_whole*) (lane pages). Replays nothing until its lane fills it. */
object PagesReplay : AreaReplay {
    override val area = "pages"

    override fun replay(misses: Misses) {}
}
