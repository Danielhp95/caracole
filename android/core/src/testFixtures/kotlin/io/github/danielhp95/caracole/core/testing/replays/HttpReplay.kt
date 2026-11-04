package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** core.http: robots, URLs, the cache and scenarios of a client (vectors/http/) (lane http-client). Replays nothing until its lane fills it. */
object HttpReplay : AreaReplay {
    override val area = "http"

    override fun replay(misses: Misses) {}
}
