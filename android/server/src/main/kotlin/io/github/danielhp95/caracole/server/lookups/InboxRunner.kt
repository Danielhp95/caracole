package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole inbox` (the phone's own, PhoneKinds' inbox kind): a file shared to the app, staged in
 * `stateDir/inbox/`, filed as `_inbox/` files it (core.inbox; lane inbox-share). */
class InboxRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane inbox-share")
}

/**
 * The files staged in `stateDir/inbox/` tried again after each sync and lookup, for 30 days, as `_inbox/` keeps a file
 * until a song fits (lane inbox-share): the phone calls [afterJob] after every job (Assembly). Neutral until its lane
 * lands: nothing is staged, so nothing is tried.
 */
class InboxRetry(val parts: PhoneParts) {
    fun afterJob(job: Job) {}
}
