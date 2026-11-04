package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Export PDF and Make this my version (vectors/web/export*) (lane export-print). Replays nothing until its lane fills it. */
object ExportReplay : AreaReplay {
    override val area = "export"

    override fun replay(misses: Misses) {}
}
