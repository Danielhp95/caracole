package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/**
 * get.py's ireal stage on the phone: a chart of iReal Pro's forum as the sheet of a song the sheet sites left with
 * none comes from the index the computer's nightly run reads (ireal_fetch.py), which no export, merge or sync carries
 * (it isn't in index_transfer.SITES): the phone's tables of it are empty, so the stage has nothing to ask, and says so
 * in get.py's words for a song with no candidate ([NOT_ASKED]), with no client made, as get.py's `wants_a_chart` then
 * makes none. A chart the computer kept comes with its song's unit, its sheet's files and `[ireal]` among them; a pick
 * of `[ireal]` the phone doesn't read yet.
 */
object IRealStage : SiteStage {
    const val PROVIDER = "ireal"
    const val NOT_ASKED = "no sheet wanted, or iReal Pro's forum has no chart of this title"

    override fun run(ctx: StageContext): StageEnd = StageEnd("skipped", NOT_ASKED)
}
