package io.github.danielhp95.caracole.server.jobs

import java.io.File
import java.time.Instant

/** web/history.py on the phone: `stateDir/requests.jsonl`, its format 1 and rules (the last 100 requests of 30 days
 * read back, one that waited or ran then interrupted). */
class JobHistory(val file: File) {
    fun load(now: Instant): List<Job> = TODO("lane jobs-queue")
    fun save(job: Job): Unit = TODO("lane jobs-queue")
    fun rewrite(jobs: List<Job>): Unit = TODO("lane jobs-queue")
}
