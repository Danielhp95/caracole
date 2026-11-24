package io.github.danielhp95.caracole

import android.os.SystemClock
import android.util.Log
import android.view.InputDevice
import android.view.MotionEvent
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.mirror.Links
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * What the instrumented tests do to the library screen's pages: where they are (the phone's own server's origin, and
 * a path's address there), a script's value in the page, the address shown, a wait for a condition, two fingers
 * pinched, and the cue for a screenshot taken from the host.
 */
internal object Pages {
    private const val TAG = "CaracolePages"
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    /**
     * The phone's caracole's origin ("http://127.0.0.1:8739", the debug build's [Caracole.PORT]), its server started:
     * where every page of the app is.
     */
    fun origin(): String = Caracole.phone(instrumentation.targetContext).server.origin

    /** [path] of the library ("Estopa/Tu calorro/sheet.html") on the phone's server; "" is the library page. */
    fun address(path: String): String = origin() + Links.target(path)

    /** [script]'s value in the page: a string, a number, a boolean, or null. */
    fun evaluate(scenario: ActivityScenario<MainActivity>, script: String): Any? {
        var raw: String? = null
        val latch = CountDownLatch(1)
        scenario.onActivity { activity ->
            activity.findViewById<WebView>(R.id.web).evaluateJavascript(script) { raw = it; latch.countDown() }
        }
        check(latch.await(10, TimeUnit.SECONDS)) { "no answer from the page to: $script" }
        val value = (JSONTokener("[${raw ?: "null"}]").nextValue() as JSONArray).get(0)
        return if (value == JSONObject.NULL) null else value
    }

    fun url(scenario: ActivityScenario<MainActivity>): String {
        var url: String? = null
        scenario.onActivity { url = it.findViewById<WebView>(R.id.web).url }
        return url.orEmpty()
    }

    fun waitUntil(what: String, timeoutMs: Long = 30_000, condition: () -> Boolean) {
        val end = System.currentTimeMillis() + timeoutMs
        var last: Throwable? = null
        while (System.currentTimeMillis() < end) {
            try {
                if (condition()) return
            } catch (e: Exception) {
                last = e
            } catch (e: AssertionError) {
                last = e
            }
            Thread.sleep(200)
        }
        throw AssertionError("waited ${timeoutMs / 1000} s for $what" + (last?.let { " (last: $it)" } ?: ""), last)
    }

    /**
     * Two fingers on the page, one above the other about its middle, [from] then [to] apart (fractions of the
     * WebView's width), moved in [steps] a frame apart, as a hand pinches: fingers apart when [to] is the larger.
     * [during] runs once they have moved, before they lift.
     */
    fun pinch(scenario: ActivityScenario<MainActivity>, from: Float, to: Float, steps: Int = 24, during: () -> Unit = {}) {
        val origin = IntArray(2)
        var width = 0
        var height = 0
        scenario.onActivity {
            val web = it.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            width = web.width
            height = web.height
        }
        val x = origin[0] + width / 2f
        val y = origin[1] + height / 2f
        val down = SystemClock.uptimeMillis()
        var at = down
        fun send(action: Int, pointers: Int, apart: Float) {
            val half = apart * width / 2
            val properties = Array(pointers) { n ->
                MotionEvent.PointerProperties().apply { id = n; toolType = MotionEvent.TOOL_TYPE_FINGER }
            }
            val coords = Array(pointers) { n ->
                MotionEvent.PointerCoords().apply {
                    this.x = x
                    this.y = if (n == 0) y - half else y + half
                    pressure = 1f
                    size = 1f
                }
            }
            val event = MotionEvent.obtain(down, at, action, pointers, properties, coords, 0, 0, 1f, 1f, 0, 0,
                InputDevice.SOURCE_TOUCHSCREEN, 0)
            check(instrumentation.uiAutomation.injectInputEvent(event, true)) { "the pinch's touch wasn't taken" }
            event.recycle()
        }
        val second = 1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT
        send(MotionEvent.ACTION_DOWN, 1, from)
        at += 10
        send(MotionEvent.ACTION_POINTER_DOWN or second, 2, from)
        for (step in 1..steps) {
            Thread.sleep(16)
            at = SystemClock.uptimeMillis()
            send(MotionEvent.ACTION_MOVE, 2, from + (to - from) * step / steps)
        }
        instrumentation.waitForIdleSync()
        during()
        at = SystemClock.uptimeMillis()
        send(MotionEvent.ACTION_POINTER_UP or second, 2, to)
        at += 10
        send(MotionEvent.ACTION_UP, 1, to)
        instrumentation.waitForIdleSync()
    }

