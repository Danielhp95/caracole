package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** UG's tab and artist pages (vectors/sites/ug_pages*, ug_artist*) (lane ug-pages). Replays nothing until its lane fills it. */
object UgPagesReplay : AreaReplay {
    override val area = "ug-pages"

    override fun replay(misses: Misses) {}
}
