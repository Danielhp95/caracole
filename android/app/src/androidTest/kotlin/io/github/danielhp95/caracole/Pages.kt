package io.github.danielhp95.caracole

import android.os.SystemClock
import android.util.Log
import android.view.InputDevice
import android.view.MotionEvent
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * What the instrumented tests do to the library screen's pages: a script's value in the page, the address shown,
 * a wait for a condition, two fingers pinched, and the cue for a screenshot taken from the host.
 */
internal object Pages {
    private const val TAG = "CaracolePages"
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

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
     */
    fun pinch(scenario: ActivityScenario<MainActivity>, from: Float, to: Float, steps: Int = 24) {
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
        at += 10
        send(MotionEvent.ACTION_POINTER_UP or second, 2, to)
        at += 10
        send(MotionEvent.ACTION_UP, 1, to)
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
