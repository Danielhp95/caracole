package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Every job's line, chips and outcome (vectors/web/job_views*, outcome*) (lane job-views). Replays nothing until its lane fills it. */
object JobViewsReplay : AreaReplay {
    override val area = "job-views"

    override fun replay(misses: Misses) {}
}
