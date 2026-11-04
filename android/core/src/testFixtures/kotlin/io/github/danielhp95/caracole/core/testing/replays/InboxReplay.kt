package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** A file shared to the app, filed as _inbox/ files it (vectors/inbox/) (lane inbox-share). Replays nothing until
 * its lane fills it. */
object InboxReplay : AreaReplay {
    override val area = "inbox"

    override fun replay(misses: Misses) {}
}
