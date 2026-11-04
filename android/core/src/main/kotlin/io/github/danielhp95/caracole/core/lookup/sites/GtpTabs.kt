package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's gtptabs stage: a song's Guitar Pro file (lane tab-files). Neutral: skipped. */
object GtpTabsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
