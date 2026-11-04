package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A lookup's words, asking and pace (vectors/lookup/words*, asking*, after_the_sheet*) (lane lookup). Replays nothing until its lane fills it. */
object LookupReplay : AreaReplay {
    override val area = "lookup"

    override fun replay(misses: Misses) {}
}
