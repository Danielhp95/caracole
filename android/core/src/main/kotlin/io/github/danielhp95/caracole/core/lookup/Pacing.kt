package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.http.Draws
import java.time.Instant
import kotlin.random.Random

/** The clocks and the pause a lookup keeps, a test's to fix: [REAL] sleeps, draws and reads the clocks. */
data class Pacing(val sleep: (Double) -> Unit, val draws: Draws, val wallSeconds: () -> Double,
                  val monotonic: () -> Double, val clock: () -> Instant) {
    companion object {
        val REAL: Pacing = Pacing(
            sleep = { seconds -> if (seconds > 0) Thread.sleep((seconds * 1000).toLong()) },
            draws = Draws { low, high -> low + (high - low) * Random.nextDouble() },
            wallSeconds = { System.currentTimeMillis() / 1000.0 },
            monotonic = { System.nanoTime() / 1e9 },
            clock = { Instant.now() },
        )
    }
}
