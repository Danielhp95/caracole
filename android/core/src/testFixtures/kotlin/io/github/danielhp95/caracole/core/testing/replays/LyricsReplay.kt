package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** LRCLIB, Megalobiz and AZLyrics (vectors/sites/ and vectors/lookup/ of each) (lane lyrics). Replays nothing until its lane fills it. */
object LyricsReplay : AreaReplay {
    override val area = "lyrics"

    override fun replay(misses: Misses) {}
}
