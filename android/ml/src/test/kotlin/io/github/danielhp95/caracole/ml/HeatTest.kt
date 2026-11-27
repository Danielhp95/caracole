package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

/** The design's §3.4 table, [HeatRules], over readings given. */
class HeatTest {
    private fun reading(thermal: String = "none", headroom: Float? = null, percent: Int? = 80, plugged: Boolean? = false,
                        powerSave: Boolean? = false) =
        Heat.Reading(thermal, headroom, null, percent, plugged, powerSave)

    @Test fun coolAndWithHeadroomIsFourThreads() {
        for (thermal in listOf("none", "light", Heat.UNKNOWN)) {
            assertEquals(thermal, HeatRules.Go(4), HeatRules.between(reading(thermal)))
            assertEquals(thermal, HeatRules.Go(4), HeatRules.between(reading(thermal, headroom = 0.84f)))
        }
    }

    @Test fun moderateOrLittleHeadroomOrBatterySaverIsTwoThreads() {
        assertEquals(HeatRules.Go(2), HeatRules.between(reading("moderate")))
        assertEquals(HeatRules.Go(2), HeatRules.between(reading("light", headroom = 0.85f)))
        assertEquals(HeatRules.Go(2), HeatRules.between(reading("none", powerSave = true)))
    }

    @Test fun severeWaitsBetweenStagesAndGoesOnWithinOne() {
        assertEquals(HeatRules.Wait(HeatRules.COOLING), HeatRules.between(reading("severe")))
        assertEquals(HeatRules.Go(2), HeatRules.within(reading("severe")))
    }

    @Test fun criticalOrWorseStopsAtTheNextChunk() {
        for (thermal in listOf("critical", "emergency", "shutdown")) {
            assertEquals(thermal, HeatRules.Stop(HeatRules.TOO_HOT), HeatRules.between(reading(thermal)))
            assertEquals(thermal, HeatRules.Stop(HeatRules.TOO_HOT), HeatRules.within(reading(thermal)))
        }
    }

    @Test fun belowFifteenPercentAndNotChargingIsRefusedBeforeItStarts() {
        assertEquals(HeatRules.CHARGE_FIRST, HeatRules.start(reading(percent = 14, plugged = false)))
        assertEquals(HeatRules.CHARGE_FIRST, HeatRules.start(reading(percent = 14, plugged = null)))
        assertNull(HeatRules.start(reading(percent = 14, plugged = true)))
        assertNull(HeatRules.start(reading(percent = 15, plugged = false)))
        assertNull(HeatRules.start(reading(percent = null, plugged = false)))
        assertEquals("Charge the phone first: chords from audio need more than 15 % of the battery.",
            HeatRules.CHARGE_FIRST)
    }

    /** A gauge that reads [states] in turn (the last for ever), and a clock [sleep] moves on. */
    private class Scripted(vararg states: String) {
        private val left = ArrayDeque(states.toList())
        var now = 0L
        val slept = mutableListOf<Long>()
        val gauge = HeatGauge { Heat.Reading(if (left.size > 1) left.removeFirst() else left.first(), null, null, 80,
            false, false) }
        fun sleep(ms: Long) { slept += ms; now += ms }
    }

    @Test fun aSevereStateIsWaitedOutEveryTenSecondsSayingSoThenTheStageGoesOn() {
        val s = Scripted("severe", "severe", "moderate")
        val said = mutableListOf<String>()
        assertEquals(2, HeatRules.cool(s.gauge, s::sleep, { s.now }, said::add))
        assertEquals(listOf(10_000L, 10_000L), s.slept)
        assertEquals(listOf(HeatRules.COOLING), said)
    }

    @Test fun aStopAskedWhileTheHeatIsWaitedOutEndsTheWaitAtItsNextPoll() {
        val s = Scripted("severe")
        var polls = 0
        assertThrows(IllegalStateException::class.java) {
            HeatRules.cool(s.gauge, s::sleep, { s.now }, {}) { if (++polls == 3) throw IllegalStateException("stop") }
        }
        assertEquals(20_000L, s.now)
    }

    @Test fun aPhoneStillSevereAfterFiveMinutesIsTooHot() {
        val s = Scripted("severe")
        val e = assertThrows(TooHot::class.java) { HeatRules.cool(s.gauge, s::sleep, { s.now }, {}) }
        assertEquals(HeatRules.TOO_HOT, e.message)
        assertEquals(300_000L, s.now)
        assertEquals("the phone is too hot to work out chords now; try again once it cools", HeatRules.TOO_HOT)
    }

    @Test fun criticalWhileWaitingStopsAtOnce() {
        val s = Scripted("severe", "critical")
        assertThrows(TooHot::class.java) { HeatRules.cool(s.gauge, s::sleep, { s.now }, {}) }
        assertEquals(10_000L, s.now)
    }
}
