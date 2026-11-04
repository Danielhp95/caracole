package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Kept files, versions, numbering and passes (vectors/library/writes*) (lane library-writes). Replays nothing until its lane fills it. */
object LibraryWritesReplay : AreaReplay {
    override val area = "library-writes"

    override fun replay(misses: Misses) {}
}
