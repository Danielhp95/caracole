package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertFalse
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
}
