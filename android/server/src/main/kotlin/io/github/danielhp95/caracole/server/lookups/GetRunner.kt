package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole get --progress -- ARTIST TITLE` on the phone: one song looked up now (core.lookup.Lookup), its stages its job's (lane lookup). */
class GetRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane lookup")
}
