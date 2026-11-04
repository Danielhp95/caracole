package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The job queue's command lines and rules (vectors/web/queue.jsonl, history.jsonl) (lane jobs-queue). Replays nothing until its lane fills it. */
object QueueReplay : AreaReplay {
    override val area = "queue"

    override fun replay(misses: Misses) {}
}
