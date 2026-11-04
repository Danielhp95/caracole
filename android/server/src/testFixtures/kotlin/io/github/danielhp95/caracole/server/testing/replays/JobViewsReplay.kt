package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobUnit
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.server.jobs.SongFacts
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import java.nio.file.Files
import java.time.Instant

/**
 * Every job's line, chips and outcome (vectors/web/job_views.jsonl, job_views_kinds.jsonl and outcome.jsonl), each
 * record's job held as the phone holds it (tests/test_conformance_web.py's and test_conformance_sync_routes.py's
 * docstrings say each field) and answered as caracole serve answered it: jobs_routes.view by JobViews.view; status.py's
 * line (with no to-do page), outcome.steps, progress and outcome by Status and Outcomes; the words both look up by a
 * name (outcome.jsonl's `tables`) as Status's and Outcomes' tables; and what the library knows of a job's song
 * (job_views_song_of.jsonl: jobs_routes.song_of) by SongFacts.songOf, over each record's fixture in a database of its
 * own.
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
        for (r in Corpus.records("web/outcome.jsonl")) if (r.fn == "tables") tables(misses, r) else outcome(misses, r)
        for (r in Corpus.records("web/job_views_song_of.jsonl")) songOf(misses, r)
    }

    /** The words status.py and outcome.py look up by a stage's, a step's or a command's name, whole. */
    private fun tables(misses: Misses, r: Record) {
        fun texts(m: Map<String, String>) = JsonObject(m.mapValues { JsonPrimitive(it.value) })
        fun steps(l: List<Pair<String, List<String>>>) = JsonArray(l.map { (name, stages) ->
            JsonArray(listOf(JsonPrimitive(name), JsonArray(stages.map(::JsonPrimitive))))
        })
        val seen = mapOf(
            "STAGE_LINES" to texts(Status.STAGE_LINES), "PEER_KINDS" to texts(Status.PEER_KINDS),
            "PEER_DONE" to texts(Status.PEER_DONE), "SHEET_LINES" to texts(Status.SHEET_LINES),
            "READ_TONES" to texts(Status.READ_TONES), "SONGBOOK_DONE" to texts(Status.DONE),
            "SONGBOOK_OPENS" to JsonArray(Status.OPENS.sorted().map(::JsonPrimitive)),
            "LOOKUP_STEPS" to steps(Outcomes.LOOKUP_STEPS), "YOUTUBE_STEPS" to steps(Outcomes.YOUTUBE_STEPS),
            "COMMAND_STEPS" to texts(Outcomes.COMMAND_STEPS), "PEER_STEPS" to texts(Outcomes.PEER_STEPS),
            "ASKS" to texts(Outcomes.ASKS), "ELSEWHERE" to texts(Outcomes.ELSEWHERE),
            "WHAT" to JsonObject(Outcomes.WHAT.mapValues { (_, said) ->
                JsonArray(listOf(JsonPrimitive(said.first), JsonPrimitive(said.second)))
            }),
        )
        val python = r.out!!.jsonObject
        misses.check(seen.keys == python.keys) { "tables: ${seen.keys}, Python's ${python.keys}" }
        for ((name, table) in seen) misses.check(table == python[name]) { "$name: $table, Python's ${python[name]}" }
    }

    /** jobs_routes.song_of over the record's library (its fixture), its songs' sheets the record's (as the phone's
     * cards give them), at its `now`: the song's id and its facts, or what stands for the exception Python raised. */
    private fun songOf(misses: Misses, r: Record) {
        val held = r.extra.getValue("job").jsonObject
        val job = jobOf(misses, held) ?: return
        val sheets = r.extra.getValue("sheets").jsonArray.associate { pair ->
            pair.jsonArray[0].jsonPrimitive.long to (pair.jsonArray[1] as? JsonPrimitive)?.contentOrNull
        }
        val cards = object : SongCards {
            override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = songs.associate { song ->
                val file = sheets[song.id]?.let { href ->
                    JsonObject(mapOf("primary" to JsonPrimitive(true), "href" to JsonPrimitive(href)))
                }
                song.id to JsonObject(mapOf("files" to JsonArray(listOfNotNull(file))))
            }
        }
        val now = Instant.parse(r.extra.getValue("now").jsonPrimitive.content)
        val note = r.extra["note"]?.jsonPrimitive?.content
        val dir = Files.createTempDirectory("caracole-song-of").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, r.extra.getValue("fixture").jsonArray.map { it.jsonObject })
                }
                val answer = try {
                    database.read { db -> SongFacts.songOf(db, job, cards, now) }
                } catch (e: IllegalArgumentException) {
                    misses.check(r.err == "ValueError") { "$note: threw $e, Python answered ${r.out ?: r.err}" }
                    return
                }
                val seen = JsonArray(listOf(answer.first?.let(::JsonPrimitive) ?: JsonNull, factsJson(answer.second)))
                misses.check(r.err == null && seen == r.out) { "$note: $seen, Python's ${r.out ?: r.err}" }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** status.SongFacts as the vectors write it (dataclasses.asdict), or null. */
    private fun factsJson(facts: SongFacts?): JsonElement {
        if (facts == null) return JsonNull
        fun text(value: String?) = value?.let(::JsonPrimitive) ?: JsonNull
        return JsonObject(mapOf(
            "sheet" to text(facts.sheet), "review" to JsonPrimitive(facts.review),
            "not_found" to JsonPrimitive(facts.notFound), "checked_now" to JsonPrimitive(facts.checkedNow),
            "ignored" to JsonPrimitive(facts.ignored), "picker" to text(facts.picker),
            "lacuerda" to JsonPrimitive(facts.lacuerda),
            "elsewhere" to (facts.elsewhere?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) }
                ?: JsonNull),
            "asked_ug" to JsonPrimitive(facts.askedUg), "sheet_from" to JsonPrimitive(facts.sheetFrom),
        ))
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
