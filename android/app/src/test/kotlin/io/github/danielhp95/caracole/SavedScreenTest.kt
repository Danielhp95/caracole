package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The library screen's history comes back after Android recreated it, only at the origin it was saved at. */
class SavedScreenTest {
    @Test
    fun `the WebView's history is restored only at today's origin`() {
        assertTrue(SavedScreen.restores("http://127.0.0.1:8738", "http://127.0.0.1:8738"))
        // Another launch's server took another port (8738 was taken): its pages are another origin's, which the
        // WebView never loads and the launch's cookie never reaches.
        assertFalse(SavedScreen.restores("http://127.0.0.1:41234", "http://127.0.0.1:8738"))
        assertFalse(SavedScreen.restores("http://127.0.0.1:8738", "http://127.0.0.1:41234"))
        // A state saved before the app had its own server (the asset loader's), or with no origin at all.
        assertFalse(SavedScreen.restores(null, "http://127.0.0.1:8738"))
        assertFalse(SavedScreen.restores("", "http://127.0.0.1:8738"))
    }

    @Test
    fun `after the renderer died the page it showed opens again, at today's origin alone`() {
        val origin = "http://127.0.0.1:8738"
        val sheet = "$origin/Estopa/Tu%20calorro/sheet.html"
        assertEquals(sheet, SavedScreen.reopened(sheet, origin, origin) { true })
        assertNull(SavedScreen.reopened(null, origin, origin) { true }, "no page: the library page")
        assertNull(SavedScreen.reopened(sheet, "http://127.0.0.1:41234", origin) { true }, "another launch's")
        assertNull(SavedScreen.reopened("http://127.0.0.1:41234/x", origin, origin) { true }, "another origin's page")
        assertNull(SavedScreen.reopened(sheet, origin, origin) { false }, "one the WebView doesn't load")
    }
}
