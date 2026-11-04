package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole render --song --version --mine` on the phone: Make this my version (Versions.entry through
 * OverrideWriters.addVersion), then the song rendered again (lane export-print). */
class RenderRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane export-print")
}
