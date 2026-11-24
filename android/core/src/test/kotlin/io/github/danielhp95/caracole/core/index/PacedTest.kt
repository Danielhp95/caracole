package io.github.danielhp95.caracole.core.index

import org.junit.Test
import kotlin.test.assertEquals

/** Paced: a step's first words at once, a count at most once a second, and the step's last count always said, as the
 * next step comes or at a flush. */
class PacedTest {
    private val told = ArrayList<String>()
    private var tick = 0L
    private val paced = Paced({ told += it }, ticks = { tick })

    @Test fun aStepsFirstAndLastCountsAreSaidAndThoseBetweenAtMostOnceASecond() {
        paced.say("1 of 4", "download")
        paced.say("2 of 4", "download")
        tick += Paced.SECOND
        paced.say("3 of 4", "download")  // a second on: said
        paced.say("4 of 4", "download")  // held, the step's last so far
        assertEquals(listOf("1 of 4", "3 of 4"), told)
        paced.say("Comparing", "plan")  // the next step: the one before's last count first
        assertEquals(listOf("1 of 4", "3 of 4", "4 of 4", "Comparing"), told)
    }

    @Test fun aFlushSaysTheLastCountHeldAndNothingWhenNoneIs() {
        paced.say("10 of 52 MB", "download")
        paced.say("52 of 52 MB", "download")
        paced.flush()
        paced.flush()
        assertEquals(listOf("10 of 52 MB", "52 of 52 MB"), told)
        paced.say("52 of 52 MB", "download")  // the same words: never twice in a row
        assertEquals(listOf("10 of 52 MB", "52 of 52 MB"), told)
    }

    @Test fun aCountAlreadySaidIsNeverHeld() {
        paced.say("1 of 2", "x")
        tick += Paced.SECOND
        paced.say("2 of 2", "x")
        paced.say("Next", "y")
        assertEquals(listOf("1 of 2", "2 of 2", "Next"), told)
    }
}
