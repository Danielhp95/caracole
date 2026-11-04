package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** gtptabs.com and MuseScore (vectors/sites/gtptabs*, musescore*) (lane tab-files). Replays nothing until its lane fills it. */
object TabFilesReplay : AreaReplay {
    override val area = "tab-files"

    override fun replay(misses: Misses) {}
}
