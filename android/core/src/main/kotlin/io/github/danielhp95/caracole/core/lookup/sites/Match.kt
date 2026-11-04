package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's match stage: the song matched to UG's index (lane matcher). Neutral: skipped. */
object MatchStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
