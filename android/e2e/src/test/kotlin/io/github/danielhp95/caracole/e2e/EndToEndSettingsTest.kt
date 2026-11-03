package io.github.danielhp95.caracole.e2e

import org.junit.Assume
import org.junit.Test
import kotlin.test.assertTrue

/** The end-to-end phases run only against a server tests/test_android_e2e.py starts (lane e2e-jvm). */
class EndToEndSettingsTest {
    private val server: String? = System.getProperty("caracole.e2e.server")

    @Test fun thePropertiesArePassedThroughOrNoneIs() {
        val given = System.getProperties().stringPropertyNames().filter { it.startsWith("caracole.e2e.") }
        assertTrue(server == null || "caracole.e2e.server" in given)
    }

    @Test fun aServerIsNamed() {
        Assume.assumeTrue("no caracole serve to test against (-Pcaracole.e2e.server)", server != null)
        assertTrue(server!!.startsWith("http"))
    }
}
