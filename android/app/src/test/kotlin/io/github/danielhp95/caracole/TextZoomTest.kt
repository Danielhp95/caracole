package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals

class TextZoomTest {
    @Test
    fun `a size is fitted to a step of five percent, from 50 to 250`() {
        assertEquals(100, TextZoom.fitted(100.0))
        assertEquals(110, TextZoom.fitted(112.4))
        assertEquals(115, TextZoom.fitted(112.5))
        assertEquals(95, TextZoom.fitted(96.0))
        assertEquals(50, TextZoom.fitted(50.0))
        assertEquals(50, TextZoom.fitted(10.0))
        assertEquals(50, TextZoom.fitted(-30.0))
        assertEquals(250, TextZoom.fitted(250.0))
        assertEquals(250, TextZoom.fitted(1000.0))
        assertEquals(250, TextZoom.fitted(Double.POSITIVE_INFINITY))
        assertEquals(100, TextZoom.fitted(Double.NaN))
        assertEquals(120, TextZoom.fitted(121))
        assertEquals(250, TextZoom.fitted(Int.MAX_VALUE))
    }

    @Test
    fun `a size is of the text as Android's font size draws it, which the WebView's own text zoom follows`() {
        assertEquals(120, TextZoom.applied(100, 120))
        assertEquals(130, TextZoom.applied(130, TextZoom.DEFAULT))  // Android's font size at 130 %, kept
        assertEquals(195, TextZoom.applied(130, 150))
        assertEquals(63, TextZoom.applied(115, 55))
    }

    @Test
    fun `the size follows the fingers' span from where the pinch began`() {
        val pinch = Pinched(100)
        pinch.begin()
        pinch.scale(1.2f)
        pinch.frame()
        assertEquals(listOf(120), pinch.applied)
        // Each factor is the step since the last: the span now 1.2 × 1.25 = 1.5 times what it was.
        pinch.scale(1.25f)
        pinch.frame()
        assertEquals(150, pinch.zoom)
        // Fingers together: 0.5 of the span the pinch began with.
        pinch.scale(1f / 3)
        pinch.frame()
        assertEquals(50, pinch.zoom)
        assertEquals(50, pinch.end())
        assertEquals(listOf(120, 150, 50), pinch.applied)
    }

    @Test
    fun `a slow pinch adds up to a step, however small each move is`() {
        val pinch = Pinched(100)
        pinch.begin()
        repeat(20) {
            pinch.scale(1.01f)
            pinch.frame()
        }
        // 1.01^20 = 1.22: 120 %, through every step on the way.
        assertEquals(120, pinch.zoom)
        assertEquals(listOf(105, 110, 115, 120), pinch.applied)
    }

    @Test
    fun `the size changes at most once a frame, to where the fingers are by then`() {
        val pinch = Pinched(100)
        pinch.begin()
        pinch.scale(1.1f)
        pinch.scale(1.1f)
        pinch.scale(1.1f)
        assertEquals(1, pinch.frames.size)
        assertEquals(emptyList(), pinch.applied)
        pinch.frame()
        assertEquals(listOf(135), pinch.applied)  // 1.331
        // A move that comes back to the size applied asks for no frame; one that leaves it, for one.
        pinch.scale(1.01f)
        assertEquals(0, pinch.frames.size)
        pinch.scale(0.9f)
        pinch.scale(1.12f)
        pinch.frame()
        assertEquals(listOf(135), pinch.applied)
    }

    @Test
    fun `past a limit, the way back starts at once`() {
        val pinch = Pinched(200)
        pinch.begin()
        pinch.scale(3f)
        pinch.frame()
        assertEquals(250, pinch.zoom)
        // Twice as far apart as the limit needed counts for no more than the limit: fingers a little closer, smaller.
        pinch.scale(0.9f)
        pinch.frame()
        assertEquals(225, pinch.zoom)
        pinch.scale(0.01f)
        pinch.frame()
        assertEquals(50, pinch.zoom)
        pinch.scale(1.2f)
        pinch.frame()
        assertEquals(60, pinch.zoom)
    }

    @Test
    fun `the next pinch begins at the size the last one ended at`() {
        val pinch = Pinched(100)
        pinch.begin()
        pinch.scale(1.5f)
        pinch.frame()
        assertEquals(150, pinch.end())
        pinch.begin()
        pinch.scale(1.2f)
        pinch.frame()
        assertEquals(180, pinch.zoom)
        // Even when it begins before the last one's frame came: from where its fingers had come.
        pinch.scale(0.5f)
        pinch.end()
        pinch.begin()
        pinch.scale(2f)
        pinch.frame()
        assertEquals(180, pinch.zoom)
    }

    @Test
    fun `a size set from outside applies at once, and the next pinch starts from it`() {
        val pinch = Pinched(150)
        pinch.set(100)
        assertEquals(100, pinch.zoom)
        assertEquals(listOf(100), pinch.applied)
        pinch.set(100)
        assertEquals(listOf(100), pinch.applied)  // nothing to change
        pinch.set(400)
        assertEquals(250, pinch.zoom)
        // A frame a pinch asked for before then applies nothing it had aimed at.
        pinch.begin()
        pinch.scale(0.5f)
        pinch.set(150)
        pinch.frame()
        assertEquals(listOf(100, 250, 150), pinch.applied)
        pinch.begin()
        pinch.scale(1.2f)
        pinch.frame()
        assertEquals(180, pinch.zoom)
    }

    /** A [TextPinch] whose frames run when the test says so, recording each size applied. */
    private class Pinched(zoom: Int) {
        val applied = mutableListOf<Int>()
        val frames = ArrayDeque<() -> Unit>()
        private val pinch = TextPinch(zoom, frame = { frames.addLast(it) }, apply = { applied.add(it) })

        val zoom get() = pinch.zoom
        fun begin() = pinch.begin()
        fun scale(factor: Float) = pinch.scale(factor)
        fun end() = pinch.end()
        fun set(zoom: Int) = pinch.set(zoom)

        /** The next frame: the blocks asked for until now run. */
        fun frame() {
            val now = frames.toList()
            frames.clear()
            now.forEach { it() }
        }
    }
}
