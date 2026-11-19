package io.github.danielhp95.caracole

import android.view.KeyEvent
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncEngine
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * A pedal in the app's WebView, on a device or an emulator, with the copy synced from a real caracole serve first:
 *
 *     adb shell am instrument -w -e server http://10.0.2.2:8741 -e class io.github.danielhp95.caracole.PedalTest \
 *         io.github.danielhp95.caracole.test/io.github.danielhp95.caracole.CaracoleTestRunner
 *
 * A pedal is a keyboard sending PageDown and Space (or Enter) to the WebView. Once a sheet has loaded, its first key
 * turns a screen (PageDown) or starts the count-in (Space: the pill, its button "Start"), and the page holds the wake
 * lock (`html[data-awake="1"]`) within 5 s of the load; so does the next sheet opened from the library: the WebView
 * keeps the focus after a load. Without `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class PedalTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")

    @Before
    fun aServerIsGiven() = assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)

    @Test
    fun aPedalsFirstPressTurnsAndTheScreenStaysAwakeOnEverySheetOpened() {
        Settings(context).server = server!!
        SyncEngine(Caracole.mirror(context), Caracole.http()).sync(ServerAddress.parse(server))
        Caracole.started()?.search?.invalidate()
        Caracole.mirror(context).reload()!!
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val library = Pages.address("")
            waitUntil("the library page") {
                url(main).substringBefore('#') == library && evaluate(main, "document.readyState") == "complete"
            }
            waitUntil("two sheets listed") {
                evaluate(main, "document.querySelectorAll('a[href\$=\"sheet.html\"]').length") as Int >= 2
            }
            val sheets = JSONObject("{\"a\":" + evaluate(main, """JSON.stringify(Array.from(
                document.querySelectorAll('a[href\$="sheet.html"]')).map((a) => a.href))""") + "}").getJSONArray("a")
            assertTrue("the library has two sheets to open", sheets.length() >= 2)
            for (n in 0..1) {
                open(main, sheets.getString(n))
                waitUntil("the wake lock held within 5 s of the load", 5_000) {
                    evaluate(main, "document.documentElement.dataset.awake === '1'") == true
                }
                val half = evaluate(main, "innerHeight / 2") as Number
                key(KeyEvent.KEYCODE_PAGE_DOWN)
                waitUntil("sheet $n: PageDown turned a screen past half the window") {
                    (evaluate(main, "scrollY") as Number).toDouble() > half.toDouble()
                }
                key(KeyEvent.KEYCODE_SPACE)
                waitUntil("sheet $n: Space shows the pill, counting in") {
                    evaluate(main, "!document.getElementById('pill').hidden && " +
                        "document.getElementById('go').getAttribute('aria-label') === 'Start'") == true
                }
            }
        }
    }

    private fun key(code: Int) = instrumentation.sendKeyDownUpSync(code)

    private fun open(main: ActivityScenario<MainActivity>, address: String) {
        evaluate(main, "window.before = true")
        main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }
        waitUntil("$address loaded") { url(main).substringBefore('#') == address.substringBefore('#') }
        waitUntil("the viewer's script") {
            evaluate(main, "!window.before && document.documentElement.dataset.ready === '1'") == true
        }
    }
}
