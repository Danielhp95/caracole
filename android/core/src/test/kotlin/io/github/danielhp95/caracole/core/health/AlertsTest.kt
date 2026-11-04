package io.github.danielhp95.caracole.core.health

import org.junit.Test
import kotlin.test.assertEquals

/** Alerts.NONE tells no one; a provider's state starts with no strike. */
class AlertsTest {
    @Test fun noneTellsNoOne() {
        Alerts.NONE.blocked("ug", null, "403")
        Alerts.NONE.failed("Look it up", "Failed")
        assertEquals(0, ProviderState("ug").strikes)
    }
}
