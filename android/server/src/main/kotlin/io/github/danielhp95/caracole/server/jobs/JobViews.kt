package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.server.http.PyText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** status.py's Line: how a request goes, in a word's tone (queued, running, ready, added, removed, waiting, failed,
 * cancelled), its text, where to go next ([link]: label, address) and, for a line that ends in a failure or a wait,
 * the request's output ([details]). */
data class Line(val tone: String, val text: String, val link: Pair<String, String>? = null,
                val details: String? = null) {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "tone" to JsonPrimitive(tone), "text" to JsonPrimitive(text),
        "link" to (link?.let { (label, href) ->
            JsonObject(linkedMapOf("label" to JsonPrimitive(label), "href" to JsonPrimitive(href)))
        } ?: JsonNull),
        "details" to (details?.let(::JsonPrimitive) ?: JsonNull),
    ))
}

/**
 * jobs_routes.view on the phone: a job as `/jobs.json` gives it to the library page's script, which follows it on a
 * song's line, or in the Sync tab (sync.js), exactly as it follows caracole serve's. Every record of
 * vectors/web/job_views.jsonl, Python's view of the same job, is what this answers (JobViewsTest).
 *
 * - `kind` is what it is about, as the page reads it: an add is a song's ("song"), a removal "remove", a sync "sync"
 *   (the computer's take of a push, "peer-push"), an index import "index" (the phone's alone).
 * - A sync, a take and an index import are staged ([STAGED]): their stages are their steps, each named as the
 *   Requests tab names it ([STEP_NAMES]), with `count` null and, once over, their `outcome` (§5.3); their failure is
 *   their failed stage's words, else their one command's (the job's title) `error:` line. An add and a removal are
 *   one command each, as caracole serve's are, whose stage stands for it: its label is what the line says while it
 *   runs ("Adding to the library…"), and its failure its `error:` line, else "<label> failed.".
 * - Its `line` is status.py's job_line: "Queued…", or "Queued behind 2 requests…"; while it runs, its running stage's
 *   line ([STAGE_LINES], else the stage's label) with "…"; then how it ended: "Cancelled", "Interrupted", a failure,
 *   or what it did, by its kind ([done]).
 * - `details` is the request's output in the Requests tab (`#tab=requests&job=N`), but a sync's, which the Sync tab
 *   shows (`#tab=sync`): the phone has no Requests tab, and tabs.js falls back to the library for one it lacks.
 * - A song's and a removal's view name the song by its `identity` (the job's key) once its id is known.
 */
object JobViews {
    const val REQUESTS = "#tab=requests"
    const val SYNC_TAB = "#tab=sync"
    const val REMOVING = "remove:"  // a removal's key: the song's key after it, so it never joins the song's add
    private const val MAX_TEXT = 160  // characters of an error's sentence

    /** The page's kind of each JobSpec.kind (none here: the same word). */
    private val KINDS = mapOf("add" to "song")

    /** The kinds whose view carries its stages, its count and its outcome (§5.3's shape). */
    private val STAGED = setOf("sync", "peer-push", "index", INDEX_MERGE)

    /** The kinds whose outcome is what they took, gave and left (jobs_routes.peer_outcome). */
    private val SYNCS = setOf("sync", "peer-push")

    /** What a running stage's line says, as status.py's STAGE_LINES (a stage not here says its label). */
    val STAGE_LINES = mapOf(
        "compare" to "Comparing",
        "take" to "Taking what changed there",
        "give" to "Giving what changed here",
        "mirror" to "Copying the computer's pages",
        "agree" to "Recording what the two agree on",
        "index" to "Bringing the indexes up to date",
        "check" to "Checking what changed since the comparison",
        "render" to "Rendering what was taken",
        "merge" to "Merging the computer's index",  // the phone's index import's
    )

    /** A staged job's step names, as outcome.py's PEER_STEPS names them (a stage not here keeps its label). */
    val STEP_NAMES = mapOf(
        "compare" to "Compare", "check" to "Check", "take" to "Take", "give" to "Give", "render" to "Render",
        "mirror" to "Pages", "agree" to "Agree", "index" to "Indexes",
    )

    /** How a sync and a take say they are done (status.py's _PEER_DONE). */
    private val DONE_WORDS = mapOf("sync" to "Synced", "peer-push" to "Taken", INDEX_MERGE to "Merged")

    /** The computer's kind of `caracole index merge --delete --progress` (web/jobs.py's index_merge_job): another
     * caracole's index pages merged, one stage, "merge", worded apart from the phone's own index import's. */
    private const val INDEX_MERGE = "index-merge"
    private const val INDEX_MERGE_LINE = "Merging the other caracole's index pages"
    private const val INDEX_MERGE_STEP = "Merge"

