package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole lacuerda --artist` and `--search` on the phone (lane lookup). */
class LaCuerdaRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane lookup")
}
