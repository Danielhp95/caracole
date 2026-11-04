package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The pages' library name (vectors/web/library_name*) (lane prep-core). Replays nothing until its lane fills it. */
object LibraryNameReplay : AreaReplay {
    override val area = "library-name"

    override fun replay(misses: Misses) {}
}
