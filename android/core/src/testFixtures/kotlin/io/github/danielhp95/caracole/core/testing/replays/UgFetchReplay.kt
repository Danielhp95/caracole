package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** UG's lookup path and its artist pages (vectors/lookup/ug_*) (lane ug-fetch-sheet). Replays nothing until its lane fills it. */
object UgFetchReplay : AreaReplay {
    override val area = "ug-fetch"

    override fun replay(misses: Misses) {}
}
