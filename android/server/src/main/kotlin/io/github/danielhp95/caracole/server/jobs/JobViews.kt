package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.server.http.PyText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

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
 * song's line, or in the Sync tab (sync.js), exactly as it follows caracole serve's.
 *
 * - `kind` is what it is about, as the page reads it: an add is a song's ("song"), a removal "remove", a sync "sync"
 *   (the computer's take of a push, "peer-push"), an index import "index".
 * - Its `line` is status.py's job_line: "Queued…", or "Queued behind 2 requests…"; while it runs, its running stage's
 *   line ([STAGE_LINES], else the stage's label) with "…"; then how it ended: "Cancelled", "Interrupted", a failure in
 *   its failed stage's words or its `error:` line's first sentence, or what it did, by its kind ([done]).
 * - `details` is the request's output in the Requests tab (`#tab=requests&job=N`), but a sync's, which the Sync tab
 *   shows (`#tab=sync`): the phone has no Requests tab, and tabs.js falls back to the library for one it lacks.
 * - A sync's view (and every staged kind's) has its stages as `steps`, `count` null and its `outcome` (§5.3); a song's
 *   and a removal's name the song by its `identity` (the job's key) once its id is known, as Python's do.
 *
 * The words of a sync's and a peer-push's lines are the plan's (status.py has them once lane sync-tab gives the
 * computer its sync routes); vectors/web/job_views.jsonl, which Python writes, is what this answers to.
 */
object JobViews {
    const val REQUESTS = "#tab=requests"
    const val SYNC_TAB = "#tab=sync"
    const val REMOVING = "remove:"  // a removal's key: the song's key after it, so it never joins the song's add
    private const val MAX_TEXT = 160  // characters of an error's sentence

    /** The page's kind of each JobSpec.kind (none here: the same word). */
    private val KINDS = mapOf("add" to "song")

    /** The kinds whose view carries its stages, its count and its outcome (§5.3's shape). */
    private val STAGED = setOf("sync", "peer-push", "index")

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
        "merge" to "Merging the computer's index",
    )

    /** The job's output in the library page's Requests tab, open (status.py's details_href). */
    fun detailsHref(id: Int): String = "$REQUESTS&job=$id"

    /** The page's kind of a job. */
    fun kindOf(job: Job): String = KINDS[job.spec.kind] ?: job.spec.kind

    /**
     * A job as `/jobs.json` gives it; [queue], the whole queue, for the jobs ahead of a queued one; [card], its song's
     * card as the page draws it now, for a job over ([SongCards]); [songbooks], the Songbooks tab's data as it is now.
     */
    fun view(job: Job, queue: JobQueue, card: JsonObject? = null, songbooks: JsonObject? = null): JsonObject {
        val kind = kindOf(job)
        val songId = (card?.get("id") as? JsonPrimitive)?.longOrNull ?: job.songId
        val seen = linkedMapOf<String, JsonElement>(
            "id" to JsonPrimitive(job.id),
            "display" to JsonPrimitive(job.display),
            "songId" to (songId?.let(::JsonPrimitive) ?: JsonNull),
            "kind" to JsonPrimitive(kind),
            "state" to JsonPrimitive(job.state),
            "fetching" to JsonPrimitive(false),
            "line" to line(job, if (job.state == Job.QUEUED) queue.ahead(job) else 0).asJson(),
            "details" to JsonPrimitive(if (kind == "sync") SYNC_TAB else detailsHref(job.id)),
        )
        if (kind in STAGED) {
            seen["steps"] = job.asJson()["steps"]!!
            seen["count"] = JsonNull
            seen["outcome"] = job.outcome ?: JsonNull
        }
        if (songId != null && (kind == "song" || kind == "remove")) {
            seen["identity"] = JsonPrimitive(job.spec.key.removePrefix(REMOVING))
        }
        if (card != null) seen["card"] = card
        if (songbooks != null) seen["songbooks"] = songbooks
        return JsonObject(seen)
    }

    /** The job's line (status.py's job_line); [ahead], the jobs before a queued one. */
    fun line(job: Job, ahead: Int = 0): Line {
        val details = detailsHref(job.id)
        return when (job.state) {
            Job.QUEUED -> Line("queued", if (ahead > 0) "Queued behind ${plural(ahead, "request")}…" else "Queued…")
            Job.RUNNING -> Line("running", stageLine(job.stages))
            Job.CANCELLED -> Line("cancelled", "Cancelled")
            Job.INTERRUPTED -> Line("waiting", "Interrupted", details = details)
            Job.FAILED -> Line("failed", stageFailure(job.stages) ?: failure(job), details = details)
            else -> done(job, details)
        }
    }

    /** What a job that is done did, by its kind. */
    private fun done(job: Job, details: String): Line {
        job.spec.doneLine?.let { return Line(if (job.spec.kind == "remove") "removed" else "added", it) }
        val left = (job.outcome?.get("left") as? JsonArray)?.size ?: 0
        return when (job.spec.kind) {
            "remove" -> Line("removed", "Removed")
            "add" -> Line("added", "Added: the nightly run looks for it")
            "sync" -> if (left > 0) Line("waiting", "Synced: ${leftAsItWas(left)}", details = details)
                      else Line("ready", "Synced")
            "peer-push" -> if (left > 0) Line("waiting", "Taken: ${leftAsItWas(left)}", details = details)
                           else Line("ready", "Taken")
            "index" -> Line("added", if ((job.outcome?.get("changed") as? JsonPrimitive)?.content == "true") "Merged"
                                     else "Nothing newer to merge")
            else -> Line("added", "Done")
        }
    }

    /** A running job's line: its running stage's, else the next one's, as between two stages (status.py's
     * _stage_line). */
    private fun stageLine(stages: List<Stage>): String {
        val stage = stages.firstOrNull { it.state == Job.RUNNING } ?: stages.firstOrNull { it.state == Job.WAITING }
            ?: return "Running…"
        return "${STAGE_LINES[stage.name] ?: stage.label}…"
    }

    /** A failure in its failed stage's words (status.py's _stage_failure); null without one. */
    private fun stageFailure(stages: List<Stage>): String? {
        val failed = stages.firstOrNull { it.state == Job.FAILED && it.detail.isNotEmpty() } ?: return null
        val said = short(firstSentence(PyText.strip(failed.detail)))
        return if (listOf(".", "!", "?", "…").any(said::endsWith)) said else "$said."
    }

    /** A failure in its last `error:` line's first sentence (status.py's _failure), else its title's. */
    private fun failure(job: Job): String {
        val said = job.output.asReversed().firstNotNullOfOrNull { ERROR.matchEntire(it)?.groupValues?.get(1) }
            ?.let { PyText.strip(it) }
        if (said.isNullOrEmpty()) return "${job.spec.title} failed."
        return short(firstSentence(said))
    }

    private val ERROR = Regex("""(?:<\d>)?error: (.+)""")

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

    private fun leftAsItWas(n: Int): String = "${plural(n, "change")} left as ${if (n == 1) "it was" else "they were"}"

    private fun plural(n: Int, noun: String): String = "$n ${if (n == 1) noun else noun + "s"}"
}
