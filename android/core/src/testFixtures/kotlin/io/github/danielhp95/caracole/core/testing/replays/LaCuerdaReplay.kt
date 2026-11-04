package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** LaCuerda's pages, search and sheets (vectors/sites/lacuerda*, vectors/lookup/lacuerda*) (lane lacuerda-pages). Replays nothing until its lane fills it. */
object LaCuerdaReplay : AreaReplay {
    override val area = "lacuerda"

    override fun replay(misses: Misses) {}
}