    /** The job's output in the library page's Requests tab, open (status.py's details_href). */
    fun detailsHref(id: Int): String = "$REQUESTS&job=$id"

    /** The page's kind of a job. */
    fun kindOf(job: Job): String = KINDS[job.spec.kind] ?: job.spec.kind

    /** [view] with the jobs before a queued one counted in [queue], and its song the one the job knows. */
    fun view(job: Job, queue: JobQueue, card: JsonObject? = null, songbooks: JsonObject? = null): JsonObject =
        view(job, if (job.state == Job.QUEUED) queue.ahead(job) else 0,
             (card?.get("id") as? JsonPrimitive)?.content?.toLongOrNull() ?: job.songId, card, songbooks)

    /**
     * A job as `/jobs.json` gives it; [ahead], the jobs waiting or running before a queued one; [songId], the song it
     * is about as the library has it now (jobs_routes.song_of: an add's by its key, a removal's by its key, else the
     * one it removed), or null; [card], its song's card as the page draws it now, for a job over ([SongCards]);
     * [songbooks], the Songbooks tab's data as it is now.
     */
    fun view(job: Job, ahead: Int, songId: Long?, card: JsonObject? = null, songbooks: JsonObject? = null): JsonObject {
        val kind = kindOf(job)
        val seen = linkedMapOf<String, JsonElement>(
            "id" to JsonPrimitive(job.id),
            "display" to JsonPrimitive(job.display),
            "songId" to (songId?.let(::JsonPrimitive) ?: JsonNull),
            "kind" to JsonPrimitive(kind),
            "state" to JsonPrimitive(job.state),
            "fetching" to JsonPrimitive(false),
            "line" to line(job, ahead).asJson(),
            "details" to JsonPrimitive(if (kind == "sync") SYNC_TAB else detailsHref(job.id)),
        )
        if (kind in STAGED) {
            seen["steps"] = JsonArray(job.stages.map { stage ->
                JsonObject(linkedMapOf("name" to JsonPrimitive(stage.name),
                                       "label" to JsonPrimitive(stepName(kind, stage)),
                                       "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail)))
            })
            seen["count"] = JsonNull
            seen["outcome"] = outcomeOf(job, kind)
        }
        if (songId != null && (kind == "song" || kind == "remove")) {
            seen["identity"] = JsonPrimitive(job.spec.key.removePrefix(REMOVING))
        }
        if (songbooks != null) seen["songbooks"] = songbooks
        if (card != null) seen["card"] = card
        return JsonObject(seen)
    }

    /** What a staged job did, once over: its outcome as its run set it (a sync's or a take's, if it set none before it
     * ended, nothing taken, given or left); null while it waits or runs. */
    private fun outcomeOf(job: Job, kind: String): JsonElement {
        if (job.active) return JsonNull
        job.outcome?.let { return it }
        if (kind !in SYNCS) return JsonNull
        return JsonObject(linkedMapOf("taken" to JsonArray(emptyList()), "given" to JsonArray(emptyList()),
                                      "left" to JsonArray(emptyList()), "agreed" to JsonNull,
                                      "indexed" to JsonArray(emptyList())))
    }

    /** The job's line (status.py's job_line); [ahead], the jobs before a queued one. */
    fun line(job: Job, ahead: Int = 0): Line {
        val details = detailsHref(job.id)
        val staged = kindOf(job) in STAGED
        return when (job.state) {
            Job.QUEUED -> Line("queued", if (ahead > 0) "Queued behind ${plural(ahead, "request")}…" else "Queued…")
            Job.RUNNING -> Line("running", if (staged) stageLine(job.stages, kindOf(job)) else commandLine(job.stages))
            Job.CANCELLED -> Line("cancelled", "Cancelled")
            Job.INTERRUPTED -> Line("waiting", "Interrupted", details = details)
            Job.FAILED -> Line("failed", if (staged) stageFailure(job.stages) ?: failure(job.spec.title, job.output)
                                         else failure(job.stages.firstOrNull { it.state == Job.FAILED }?.label,
                                                      job.output), details = details)
            else -> done(job, details)
        }
    }

    /** A staged job's step's name, as outcome.py's PEER_STEPS names it. */
    private fun stepName(kind: String, stage: Stage): String =
        if (kind == INDEX_MERGE && stage.name == "merge") INDEX_MERGE_STEP else STEP_NAMES[stage.name] ?: stage.label

    /** What a job that is done did, by its kind. */
    private fun done(job: Job, details: String): Line {
        job.spec.doneLine?.let { return Line(if (job.spec.kind == "remove") "removed" else "added", it) }
        val kind = job.spec.kind
        DONE_WORDS[kind]?.let { said ->  // status.py's _peer_done
            stageFailure(job.stages)?.let { return Line("waiting", it, details = details) }
            val left = (job.outcome?.get("left") as? JsonArray)?.size ?: 0
            if (left > 0) {
                return Line("waiting", "$said: ${plural(left, "change")} left as ${if (left == 1) "it was" else "they were"}",
                            details = details)
            }
            return Line("ready", said)
        }
        return when (kind) {
            "remove" -> Line("removed", "Removed")
            "add" -> Line("added", "Added: the nightly run looks for it")
            "index" -> Line("added", if ((job.outcome?.get("changed") as? JsonPrimitive)?.content == "true") "Merged"
                                     else "Nothing newer to merge")
            else -> Line("added", "Done")
        }
    }

    /** A running staged job's line: its running stage's, else the next one's, as between two stages (status.py's
     * _stage_line). */
    private fun stageLine(stages: List<Stage>, kind: String): String {
        val stage = stages.firstOrNull { it.state == Job.RUNNING } ?: stages.firstOrNull { it.state == Job.WAITING }
            ?: return "Running…"
        if (kind == INDEX_MERGE && stage.name == "merge") return "$INDEX_MERGE_LINE…"
        return "${STAGE_LINES[stage.name] ?: stage.label}…"
    }

    /** A running command's line: its label (status.py's for a job of steps), else the next one's. */
    private fun commandLine(stages: List<Stage>): String {
        val stage = stages.firstOrNull { it.state == Job.RUNNING } ?: stages.firstOrNull { it.state == Job.WAITING }
        return if (stage != null) "${stage.label}…" else "Running…"
    }

    /** A failure in its failed stage's words (status.py's _stage_failure): never what a stage the queue ended said
     * while it ran ([Stage.runningDetail]); null without one. */
    private fun stageFailure(stages: List<Stage>): String? {
        val failed = stages.firstOrNull { it.state == Job.FAILED && it.detail.isNotEmpty() && it.detail != it.runningDetail }
            ?: return null
        val said = short(firstSentence(PyText.strip(failed.detail)))
        return if (listOf(".", "!", "?", "…").any(said::endsWith)) said else "$said."
    }

    /** A failed command's words (status.py's _failure): its last `error:` line's first sentence, else "<[label]>
     * failed."; with no command failed ([label] null), that it stopped. */
    private fun failure(label: String?, output: List<String>): String {
        if (label == null) return "It stopped before it was done."
        val said = output.asReversed().firstNotNullOfOrNull(::errorOf)?.let(PyText::strip)
        if (said.isNullOrEmpty()) return "$label failed."
        return short(firstSentence(said))
    }

    /** What an `error:` line says (status.py's `^(?:<\d>)?error: (.+)$`, a journal priority before it); null for
     * any other line. */
    private fun errorOf(line: String): String? {
        var rest = line.removeSuffix("\n")
        if (rest.startsWith("<") && rest.length > 1) {
            val digit = rest.codePointAt(1)
            val after = 1 + Character.charCount(digit)
            if (PyText.isDigit(digit) && rest.startsWith(">error: ", after)) rest = rest.substring(after + 1)
        }
        if (!rest.startsWith("error: ")) return null
        val said = rest.substring("error: ".length)
        return said.takeIf { it.isNotEmpty() && '\n' !in it }
    }

    /** The text up to its first sentence's end: `(?<=[.!?])\s`, Python's whitespace. */
    private fun firstSentence(text: String): String {
        var i = 0
        var previous = -1
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (previous == '.'.code || previous == '!'.code || previous == '?'.code) {
                if (PyText.isSpace(cp)) return text.substring(0, i)
            }
            previous = cp
            i += Character.charCount(cp)
        }
        return text
    }

    /** status.py's _short: at most [MAX_TEXT] characters (code points), cut at a word with "…". */
    private fun short(text: String): String {
        if (text.codePointCount(0, text.length) <= MAX_TEXT) return text
        val head = text.substring(0, text.offsetByCodePoints(0, MAX_TEXT - 1))
        val cut = (if (' ' in head) head.substringBeforeLast(' ') else head).trimEnd(' ', ',', ';', ':')
        return "$cut…"
    }

    private fun plural(n: Int, noun: String): String = "$n ${if (n == 1) noun else noun + "s"}"
}
