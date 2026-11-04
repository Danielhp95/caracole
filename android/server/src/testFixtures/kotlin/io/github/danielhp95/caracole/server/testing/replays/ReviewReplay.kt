package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** An uncertain match reviewed (vectors/web/review*) (lane review). Replays nothing until its lane fills it. */
object ReviewReplay : AreaReplay {
    override val area = "review"

    override fun replay(misses: Misses) {}
}
