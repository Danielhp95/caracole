package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Voicings, instruments, the harmonica and the winds (vectors/viewer/voicings*, instruments*, harp_*, winds*) (lane shapes-harp-winds). Replays nothing until its lane fills it. */
object ShapesReplay : AreaReplay {
    override val area = "shapes"

    override fun replay(misses: Misses) {}
}
