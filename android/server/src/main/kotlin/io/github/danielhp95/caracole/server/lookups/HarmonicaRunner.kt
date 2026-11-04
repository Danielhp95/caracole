package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole harmonica --as` or `--clear` on the phone: a harmonica tab's reading pinned through
 * OverrideWriters.addHarmonica (checked by HarpTabs.checkSpec), then the song rendered again (lane
 * versions-harmonica). */
class HarmonicaRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane versions-harmonica")
}
