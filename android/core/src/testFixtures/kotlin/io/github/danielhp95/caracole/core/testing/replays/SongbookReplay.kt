package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Songbooks named, made and edited (vectors/songbook/) (lanes songbook-writers, songbook-entries). Replays nothing
 * until its lane fills it. */
object SongbookReplay : AreaReplay {
    override val area = "songbook"

    override fun replay(misses: Misses) {}
}