    /**
     * A link to [url] tapped as a finger taps it: a link laid over the whole page by script, then one touch down and
     * up at the WebView's middle, so its navigation carries a gesture (`WebResourceRequest.hasGesture`), as a link the
     * owner taps does and a script's own navigation doesn't.
     */
    fun tapLink(scenario: ActivityScenario<MainActivity>, url: String) {
        evaluate(scenario, """(() => { const a = document.createElement('a'); a.href = ${JSONObject.quote(url)};
            a.textContent = 'tap';
            a.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:block;background:transparent';
            document.body.appendChild(a); return true; })()""")
        val origin = IntArray(2)
        var width = 0
        var height = 0
        var focus = false
        scenario.onActivity {
            focus = it.hasWindowFocus()
            val web = it.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            width = web.width
            height = web.height
        }
        val x = origin[0] + width / 2f
        val y = origin[1] + height / 2f
        val down = SystemClock.uptimeMillis()
        for ((action, at) in listOf(MotionEvent.ACTION_DOWN to down, MotionEvent.ACTION_UP to down + 50)) {
            val event = MotionEvent.obtain(down, at, action, x, y, 0).apply { source = InputDevice.SOURCE_TOUCHSCREEN }
            check(instrumentation.uiAutomation.injectInputEvent(event, true)) { "the tap wasn't taken" }
            event.recycle()
        }
        instrumentation.waitForIdleSync()
    }

    /**
     * A touch down and up on [selector]'s box, found after it is scrolled to the middle of the screen: its CSS point
     * turned to the screen's by the device pixels a CSS pixel is (the WebView's width over `innerWidth`) and the
     * WebView's place on the screen, injected as [tapLink] injects its touch, so the page's handler runs with a user
     * activation. The point is a quarter of the way in from the box's left edge, not its middle: a button at the
     * screen's edge would be under the system's Back gesture there.
     */
    fun tapElement(scenario: ActivityScenario<MainActivity>, selector: String) {
        val q = JSONObject.quote(selector)
        evaluate(scenario, "(() => { const e = document.querySelector($q); if (e) e.scrollIntoView({block: 'center'}); return true; })()")
        Thread.sleep(300)  // the scroll settled before the box is read
        val box = JSONObject(evaluate(scenario, """(() => { const e = document.querySelector($q);
            if (!e) return JSON.stringify({}); const r = e.getBoundingClientRect();
            const x = r.left + r.width * 0.25, y = r.top + r.height * 0.4, at = document.elementFromPoint(x, y);
            return JSON.stringify({x: x, y: y, w: window.innerWidth, hit: !!at && e.contains(at)}); })()""") as String)
        check(box.has("x")) { "no element for $selector" }
        check(box.getBoolean("hit")) { "$selector isn't what is at its own point: $box" }
        val origin = IntArray(2)
        var width = 0
        scenario.onActivity {
            val web = it.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            width = web.width
        }
        val ratio = width / box.getDouble("w").toFloat()
        val x = origin[0] + box.getDouble("x").toFloat() * ratio
        val y = origin[1] + box.getDouble("y").toFloat() * ratio
        Log.i(TAG, "tapElement $selector at ($x, $y), $ratio device px a CSS px")
        val down = SystemClock.uptimeMillis()
        for ((action, at) in listOf(MotionEvent.ACTION_DOWN to down, MotionEvent.ACTION_UP to down + 50)) {
            val event = MotionEvent.obtain(down, at, action, x, y, 0).apply { source = InputDevice.SOURCE_TOUCHSCREEN }
            check(instrumentation.uiAutomation.injectInputEvent(event, true)) { "the tap wasn't taken" }
            event.recycle()
        }
        instrumentation.waitForIdleSync()
    }

    /** With `-e shots <ms>` ([hold] > 0), says the screen is ready for the host's screenshot, and holds it. */
    fun shot(name: String, hold: Long) {
        if (hold <= 0) return
        instrumentation.waitForIdleSync()
        Thread.sleep(800)
        Log.i(TAG, "CARACOLE-SHOT $name")
        Thread.sleep(hold)
    }
}
