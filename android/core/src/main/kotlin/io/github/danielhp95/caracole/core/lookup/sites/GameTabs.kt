package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's gametabs stage: a song's game tab (lane gametabs). Neutral: skipped. */
object GameTabsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
