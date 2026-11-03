package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** The computer's address the Sync tab offers and remembers: the one Settings keeps for the mirror's sync. */
class SyncSettingsTest {
    @Test
    fun `the Sync tab offers the address Settings keeps, and none while none is typed`() {
        val prefs = MemoryPreferences()
        val sync = SavedAddress(Settings(prefs))
        assertNull(sync.address)
        Settings(prefs).server = "   "
        assertNull(sync.address, "blank is none")
        Settings(prefs).server = "192.168.1.20:8737"
        assertEquals("192.168.1.20:8737", sync.address, "as typed: the tab reads it as the computer does")
    }

    @Test
    fun `the address the tab compared with is the one Settings keeps, so the mirror syncs with it too`() {
        val prefs = MemoryPreferences()
        val settings = Settings(prefs)
        settings.server = "http://192.168.1.5:8737"
        settings.syncOnWifi = true
        SavedAddress(settings).remember("http://192.168.1.20:8737")
        assertEquals("http://192.168.1.20:8737", Settings(prefs).server)
        assertEquals("http://192.168.1.20:8737", SavedAddress(Settings(prefs)).address)
        assertEquals(true, Settings(prefs).syncOnWifi, "the other settings as they were")
    }
}
