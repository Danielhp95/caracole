package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole backup` (the phone's own): a backup made (`--label`), or one restored (`--restore FILE`), through
 * core.backup, as PhoneKinds' backup and restore kinds (lane alerts-backups). */
class BackupRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane alerts-backups")
}
