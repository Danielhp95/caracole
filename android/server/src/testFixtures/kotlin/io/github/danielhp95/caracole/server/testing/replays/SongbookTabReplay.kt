package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The Songbooks tab's forms and jobs (vectors/songbook/routes*) (lane songbook-routes). Replays nothing until its lane fills it. */
object SongbookTabReplay : AreaReplay {
    override val area = "songbook-tab"

    override fun replay(misses: Misses) {}
}
