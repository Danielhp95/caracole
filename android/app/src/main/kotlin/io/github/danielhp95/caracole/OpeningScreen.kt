package io.github.danielhp95.caracole

import android.animation.ValueAnimator
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
import android.widget.TextView
import androidx.core.content.ContextCompat

/**
 * The opening screen (activity_main's `loading`): caracole's logo, a segment a step (OpeningSteps), the steps done
 * filled in the accent and the current one with a moving shine, and under them what is happening; a step slower than
 * [SLOW_MS] adds that it is still working. Gone, faded, once the first page is drawn ([done]), and what waited for it
 * then shown ([whenGone]). Stopped with its screen ([stop]): its shine never runs on for a screen gone, nor starts
 * again for a step the start still tells. On the UI thread alone.
 */
class OpeningScreen(private val root: View) {
    private val segments: List<ViewGroup> = root.findViewById<ViewGroup>(R.id.opening_steps).let { row ->
        (0 until row.childCount).map { row.getChildAt(it) as ViewGroup }
    }
    private val said: TextView = root.findViewById(R.id.opening_said)
    private val more: TextView = root.findViewById(R.id.opening_more)
    private var shine: ValueAnimator? = null
    private val slow = Runnable { more.visibility = View.VISIBLE }
    private var stopped = false
    private val afterGone = ArrayList<() -> Unit>()

    /** Whether its shine runs (a device test's). */
    val shining: Boolean get() = shine?.isRunning == true

    /** The step [step] is at, and what it says; [updating]: the library is upgraded first (OpeningSteps.updating). */
    fun show(step: OpeningSteps.Step, updating: Boolean = false) {
        if (stopped || root.visibility != View.VISIBLE) return
        said.setText(when (step) {
            OpeningSteps.Step.OPEN -> if (updating) R.string.opening_update else R.string.opening_open
            OpeningSteps.Step.START -> R.string.opening_start
            OpeningSteps.Step.DRAW -> R.string.opening_draw
        })
        val accent = ContextCompat.getColor(root.context, R.color.accent)
        segments.forEachIndexed { i, segment ->
            segment.background.mutate().setTint(if (i < step.number - 1) accent else ContextCompat.getColor(
                root.context, R.color.opening_track))
            segment.getChildAt(0).visibility = if (i == step.number - 1) View.VISIBLE else View.INVISIBLE
        }
        shine?.cancel()
        val current = segments[step.number - 1]
        val light = current.getChildAt(0)
        shine = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = SHINE_MS
            repeatCount = ValueAnimator.INFINITE
            interpolator = AccelerateDecelerateInterpolator()
            addUpdateListener { light.translationX = -light.width + (current.width + light.width) * (it.animatedValue as Float) }
            start()
        }
        more.visibility = View.INVISIBLE
        root.removeCallbacks(slow)
        root.postDelayed(slow, SLOW_MS)
    }

    /** The first page drawn, or a message said: the screen fades out, once, then what waited for it is shown. */
    fun done() {
        if (stopped || root.visibility != View.VISIBLE || root.alpha < 1f) return
        root.removeCallbacks(slow)
        root.animate().alpha(0f).setDuration(FADE_MS).withEndAction {
            shine?.cancel()
            root.visibility = View.GONE
            val then = afterGone.toList()
            afterGone.clear()
            then.forEach { it() }
        }
    }

    /** [then] once the screen is gone: now if it is, else at the end of its fade (the first start's offer, which would
     * otherwise lie, live, under or over the logo). Never once the screen is [stop]ped. */
    fun whenGone(then: () -> Unit) {
        if (stopped) return
        if (root.visibility == View.GONE) then() else afterGone += then
    }

    /** Its screen gone (MainActivity.onDestroy, in the opening too: Back, a recreation): the shine, the slow step's
     * words and the fade stopped, and nothing it is told after shown. */
    fun stop() {
        stopped = true
        shine?.cancel()
        shine = null
        root.removeCallbacks(slow)
        root.animate().cancel()
        afterGone.clear()
    }

    companion object {
        /** A step longer than this says it is still working. */
        const val SLOW_MS = 5_000L
        private const val SHINE_MS = 1_000L
        private const val FADE_MS = 200L
    }
}
