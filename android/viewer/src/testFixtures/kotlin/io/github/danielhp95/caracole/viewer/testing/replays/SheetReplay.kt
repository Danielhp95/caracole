package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A sheet read, ChordPro and a song's key (vectors/viewer/sheet*, chordpro*, musickeys*) (lane sheet-keys). Replays nothing until its lane fills it. */
object SheetReplay : AreaReplay {
    override val area = "sheet"

    override fun replay(misses: Misses) {}
}
