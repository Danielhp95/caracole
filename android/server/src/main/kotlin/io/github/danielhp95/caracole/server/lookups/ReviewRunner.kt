package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole review --song --pick` (or `--none`) `--seen` on the phone: an uncertain match accepted or rejected, the
 * song matched again, then a lookup when asked (lane review). */
class ReviewRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane review")
}
