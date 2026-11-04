package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** core.py's site and format records (vectors/py/) (lane py-sites). Replays nothing until its lane fills it. */
object PyReplay : AreaReplay {
    override val area = "py"

    override fun replay(misses: Misses) {}
}
