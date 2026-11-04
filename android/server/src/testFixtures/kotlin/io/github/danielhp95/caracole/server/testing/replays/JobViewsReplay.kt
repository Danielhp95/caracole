package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobUnit
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.server.jobs.SongFacts
import io.github.danielhp95.caracole.server.jobs.Status
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.time.Instant

/**
 * Every job's line, chips and outcome (vectors/web/job_views.jsonl, job_views_kinds.jsonl and outcome.jsonl), each
 * record's job held as the phone holds it (tests/test_conformance_web.py's and test_conformance_sync_routes.py's
 * docstrings say each field) and answered as caracole serve answered it: jobs_routes.view by JobViews.view; status.py's
 * line (with no to-do page), outcome.steps, progress and outcome by Status and Outcomes.
 *
 * A record's job with `commands` is a job of commands, its stages those its commands report (JobCommands.stages,
 * checked against the record's names); one without is a job of the phone's own (a run), its stages the record's.
 */
object JobViewsReplay : AreaReplay {
    override val area = "job-views"

    override fun replay(misses: Misses) {
        for (name in listOf("web/job_views.jsonl", "web/job_views_kinds.jsonl")) {
            for (r in Corpus.records(name)) view(misses, r)
        }
        for (r in Corpus.records("web/outcome.jsonl")) outcome(misses, r)
    }

    private fun view(misses: Misses, r: Record) {
        val held = r.extra.getValue("job").jsonObject
        val job = jobOf(misses, held) ?: return
        val songId = held.getValue("song_id").jsonPrimitive.longOrNull
        val seen = JobViews.view(job, held.getValue("ahead").jsonPrimitive.int, songId,
                                 facts = SongFacts.of(r.extra["facts"]),
                                 songbookPage = (r.extra["songbook_page"] as? JsonPrimitive)?.contentOrNull)
        misses.check(seen == r.out) { "${held["kind"]}, ${r.extra["note"]}: ${seen}, Python's ${r.out}" }
    }

    private fun outcome(misses: Misses, r: Record) {
        val held = r.extra.getValue("job").jsonObject
        val job = jobOf(misses, held) ?: return
        val facts = SongFacts.of(r.extra["facts"])
        val line = Status.jobLine(job, facts, held.getValue("ahead").jsonPrimitive.int,
                                  (r.extra["songbook_page"] as? JsonPrimitive)?.contentOrNull, todo = null)
        val over = if (job.active) null else
            Outcomes.outcome(job, line, facts, held.getValue("song_id").jsonPrimitive.longOrNull)
        val seen = JsonObject(linkedMapOf(
            "line" to line.asJson(),
            "steps" to JsonArray(Outcomes.steps(job, facts).map { it.asJson() }),
            "progress" to JsonObject(Outcomes.progress(job, line, facts)),
            "outcome" to (over?.asJson() ?: JsonNull),
        ))
        misses.check(seen == r.out) { "${held["kind"]}, ${r.extra["note"]}: ${seen}, Python's ${r.out}" }
    }

    /** A record's job as the phone holds it; null (a miss said) when its commands report other stages. */
    fun jobOf(misses: Misses, held: JsonObject): Job? {
        fun text(name: String) = held.getValue(name).jsonPrimitive.content
        val stages = held.getValue("stages").jsonArray.map { it.jsonObject }
        val commands = (held["commands"] as? JsonArray)?.map { it.jsonObject }
        val spec = JobSpec(
            title = text("title"), key = text("key"), kind = text("kind"),
            stages = if (commands != null) emptyList() else stages.map {
                it.getValue("name").jsonPrimitive.content to it.getValue("label").jsonPrimitive.content
            },
            display = text("display"), songId = (held["job_song_id"] as? JsonPrimitive)?.longOrNull,
            fetching = (held["fetching"] as? JsonPrimitive)?.content == "true",
            note = (held["note"] as? JsonPrimitive)?.contentOrNull ?: "",
            commands = commands.orEmpty().map { c ->
                Command(c.getValue("label").jsonPrimitive.content, c.getValue("args").jsonArray.map { it.jsonPrimitive.content })
            },
            run = if (commands != null) null else ({ _ -> }),
        )
        val job = Job(held.getValue("id").jsonPrimitive.int, spec)
        if (job.stages.map { it.name } != stages.map { it.getValue("name").jsonPrimitive.content }) {
            misses.check(false) { "${held["kind"]}: stages ${job.stages.map { it.name }}, Python's $stages" }
            return null
        }
        job.state = text("state")
        job.stages.zip(stages).forEach { (stage, said) ->
            stage.state = said.getValue("state").jsonPrimitive.content
            stage.detail = said.getValue("detail").jsonPrimitive.content
            stage.runningDetail = said.getValue("running_detail").jsonPrimitive.content
        }
        if (commands != null) {
            job.steps.zip(commands).forEach { (step, said) ->
                step.state = said.getValue("state").jsonPrimitive.content
                step.code = (said["code"] as? JsonPrimitive)?.intOrNull
                step.output = said.getValue("output").jsonArray.map { it.jsonPrimitive.content }
            }
            job.startedAt = (held["started_at"] as? JsonPrimitive)?.contentOrNull?.let(Instant::parse)
            job.units = (held["units"] as? JsonArray).orEmpty().map { u ->
                val (id, outcome, why) = u.jsonArray.map { it.jsonPrimitive.content }
                JobUnit(id, outcome, why)
            }
        } else {
            job.output = held.getValue("output").jsonArray.map { it.jsonPrimitive.content }
            job.songId = held.getValue("song_id").jsonPrimitive.longOrNull
            job.outcome = held["outcome"] as? JsonObject
        }
        return job
    }
}
