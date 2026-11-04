package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.QueueReplay
import org.junit.Test

/** Every record of vectors/web/queue.jsonl and history.jsonl answered as caracole serve's queue and history answered
 * it: web/jobs.py's builders and rules, its queues op by op (the jobs after each, their history file), and history.py's
 * reads and writes, byte for byte (QueueReplay, which the device runs too: device-test.sh --area queue). */
class QueueVectorsTest {
    @Test fun theQueueAndItsHistoryAnswerAsCaracoleServesDo() {
        val misses = Misses("queue")
        QueueReplay.replay(misses)
        misses.assertNone()
    }
}
