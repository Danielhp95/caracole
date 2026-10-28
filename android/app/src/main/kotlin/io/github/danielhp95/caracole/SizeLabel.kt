package io.github.danielhp95.caracole

/**
 * The size a pinch is at ([TextZoom]), over the page while the pinch lasts: shown as it [began], at each step it
 * [sized] the text to (a limit, where the fingers go further, stays shown), and at its end ([ended]), when the size
 * is said once for assistive technology ([announce]); then hidden [HOLD_MS] after the end, faded out, or at once where
 * motion is reduced ([calm]). A size set outside a pinch (Settings' Reset) shows nothing. [later] runs a block after a
 * delay and gives back what calls it off.
 */
class SizeLabel(
    private val show: (Int) -> Unit,
    private val hide: (fade: Boolean) -> Unit,
    private val announce: (Int) -> Unit,
    private val later: (Long, () -> Unit) -> () -> Unit,
    private val calm: () -> Boolean,
) {
    private var pinching = false
    private var hiding: (() -> Unit)? = null

    fun began(size: Int) {
        hiding?.invoke()
        hiding = null
        pinching = true
        show(size)
    }

    fun sized(size: Int) {
        if (pinching) show(size)
    }

    fun ended(size: Int) {
        if (!pinching) return
        pinching = false
        show(size)
        announce(size)
        hiding = later(HOLD_MS) {
            hiding = null
            hide(!calm())
        }
    }

    companion object {
        /** How long the size stays shown once the fingers are lifted. */
        const val HOLD_MS = 1_000L
    }
}
