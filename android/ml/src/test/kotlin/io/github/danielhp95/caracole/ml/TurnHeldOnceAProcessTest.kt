package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** The hearings' one turn ([MlChordModels.turn]) is a POSIX record lock of its file, which belongs to the process and
 * goes with ANY close of the file by it: so a turn held here stays held against other processes (a child JVM,
 * [HoldsTheTurn]) when a second asker of this process is refused, when the start's sweep finds it held, and when a
 * turn already given back is closed again. */
class TurnHeldOnceAProcessTest {
    @get:Rule val tmp = TemporaryFolder()

    /** Whether another process takes [turn]'s lock now (it lets go of it at once). */
    private fun childTakesIt(turn: File): Boolean {
        val java = File(System.getProperty("java.home"), "bin/java").path
        val child = ProcessBuilder(java, "-cp", System.getProperty("java.class.path"), HoldsTheTurn::class.java.name,
                                   turn.path).redirectErrorStream(true).start()
        val line = child.inputStream.bufferedReader().readLine()
        child.outputStream.close()
        child.waitFor()
        return line == "held"
    }

    @Test fun aTurnHeldHereStaysHeldAgainstOtherProcessesAfterASecondAskHereIsRefused() {
        val turn = tmp.newFile("turn")
        val held = MlChordModels.turn(turn)!!
        try {
            assertEquals("control: another process is refused while this one holds the turn", false, childTakesIt(turn))
            assertNull("a second ask of this process is refused", MlChordModels.turn(turn))
            assertEquals("another process must still be refused: the first hearing still holds the turn", false,
                childTakesIt(turn))
        } finally {
            held.close()
        }
        assertEquals("given back, another process takes it", true, childTakesIt(turn))
    }

    @Test fun theStartsSweepUnderAHeldTurnLeavesItHeldAgainstOtherProcesses() {
        val turn = tmp.newFile("turn")
        val work = tmp.newFolder("autochords")
        val held = MlChordModels.turn(turn)!!
        try {
            assertEquals(emptyList<String>(), MlChordModels.sweepOld(work, System.currentTimeMillis(), turn))
            assertEquals("another process must still be refused", false, childTakesIt(turn))
        } finally {
            held.close()
        }
    }

    /** Closing a turn again (it was given back already) lets go of nothing of the turn taken after it. */
    @Test fun aTurnClosedTwiceGivesBackItsOwnTurnAlone() {
        val turn = tmp.newFile("turn")
        val first = MlChordModels.turn(turn)!!
        first.close()
        val second = MlChordModels.turn(turn)!!
        try {
            first.close()
            assertNull("the second still holds it here", MlChordModels.turn(turn))
            assertEquals("and against other processes", false, childTakesIt(turn))
        } finally {
            second.close()
        }
        assertNotNull("given back", MlChordModels.turn(turn)?.also { it.close() })
    }
}
