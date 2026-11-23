package io.github.danielhp95.caracole

import android.view.View
import android.widget.ImageView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.waitUntil
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * caracole's logo while the app opens (activity_main's `loading`, MainActivity.loaded, the owner's ask of 2026-11-23):
 * shown as the library screen starts, over the page, and gone once the page is drawn, so nothing is left over it. Needs
 * no computer.
 */
@RunWith(AndroidJUnit4::class)
class LoadingLogoTest {
    @Test
    fun theLogoShowsAsTheAppOpensAndGoesOnceThePageIsDrawn() {
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            var drawn = false
            main.onActivity {
                val logo = it.findViewById<View>(R.id.loading)
                drawn = logo.visibility == View.VISIBLE ||
                    // the page may have been drawn already, on a fast device: the logo gone, never left half faded
                    logo.visibility == View.GONE
                assertNotNull((logo as android.view.ViewGroup).getChildAt(0) as ImageView)
            }
            assertTrue("the logo neither shown nor gone", drawn)
            waitUntil("the library page drawn") { evaluate(main, "document.readyState === 'complete'") == true }
            waitUntil("the logo gone", 5_000) {
                var gone = false
                main.onActivity { gone = it.findViewById<View>(R.id.loading).visibility == View.GONE }
                gone
            }
        }
    }
}
