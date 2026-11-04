package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's azlyrics stage (lane lyrics). Neutral: skipped. */
object AzLyricsStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
