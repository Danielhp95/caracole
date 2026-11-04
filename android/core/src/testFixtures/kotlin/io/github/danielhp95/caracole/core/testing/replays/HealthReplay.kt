package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** core.health's cooldowns and events (vectors/health/) (lane health-pace). Replays nothing until its lane fills it. */
object HealthReplay : AreaReplay {
    override val area = "health"

    override fun replay(misses: Misses) {}
}
