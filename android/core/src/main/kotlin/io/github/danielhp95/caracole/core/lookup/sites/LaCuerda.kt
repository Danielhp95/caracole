package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's sheet stage from a LaCuerda page picked (`--lacuerda`, `[lacuerda]`; lane lacuerda-sheets). */
object LaCuerdaPickStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}

/** get.py's lacuerda stage: LaCuerda for a song it may have (lane lacuerda-sheets). Neutral: skipped. */
object LaCuerdaStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
