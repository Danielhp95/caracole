package io.github.danielhp95.caracole

import kotlin.math.roundToInt
import kotlin.math.roundToLong

/**
 * The size the pages' text is shown at, in percent of their own as Android's font size draws them (the WebView's
 * textZoom, which follows that setting until it is set): only the text grows or shrinks, and the page reflows to the
 * screen's width, never zoomed as a picture. A page's own text size (the viewer's Aa) is multiplied by it.
 */
object TextZoom {
    /** The pages' own size, as Android's font size draws them. */
    const val DEFAULT = 100
    const val MIN = 50
    const val MAX = 250
    const val STEP = 5

    /** [percent] to the nearest [STEP], from [MIN] to [MAX]: 112.4 is 110, 400 is 250, NaN the pages' own size. */
    fun fitted(percent: Double): Int {
        if (percent.isNaN()) return DEFAULT
        val step = (percent.coerceIn(MIN.toDouble(), MAX.toDouble()) / STEP).roundToLong()
        return (step * STEP).toInt()
    }

    fun fitted(percent: Int): Int = fitted(percent.toDouble())

    /** The WebView's textZoom for [percent], where [own] is its own (Android's font size: 130 for 130 %). */
    fun applied(own: Int, percent: Int): Int = (own * percent / 100.0).roundToInt()
}

/**
 * Pinches, one after another, as the text's size: [begin] when two fingers start to pinch, [scale] as they move
 * (each move's factor, as Android's ScaleGestureDetector gives it), [end] when they part from the screen. The size
 * follows the fingers' span since the pinch began, fitted ([TextZoom.fitted]): twice as far apart, twice the size.
 * Past a limit the span counts for no more than the limit, so the way back starts at once. A size is [apply]'d
 * only when it changed, at most once a frame ([frame] runs a block at the next one), as each change lays the page
 * out again.
 */
class TextPinch(zoom: Int, private val frame: (() -> Unit) -> Unit, private val apply: (Int) -> Unit) {
    /** The size applied. */
    var zoom: Int = TextZoom.fitted(zoom)
        private set

    /** Where the fingers have come to, applied at the next frame. */
    private var target = this.zoom
    private var from = this.zoom
    private var span = 1.0
    private var queued = false

    fun begin() {
        from = target
        span = 1.0
    }

    fun scale(factor: Float) {
        if (factor.isNaN() || factor <= 0f) return
        span = (span * factor).coerceIn(TextZoom.MIN.toDouble() / from, TextZoom.MAX.toDouble() / from)
        target = TextZoom.fitted(from * span)
        if (queued || target == zoom) return
        queued = true
        frame {
            queued = false
            if (target != zoom) {
                zoom = target
                apply(zoom)
            }
        }
    }

    /** The size the pinch ends at, to keep: the one its fingers came to (the next frame applies it). */
    fun end(): Int = target

    /** A size chosen elsewhere (Settings' Reset), applied at once; the next pinch starts from it. */
    fun set(size: Int) {
        val fitted = TextZoom.fitted(size)
        target = fitted
        from = fitted
        span = 1.0
        if (fitted == zoom) return
        zoom = fitted
        apply(fitted)
    }
}
