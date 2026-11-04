package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's harptabs stage: a song's harmonica tab (lane harptabs). Neutral: skipped. */
object HarpTabsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
