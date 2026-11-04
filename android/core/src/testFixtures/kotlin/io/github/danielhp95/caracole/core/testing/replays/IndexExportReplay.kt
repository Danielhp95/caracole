package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The phone's index export (vectors/index/export*) (lane index-push). Replays nothing until its lane fills it. */
object IndexExportReplay : AreaReplay {
    override val area = "index-export"

    override fun replay(misses: Misses) {}
}
