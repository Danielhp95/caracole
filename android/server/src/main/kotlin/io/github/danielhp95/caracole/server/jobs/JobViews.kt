package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * jobs_routes.view on the phone: a job as `/jobs.json` gives it to the library page's script, which follows it on a
 * song's line, or in the Sync tab (sync.js), exactly as it follows caracole serve's. Every record of
 * vectors/web/job_views*.jsonl, Python's view of the same job, is what this answers (JobViewsReplay).
 *
 * A job of commands (a lookup, a sheet's versions, a site's index read, a songbook's change, a review's answer, a
 * harmonica tab's reading, Make this my version, a removal, a pull…) is read as caracole serve reads it: its line is
 * Status's (status.job_line, with no to-do page), a lookup's steps and count Outcomes.progress', a sync's or a take's
 * stages its steps and what it took, gave and left its outcome (jobs_routes.peer_outcome).
 *
 * A job of the phone's own (a run, no command) is read as Shape says, its view as milestone 3 made it:
 * - `kind` is what it is about, as the page reads it: an add is a song's ("song"), a removal "remove", a sync
 *   "sync", an index import "index" (the phone's alone), PhoneKinds' their own;
 * - a sync, a take, an index import and a merge are staged ([STAGED]): their stages are their steps, each named as
 *   the Requests tab names it ([stepName]), with `count` null and, once over, their `outcome` (§5.3);
 * - its line once done is its JobSpec's [JobSpec.doneLine] when it has one ("Added: the nightly run looks for it"); an
 *   index import says "Merged" or "Nothing newer to merge"; PhoneKinds' say their table's words, the ones
 *   their run filled in as their stage's detail (§5.3's table: "Making the pages again: 3 of 10", "Pages made again
 *   for 12 songs", "Not filed: why").
 * - `details` is the request's output in the Requests tab (`#tab=requests&job=N`), but a sync's, which the Sync tab
 *   shows (`#tab=sync`).
 */
object JobViews {
    const val REQUESTS = Status.REQUESTS
    const val SYNC_TAB = "#tab=sync"
    const val REMOVING = JobCommands.REMOVING  // a removal's key: the song's key after it

    /** The page's kind of each JobSpec.kind of the phone's own (none here: the same word). */
    private val KINDS = mapOf("add" to "song")

    /** The phone's own kinds whose view carries its stages, its count and its outcome (§5.3's shape). */
    internal val STAGED = setOf("sync", "peer-push", "index", Status.INDEX_MERGE_KIND)

    /** The kinds whose outcome is what they took, gave and left (jobs_routes.peer_outcome). */
    private val SYNCS = setOf("sync", "peer-push")

    /** The phone's index import's running line (its "merge" stage), apart from another caracole's index pages merged. */
    private const val INDEX_LINE = "Merging the computer's index"

    /** `caracole peer sync`'s and `take`'s agree stage, done: how many units the two agree on. */
    private val AGREED = PyRegex.compile("""^(\d+) units? the two agree on$""")

    /** The job's output in the library page's Requests tab, open (status.py's details_href). */
    fun detailsHref(id: Int): String = Status.detailsHref(id)

    /** The page's kind of a job (jobs_routes.view's `kind`). */
    fun kindOf(job: Job): String = kindOf(Shape(job))

    private fun kindOf(shape: Shape): String {
        val job = shape.job
        if (shape.own) return KINDS[job.spec.kind] ?: job.spec.kind
        val key = job.key
        return shape.peer ?: when {
            key.startsWith(JobCommands.REMOVING) -> "remove"
            key.startsWith(JobCommands.EXPORTING) || key.startsWith(JobCommands.READING) -> "export"
            Status.songbookOf(key) != null -> "songbook"
            else -> "song"
        }
    }

    /** [view] with the jobs before a queued one counted in [queue], and its song the one the job knows. */
    fun view(job: Job, queue: JobQueue, card: JsonObject? = null, songbooks: JsonObject? = null,
             facts: SongFacts? = null, songbookPage: String? = null): JsonObject =
        view(job, if (job.state == Job.QUEUED) queue.ahead(job) else 0,
             (card?.get("id") as? JsonPrimitive)?.content?.toLongOrNull() ?: job.songId, card, songbooks, facts,
             songbookPage)

    /**
     * A job as `/jobs.json` gives it; [ahead], the jobs waiting or running before a queued one; [songId], the song it
     * is about as the library has it now (jobs_routes.song_of, SongFacts.songOf), or null; [card], its song's card
     * as the page draws it now, for a job over ([SongCards]); [songbooks], the Songbooks tab's data as it is now;
     * [facts], what the library knows of its song (SongFacts.songOf); [songbookPage], a songbook's change's page.
     */
    fun view(job: Job, ahead: Int, songId: Long?, card: JsonObject? = null, songbooks: JsonObject? = null,
             facts: SongFacts? = null, songbookPage: String? = null): JsonObject {
        val shape = Shape(job)
        val kind = kindOf(shape)
        val line = line(shape, ahead, facts, songbookPage)
        val shown = if (kind == "song") Status.songLine(line) else line
        val seen = linkedMapOf<String, JsonElement>(
            "id" to JsonPrimitive(job.id),
            "display" to JsonPrimitive(job.display),
            "songId" to (songId?.let(::JsonPrimitive) ?: JsonNull),
            "kind" to JsonPrimitive(kind),
            "state" to JsonPrimitive(job.state),
            "fetching" to JsonPrimitive(job.fetching),
            "line" to shown.asJson(),
            "details" to JsonPrimitive(if (kind == "sync") SYNC_TAB else detailsHref(job.id)),
        )
        val staged = if (shape.own) kind in STAGED else shape.peer in listOf("sync", "peer-push", Status.INDEX_MERGE_KIND)
        if (staged) {
            seen["steps"] = JsonArray(job.stages.map { stage ->
                JsonObject(linkedMapOf("name" to JsonPrimitive(stage.name),
                                       "label" to JsonPrimitive(stepName(kind, stage)),
                                       "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail)))
            })
            seen["count"] = JsonNull
            seen["outcome"] = if (shape.own) ownOutcome(job, kind) else if (kind in SYNCS) peerOutcome(shape) else JsonNull
        }
        if (shown != line && line.link != null) seen["sheet"] = JsonPrimitive(line.link.second)
        if (kind == "song") seen.putAll(Outcomes.progress(shape, line, facts))
        val songbook = if (shape.own) null else Status.songbookOf(job.key)
        val identified = if (shape.own) kind == "song" || kind == "remove" else songbook == null
        if (songId != null && identified) seen["identity"] = JsonPrimitive(Status.songKeyOf(job.key))
        if (songbook != null) seen["songbook"] = songbook.asJson()
        if (songbooks != null) seen["songbooks"] = songbooks
        if (card != null) seen["card"] = card
        return JsonObject(seen)
    }

    /** What a staged job of the phone's own did, once over: its outcome as its run set it (a sync's or a take's, if
     * it set none before it ended, nothing taken, given or left); null while it waits or runs. */
    private fun ownOutcome(job: Job, kind: String): JsonElement {
        if (job.active) return JsonNull
        job.outcome?.let { return it }
        if (kind !in SYNCS) return JsonNull
        return JsonObject(linkedMapOf("taken" to JsonArray(emptyList()), "given" to JsonArray(emptyList()),
                                      "left" to JsonArray(emptyList()), "agreed" to JsonNull,
                                      "indexed" to JsonArray(emptyList())))
    }

    /** jobs_routes.peer_outcome: what a sync or a take of commands did, once over, from the units it said. */
    private fun peerOutcome(job: Shape): JsonElement {
        if (job.job.active) return JsonNull
        val agree = job.stages.firstOrNull { it.name == "agree" && it.state == Job.DONE }
        val count = agree?.let { AGREED.find(PyText.strip(it.detail)) }
        fun ids(said: String) = JsonArray(job.units.filter { it.outcome == said }.map { JsonPrimitive(it.id) })
        return JsonObject(linkedMapOf(
            "taken" to ids("taken"), "given" to ids("given"),
            "left" to JsonArray(job.units.filter { it.outcome == "left" }.map {
                JsonArray(listOf(JsonPrimitive(it.id), JsonPrimitive(it.why)))
            }),
            "agreed" to (count?.let { PyInt.parse(it.groupValues[1]) }?.let(::JsonPrimitive) ?: JsonNull),
            "indexed" to JsonArray(emptyList()),
        ))
    }

    /** The job's line (status.py's job_line, the phone's own kinds as the class says); [ahead], the jobs before a
     * queued one; [facts], what the library knows of its song; [songbookPage], a songbook's change's page. */
    fun line(job: Job, ahead: Int = 0, facts: SongFacts? = null, songbookPage: String? = null): Line =
        line(Shape(job), ahead, facts, songbookPage)

    private fun line(shape: Shape, ahead: Int, facts: SongFacts?, songbookPage: String?): Line {
        if (shape.own) ownLine(shape)?.let { return it }
        return Status.line(shape, facts, ahead, songbookPage, todo = null)
    }

    /** The words of the phone's own kinds where they are not caracole serve's; null where they are. */
    private fun ownLine(shape: Shape): Line? {
        val job = shape.job
        val details = detailsHref(job.id)
        PhoneKinds.ALL[job.spec.kind]?.let { return phoneLine(job, it, details) }
        if (job.state == Job.RUNNING && job.spec.kind == "index") {
            return Line("running", Status.stageLine(job.stages, lines = Status.STAGE_LINES + ("merge" to INDEX_LINE)))
        }
        if (job.state != Job.DONE) return null
        job.spec.doneLine?.let { return Line(if (job.spec.kind == "remove") "removed" else "added", it) }
        if (job.spec.kind == "index") {
            return Line("added", if ((job.outcome?.get("changed") as? JsonPrimitive)?.content == "true") "Merged"
                                 else "Nothing newer to merge")
        }
        return null
    }

    /** A job of PhoneKinds' (§5.3's table): while it runs, its stage's words, else its kind's running line (its
     * stage's label while that has blanks to fill); once done, its stage's words, else its kind's; failed, its failed
     * stage's words, else its error line's; a done line in the kind's second way to end ([PhoneKinds.Kind.otherwise])
     * is a wait. */
    private fun phoneLine(job: Job, kind: PhoneKinds.Kind, details: String): Line? {
        val stage = job.stages.firstOrNull { it.name == kind.stage.first }
        return when (job.state) {
            Job.RUNNING -> {
                val said = stage?.detail?.takeIf { stage.state == Job.RUNNING && it.isNotEmpty() }
                Line("running", said ?: if ('{' in kind.running) "${kind.stage.second}…" else kind.running)
            }
            Job.DONE -> {
                val said = stage?.detail?.takeIf { it.isNotEmpty() } ?: kind.done.takeIf { '{' !in it } ?: "Done"
                val waits = kind.otherwise?.substringBefore('{')?.let { it.isNotEmpty() && said.startsWith(it) } == true
                if (waits) Line("waiting", said, details = details) else Line("ready", said)
            }
            Job.FAILED -> Line("failed", Status.stageFailure(job.stages) ?: Status.failure(Shape(job).steps),
                               details = details)
            else -> null
        }
    }

    /** A staged job's step's name, as outcome.py's PEER_STEPS names it: the phone's index import keeps its stage's
     * label ("Merging the index"), and PhoneKinds' too. */
    internal fun stepName(kind: String, stage: Stage): String = when {
        kind in PhoneKinds.ALL -> stage.label
        kind == "index" && stage.name == "merge" -> stage.label
        else -> Outcomes.PEER_STEPS[stage.name] ?: stage.label
    }
}
