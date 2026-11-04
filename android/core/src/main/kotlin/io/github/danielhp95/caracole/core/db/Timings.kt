package io.github.danielhp95.caracole.core.db

/**
 * How long each step of a piece of work took, for a benchmark or a device test to read (the first search after a
 * start, an import's merge and checkpoint: android/README.md's Performance notes), behind a debug flag: steps are
 * timed only while [enabled], which the system property `caracole.timings=1` turns on (or a test, by setting it), and
 * nothing a page or a job shows ever reads them. Off, [time] runs its block and records nothing.
 */
object Timings {
    /** One step: its name, and how long it took, in milliseconds. */
    data class Step(val name: String, val ms: Double) {
        override fun toString(): String = "$name ${Math.round(ms * 10) / 10.0} ms"
    }

    /** Whether steps are timed. */
    @Volatile
    var enabled: Boolean = System.getProperty("caracole.timings") == "1"

    private val steps = ArrayList<Step>()

    /** [block], timed as the step [name] while [enabled]. */
    fun <T> time(name: String, block: () -> T): T {
        if (!enabled) return block()
        val started = System.nanoTime()
        try {
            return block()
        } finally {
            val ms = (System.nanoTime() - started) / 1_000_000.0
            synchronized(steps) { steps.add(Step(name, ms)) }
        }
    }

    /** The steps timed since the last [take], in the order they ended; none kept after. */
    fun take(): List<Step> = synchronized(steps) { steps.toList().also { steps.clear() } }
}
