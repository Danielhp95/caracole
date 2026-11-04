package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** Ranking, coverage and sheet versions (vectors/sites/ug_rank*, ug_coverage*, ug_sheet_versions*) (lane rank-coverage). Replays nothing until its lane fills it. */
object RankReplay : AreaReplay {
    override val area = "rank"

    override fun replay(misses: Misses) {}
}
