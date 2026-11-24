package io.github.danielhp95.caracole.core.index

/**
 * A long job's words, told to [tell] at most once every [every] nanoseconds of [ticks] while they are of one step (a
 * count going up: "Downloading · 31 of 52 MB", "Importing · Ultimate Guitar · 600,000 of 1,521,145 tabs"), but at
 * once when they are of another step than the last told, so that no step is ever passed over in silence; the same
 * words never twice in a row. The catalogues job's and a sync's index stage's, which a page or the app reads as often
 * as it likes.
 */
class Paced(private val tell: (String) -> Unit, private val every: Long = SECOND,
            private val ticks: () -> Long = System::nanoTime) {
    private var said: String? = null
    private var step: Any? = null
    private var at = 0L

    /** [words] told, of [step] (by default the words themselves: each different one a step of its own). */
    @Synchronized
    fun say(words: String, step: Any = words) {
        val now = ticks()
        if (words == said) return
        if (said != null && step == this.step && now - at < every) return
        said = words
        this.step = step
        at = now
        tell(words)
    }

    companion object {
        const val SECOND = 1_000_000_000L
    }
}
