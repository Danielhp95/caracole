package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals

class SizeLabelTest {
    @Test
    fun `a pinch shows its size from its start and at each step, and says nothing until it ends`() {
        val label = Labelled()
        label.began(100)
        label.sized(105)
        label.sized(110)
        assertEquals(listOf("show 100", "show 105", "show 110"), label.done)
        assertEquals(emptyList(), label.waiting.keys.toList())
    }

    @Test
    fun `at its end the final size is shown and said once, then hidden with a fade a second later`() {
        val label = Labelled()
        label.began(100)
        label.sized(135)
        label.ended(135)
        assertEquals(listOf("show 100", "show 135", "show 135", "say 135"), label.done)
        assertEquals(listOf(SizeLabel.HOLD_MS), label.waiting.keys.toList())
        label.time(SizeLabel.HOLD_MS)
        assertEquals("hide, fading", label.done.last())
        assertEquals(1, label.done.count { it == "say 135" })
    }

    @Test
    fun `with motion reduced it is hidden at once, with no fade`() {
        val label = Labelled(calm = true)
        label.began(100)
        label.ended(120)
        label.time(SizeLabel.HOLD_MS)
        assertEquals("hide", label.done.last())
    }

    @Test
    fun `a pinch begun while the last one's size is still shown keeps it shown`() {
        val label = Labelled()
        label.began(100)
        label.ended(150)
        label.began(150)
        assertEquals(emptyList(), label.waiting.keys.toList())  // the hide is called off
        label.sized(180)
        label.ended(180)
        label.time(SizeLabel.HOLD_MS)
        assertEquals(listOf("show 100", "show 150", "say 150", "show 150", "show 180", "show 180", "say 180",
            "hide, fading"), label.done)
    }

    @Test
    fun `a size set outside a pinch, as Settings' Reset sets it, shows nothing`() {
        val label = Labelled()
        label.sized(100)
        assertEquals(emptyList(), label.done)
        // Nor does the last frame of a pinch that has ended, which applies the size the end already showed.
        label.began(100)
        label.ended(130)
        label.sized(130)
        assertEquals(listOf("show 100", "show 130", "say 130"), label.done)
    }

    @Test
    fun `at a limit the label shows the limit, however much further the fingers go`() {
        val label = Labelled()
        val frames = ArrayDeque<() -> Unit>()
        val pinch = TextPinch(200, frame = { frames.addLast(it) }, apply = { label.sized(it) })
        fun frame() = frames.toList().also { frames.clear() }.forEach { it() }
        label.began(pinch.zoom)
        pinch.begin()
        pinch.scale(1.2f)
        frame()
        pinch.scale(2f)
        frame()
        label.ended(pinch.end())
        assertEquals(listOf("show 200", "show 240", "show 250", "show 250", "say 250"), label.done)

        label.began(pinch.zoom)
        pinch.begin()
        pinch.scale(0.1f)
        frame()
        label.ended(pinch.end())
        assertEquals(listOf("show 250", "show 50", "show 50", "say 50"), label.done.takeLast(4))
    }

    /** A [SizeLabel] on a clock the test moves ([time]), recording what it shows, hides and says. */
    private class Labelled(calm: Boolean = false) {
        val done = mutableListOf<String>()
        /** The blocks waiting, by when they run. */
        val waiting = sortedMapOf<Long, () -> Unit>()
        private var now = 0L
        private val label = SizeLabel(
            show = { done.add("show $it") },
            hide = { fade -> done.add(if (fade) "hide, fading" else "hide") },
            announce = { done.add("say $it") },
            later = { delay, block ->
                val at = now + delay
                waiting[at] = block
                ({ waiting.remove(at) })
            },
            calm = { calm },
        )

        fun began(size: Int) = label.began(size)
        fun sized(size: Int) = label.sized(size)
        fun ended(size: Int) = label.ended(size)

        /** [ms] go by: what was waiting until then runs. */
        fun time(ms: Long) {
            now += ms
            val due = waiting.headMap(now + 1).toMap()
            due.keys.forEach { waiting.remove(it) }
            due.values.forEach { it() }
        }
    }
}
