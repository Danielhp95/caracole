package io.github.danielhp95.caracole.core.config

import org.junit.Test
import kotlin.test.assertEquals

/** The phone's defaults are config.py's, as data/caracole/config/config.json holds them. */
class PhoneConfigTest {
    @Test fun theDefaultsAreConfigPys() {
        val ug = PhoneConfig.DEFAULTS.provider("ug")
        assertEquals(60, ug.budget)
        assertEquals(2.5 to 5.0, ug.delay)
        assertEquals(0.125 to 0.375, ug.lookupDelay)
        assertEquals(PhoneConfig.NO_BUDGET, PhoneConfig.DEFAULTS.provider("azlyrics").budget)
        assertEquals(900, PhoneConfig.DEFAULTS.provider("megalobiz").perDay)
        assertEquals(MatchPolicy(), PhoneConfig.DEFAULTS.match)
        assertEquals(RankPolicy(), PhoneConfig.DEFAULTS.rank)
        assertEquals("caracole/0.1 (personal tab library)", PhoneConfig.DEFAULTS.userAgent)
        assertEquals(setOf("azlyrics", "gametabs", "gtptabs", "harptabs", "megalobiz", "musescore", "youtube", "ytimg"),
                     PhoneConfig.SWITCHABLE)
    }
}
