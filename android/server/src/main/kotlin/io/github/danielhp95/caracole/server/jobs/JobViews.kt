package io.github.danielhp95.caracole.server.jobs

import kotlinx.serialization.json.JsonObject

/** jobs_routes.view on the phone: a job as the page's line shows it (lane jobs). */
object JobViews {
    fun view(job: Job, queue: JobQueue, card: JsonObject? = null, songbooks: JsonObject? = null): JsonObject =
        TODO("lane jobs")
}
