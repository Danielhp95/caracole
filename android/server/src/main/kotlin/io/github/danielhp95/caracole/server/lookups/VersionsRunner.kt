package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole versions --keep`, `--keep-more`, `--choose` and `--clear` on the phone (lane lookup). */
class VersionsRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane lookup")
}
