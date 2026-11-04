package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.SiteStages
import org.junit.Test
import kotlin.test.assertEquals

/** Every site's stage is its lane's; each is neutral until then. */
class StagesTest {
    @Test fun everyStageIsNamedAndNeutral() {
        val all = SiteStages.ALL
        val stages = listOf(all.match, all.ugSheet, all.ug, all.lacuerdaPick, all.lacuerda, all.lrclib, all.megalobiz,
                            all.azlyrics, all.gtptabs, all.harptabs, all.gametabs)
        assertEquals(11, stages.toSet().size)
        assertEquals("skipped", NotYet.STAGE.state)
    }
}
