package io.github.danielhp95.caracole.autochords.testing

import io.github.danielhp95.caracole.autochords.frontend.Soxr
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** :autochords' areas of the corpus (core.testing.Replays has :core's), which CorpusOnDeviceTest runs on the device. */
object AutochordsReplays {
    val all: List<AreaReplay> = listOf(AutochordsReplay)
}

/**
 * The area `autochords` (tests/test_conformance_autochords_models.py), the front ends' half: every soxr.jsonl
 * conversion by [Soxr] within its tolerance, of the same length (the design's B1 resample gate), and every
 * frontend.jsonl clip's and excerpt's log-CQT and every clip's log-mel by the Kotlin front ends within the B1 feature
 * gate (FrontendRecords). Each feature's score is told to [report] (the JVM's stdout; on the device, the
 * instrumentation's output), so a run says how close it came, not only that it passed.
 */
object AutochordsReplay : AreaReplay {
    override val area = "autochords"

    @JvmStatic
    var report: (String) -> Unit = { println(it) }

    override fun replay(misses: Misses) {
        for (c in SoxrRecords.conversions) {
            val worst = SoxrRecords.worst(Soxr.resample(c.x, c.from, c.to), c.y)
            misses.check(worst <= SoxrRecords.TOLERANCE) { "soxr ${c.what}: a sample differs by $worst" }
        }
        val gate = FrontendRecords.gate
        for (source in FrontendRecords.sources) {
            val scores = listOfNotNull(FrontendRecords.cqt(source), source.mel?.let { FrontendRecords.mel(source) })
            for (score in scores) {
                report("autochords: $score")
                misses.check(score.passes(gate)) { "$score: under the gate" }
            }
        }
    }
}
