package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals

class SettingsTest {
    @Test
    fun `the text size is the pages' own until a pinch changes it, and kept`() {
        val prefs = MemoryPreferences()
        assertEquals(100, Settings(prefs).textZoom)
        Settings(prefs).textZoom = 135
        // A new Settings over the same preferences: the app started again.
        assertEquals(135, Settings(prefs).textZoom)
        assertEquals(135, prefs.getInt("text_zoom", 0))
    }

    @Test
    fun `a text size is kept fitted, and one stored out of bounds reads fitted`() {
        val prefs = MemoryPreferences()
        val settings = Settings(prefs)
        settings.textZoom = 400
        assertEquals(250, prefs.getInt("text_zoom", 0))
        settings.textZoom = 33
        assertEquals(50, settings.textZoom)
        prefs.edit().putInt("text_zoom", 1234).apply()
        assertEquals(250, settings.textZoom)
        prefs.edit().putInt("text_zoom", 103).apply()
        assertEquals(105, settings.textZoom)
    }

    @Test
    fun `the text size leaves the other settings as they were`() {
        val prefs = MemoryPreferences()
        val settings = Settings(prefs)
        settings.server = "http://192.168.1.20:8737"
        settings.syncOnWifi = true
        settings.textZoom = 80
        assertEquals("http://192.168.1.20:8737", settings.server)
        assertEquals(true, settings.syncOnWifi)
        assertEquals(80, Settings(prefs).textZoom)
    }

    @Test
    fun `the last index import's outcome is kept apart from the last sync's`() {
        val prefs = MemoryPreferences()
        val settings = Settings(prefs)
        assertEquals(null, settings.lastImport)
        settings.lastOutcome = Outcome(1L, true, "nothing changed")
        settings.lastImport = Outcome(2L, false, "The import failed: interrupted")
        assertEquals(Outcome(2L, false, "The import failed: interrupted"), Settings(prefs).lastImport)
        assertEquals(Outcome(1L, true, "nothing changed"), Settings(prefs).lastOutcome)
        settings.lastImport = null
        assertEquals(null, settings.lastImport)
        assertEquals(Outcome(1L, true, "nothing changed"), settings.lastOutcome)
    }
}
