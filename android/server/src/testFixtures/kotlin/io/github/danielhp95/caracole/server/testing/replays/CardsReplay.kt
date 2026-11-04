package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The library page's cards from the phone's own library (vectors/web/cards_full*) (lane library-cards). Replays nothing until its lane fills it. */
object CardsReplay : AreaReplay {
    override val area = "cards"

    override fun replay(misses: Misses) {}
}
