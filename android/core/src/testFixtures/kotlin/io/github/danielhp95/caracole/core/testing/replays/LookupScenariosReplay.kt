package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Whole lookups replayed from the computer's records (vectors/lookup/get*) (lane lookup-scenarios). Replays nothing until its lane fills it. */
object LookupScenariosReplay : AreaReplay {
    override val area = "lookup-scenarios"

    override fun replay(misses: Misses) {}
}
