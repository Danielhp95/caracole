package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/** get.py's sheet stage from Ultimate Guitar (lane ug-fetch-sheet). Neutral: skipped. */
object UgSheetStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}

/** get.py's ug stage: what follows the sheet on Ultimate Guitar, its versions and its tab (lane ug-fetch-sheet). */
object UgStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = NotYet.STAGE
}
