package io.github.danielhp95.caracole

import android.view.View
import android.widget.ImageView
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.waitUntil
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * caracole's logo while the app opens (activity_main's `loading`, OpeningScreen, the owner's asks of 2026-11-23): shown
 * as the library screen starts, over the page, saying under it which step the app is at (OpeningSteps: its words and a
 * segment a step), and gone once the page is drawn, so nothing is left over it. Needs no computer.
 */
@RunWith(AndroidJUnit4::class)
class LoadingLogoTest {
    @Test
    fun theLogoShowsAsTheAppOpensAndGoesOnceThePageIsDrawn() {
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            var drawn = false
            var said = ""
            var words = emptyList<String>()
            var segments = 0
            main.onActivity {
                val logo = it.findViewById<View>(R.id.loading)
                drawn = logo.visibility == View.VISIBLE ||
                    // the page may have been drawn already, on a fast device: the logo gone, never left half faded
                    logo.visibility == View.GONE
                assertNotNull((logo as android.view.ViewGroup).getChildAt(0) as ImageView)
                said = it.findViewById<TextView>(R.id.opening_said).text.toString()
                words = listOf(R.string.opening_open, R.string.opening_update, R.string.opening_start,
                               R.string.opening_draw).map(it::getString)
                segments = it.findViewById<android.view.ViewGroup>(R.id.opening_steps).childCount
            }
            assertTrue("the logo neither shown nor gone", drawn)
            // Under the logo, what is happening: one of the steps' words (OpeningSteps), a segment a step.
            assertTrue("the opening screen says \"$said\"", said in words)
            assertEquals(3, segments)
            waitUntil("the library page drawn") { evaluate(main, "document.readyState === 'complete'") == true }
            waitUntil("the logo gone", 5_000) {
                var gone = false
                main.onActivity { gone = it.findViewById<View>(R.id.loading).visibility == View.GONE }
                gone
            }
        }
    }
}
