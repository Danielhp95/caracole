package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** outcome.py's Chip: a step of a request, its state (waiting, running, done, failed; or plain, over and neither,
 * "Match · not on UG") and the site it names ([source], "" for none). */
data class Chip(val name: String, val state: String, val source: String = "") {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "name" to JsonPrimitive(name), "source" to JsonPrimitive(source), "state" to JsonPrimitive(state),
    ))
}

/** outcome.py's Action: the next step, a link ([href]) or a form posted to [post] with [fields] and the form token. */
data class Action(val label: String, val href: String? = null, val post: String? = null,
                  val fields: List<Pair<String, String>> = emptyList()) {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "label" to JsonPrimitive(label), "href" to (href?.let(::JsonPrimitive) ?: JsonNull),
        "post" to (post?.let(::JsonPrimitive) ?: JsonNull),
        "fields" to JsonArray(fields.map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) }),
    ))
}

/** outcome.py's Outcome: how a finished request ended, its tone, word, reason ("" for none), next step and a second
 * way on beside it. */
data class Outcome(val tone: String, val word: String, val reason: String = "", val action: Action? = null,
                   val also: Action? = null) {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "tone" to JsonPrimitive(tone), "word" to JsonPrimitive(word), "reason" to JsonPrimitive(reason),
        "action" to (action?.asJson() ?: JsonNull), "also" to (also?.asJson() ?: JsonNull),
    ))
}

/**
 * web/outcome.py on the phone: a request's steps as chips ([steps]), what the library page draws under a song's
 * request line ([progress]), and how a finished one ended ([outcome]), read from the job, its line (Status) and what
 * the library knows of its song (SongFacts), never anything else. vectors/web/outcome.jsonl holds them to Python's.
 *
 * A job of the phone's own is read as Shape says; one staged (a sync, an index import, PhoneKinds') draws its stages,
 * each not skipped, as a sync's are drawn.
 */
object Outcomes {
    /** A lookup's steps (get.py's STAGES), each a name and the stages it stands for. */
    val LOOKUP_STEPS: List<Pair<String, List<String>>> = listOf(
        "Song" to listOf("song"), "Match" to listOf("match"), "Sheet" to listOf("sheet"), "PDF" to listOf("pdf"),
        "Lyrics" to listOf("lyrics"), "Extras" to listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs"),
        "Songbooks" to listOf("songbooks"),
    )

    /** A sheet from a YouTube video's steps (youtube_sheet.STAGES). */
    val YOUTUBE_STEPS: List<Pair<String, List<String>>> = listOf(
        "Song" to listOf("song"), "Audio" to listOf("audio"), "Lyrics" to listOf("lyrics"),
        "Chords" to listOf("chords"), "PDF" to listOf("pdf"),
    )
    private const val YOUTUBE_SOURCE = "YouTube"

    /** A request of other commands: each command's step, by what it does. */
    val COMMAND_STEPS: Map<String, String> = mapOf(
        "add" to "Add", "match" to "Match", "fetch" to "Sheet", "render" to "PDF", "review" to "Your pick",
        "remove" to "Remove", "lacuerda" to "LaCuerda", "songbook" to "Songbook", JobCommands.LOOKUP to "Fetch",
    )

    /** A sync's, a take's and a merge's steps, by their stages' names (outcome.py's PEER_STEPS). */
    val PEER_STEPS: Map<String, String> = mapOf(
        "compare" to "Compare", "check" to "Check", "take" to "Take", "give" to "Give", "render" to "Pages",
        "mirror" to "Copy", "agree" to "Agree", "index" to "Indexes", "merge" to "Merge",
    )

    private val OVER = setOf(Job.DONE, Job.SKIPPED, Job.FAILED)
    private const val MATCHED_IN = "UG"
    const val NOT_ON_UG = "Match · not on UG"
    private const val MATCH_NOT_FOUND = "not in UG's index"  // get.py's
    private const val GTPTABS_KEPT = "Guitar Pro file downloaded"  // get.py's

    /** A running sheet stage's site, by its words (get.py's SHEET_FROM, icons.tag). */
    internal val ASKS = mapOf("from LaCuerda" to "LaCuerda", "from UG" to "UG")

    /** What a stage leaves for tonight's run when it ends in a wait or an error: its name, and its verb. */
    internal val WHAT = mapOf(
        "sheet" to ("the sheet" to "waits"), "lyrics" to ("the lyrics" to "wait"),
        "ug" to ("its other versions and tab" to "wait"), "lacuerda" to ("LaCuerda's sheet" to "waits"),
        "gtptabs" to ("the Guitar Pro file" to "waits"), "harptabs" to ("the harmonica tab" to "waits"),
        "gametabs" to ("the game music tab" to "waits"),
    )

    // How get.py words them (_Lookup.asking, _usable), as outcome.py reads them.
    private val FAILED = PyRegex.compile("""^(.+?) failed \((.*)\); tried again tonight$""")
    private val STATUS = PyRegex.compile("""^[\w.-]+: (\d{3})(?::|$)""")
    private val BLOCKED = PyRegex.compile("""^(.+?) turned us back\b(?:.*?No more asks until (.+?)\.(?:\s|$))?""")
    private val COOLING = PyRegex.compile("""^Waiting out (.+?) until (.+)$""")
    private val SPENT = PyRegex.compile("""^(.+); tonight's run does the rest$""")

    const val NO_CHORDS = "UG has no chords for it"
    const val NOT_INDEXED = "Not in UG's index under this name"
    const val NOT_ASKED = "UG not asked this time: waiting out a block, no asks left, or an error. The output says " +
        "which."
    const val IN_REVIEW = "Not sure which UG song it is."
    const val CANCELLED = "Cancelled before it ran."
    const val INTERRUPTED_RAN = "The server stopped mid-way. Try again to finish."
    const val INTERRUPTED_WAITED = "The server stopped before it ran. Try again runs it."
    internal val ELSEWHERE = mapOf("lacuerda" to "LaCuerda has a sheet",
                                  "gtptabs" to "gtptabs lists a page for it")
    private val NO_UNITS = setOf(Status.INDEX_MERGE_KIND)
    val COMPARE_AGAIN = Action("Compare again", href = "/#tab=sync")

    // --- the running request's steps --------------------------------------------------------------------------

    /** The request's steps, as the Requests tab draws the one that runs; [facts], its song's. */
    fun steps(job: Job, facts: SongFacts? = null): List<Chip> = steps(Shape(job), facts)

    internal fun steps(job: Shape, facts: SongFacts?): List<Chip> {
        if (job.peer != null || job.staged) {
            return job.stages.filter { it.state != Job.SKIPPED }.map { stage ->
                Chip(JobViews.stepName(job.job.spec.kind.takeIf { job.own } ?: job.peer ?: "", stage),
                     if (stage.state == Job.INTERRUPTED) Job.FAILED else stage.state)
            }
        }
        if (job.stages.isNotEmpty() && job.fromYoutube) return youtubeSteps(job)
        if (job.stages.isNotEmpty()) return lookupSteps(job, facts)
        return job.steps.filter { it.state != Job.SKIPPED }.map { step ->
            val name = COMMAND_STEPS[step.args.firstOrNull() ?: ""] ?: step.label
            val state = if (step.state == Job.INTERRUPTED) Job.FAILED else step.state
            Chip(name, if (state in listOf(Job.WAITING, Job.RUNNING, Job.DONE, Job.FAILED)) state else Job.DONE)
        }
    }

    private fun lookupSteps(job: Shape, facts: SongFacts?): List<Chip> {
        val leaves = job.steps.any { it.args.firstOrNull() == JobCommands.LOOKUP && "--no-songbooks" in it.args }
        val byName = job.stages.associateBy { it.name }
        val chips = ArrayList<Chip>()
        for ((name, names) in LOOKUP_STEPS) {
            if (name == "Songbooks" && leaves) continue
            val state = stateOf(names.mapNotNull { byName[it] }.map(::sheetWaited)) ?: continue
            chips += when (name) {
                "Match" -> match(byName.getValue("match"), state)
                "Sheet" -> Chip(name, state, sheetSource(byName.getValue("sheet"), state, facts))
                else -> Chip(name, state)
            }
        }
        return chips
    }

    private fun youtubeSteps(job: Shape): List<Chip> {
        val byName = job.stages.associateBy { it.name }
        val chips = ArrayList<Chip>()
        for ((name, names) in YOUTUBE_STEPS) {
            val states = names.mapNotNull { byName[it] }.map { stage ->
                if ((stage.name == "audio" && stage.state == Job.SKIPPED && stage.detail.isNotEmpty()) ||
                    stage.state == Job.INTERRUPTED) Job.FAILED else stage.state
            }
            val state = stateOf(states) ?: continue
            chips += Chip(name, state, if (name == "Audio") YOUTUBE_SOURCE else "")
        }
        return chips
    }

    /** A stage's state as its step reads it: the sheet's, skipped for a block, a cooldown or a spent budget, failed;
     * one the server stopped, failed. */
    private fun sheetWaited(stage: Stage): String =
        if (stage.state == Job.INTERRUPTED || (stage.name == "sheet" && stage.state == Job.SKIPPED && waited(stage.detail)))
            Job.FAILED else stage.state

    private fun match(stage: Stage, state: String): Chip =
        if (state == Job.DONE && stage.detail.startsWith(MATCH_NOT_FOUND)) Chip(NOT_ON_UG, "plain")
        else Chip("Match", state, MATCHED_IN)

    private fun sheetSource(stage: Stage, state: String, facts: SongFacts?): String = when {
        state == Job.RUNNING -> ASKS[stage.detail] ?: ""
        state == Job.FAILED -> ASKS[stage.runningDetail] ?: ""
        state == Job.DONE && facts != null -> facts.sheetFrom
        else -> ""
    }

    /** What the library page draws under a song's request line (outcome.progress): a lookup's steps and, while it
     * runs, how many are over; nothing for a request that runs no lookup, one queued or cancelled, and one Ready. */
    fun progress(job: Job, line: Line, facts: SongFacts?): Map<String, JsonElement> = progress(Shape(job), line, facts)

    internal fun progress(job: Shape, line: Line, facts: SongFacts?): Map<String, JsonElement> {
        if (!(job.looksUp || job.fromYoutube) || job.state == Job.QUEUED || job.state == Job.CANCELLED ||
            (line.tone == "ready" && line.text == Status.READY)) return emptyMap()
        val chips = steps(job, facts)
        if (chips.isEmpty()) return emptyMap()
        val shown = linkedMapOf<String, JsonElement>("steps" to JsonArray(chips.map { it.asJson() }))
        if (job.state == Job.RUNNING) {
            val over = chips.count { it.state == Job.DONE || it.state == "plain" }
            shown["count"] = JsonPrimitive("$over of ${chips.size} done")
        }
        return shown
    }

    /** A step's state from its stages'; null for a step not drawn (no stage, or every one skipped). */
    private fun stateOf(states: List<String>): String? {
        if (states.isEmpty() || states.all { it == Job.SKIPPED }) return null
        if (Job.RUNNING in states) return Job.RUNNING
        if (states.all { it in OVER }) return if (Job.FAILED in states) Job.FAILED else Job.DONE
        if (states.any { it in OVER }) return Job.RUNNING
        return Job.WAITING
    }

    // --- how a finished request ended ---------------------------------------------------------------------------

    /** The request's outcome (outcome.outcome), read from its [line] (Status's), its stages and [facts]; [songId], its
     * song's, for the actions that name it. */
    fun outcome(job: Job, line: Line, facts: SongFacts? = null, songId: Long? = null): Outcome =
        outcome(Shape(job), line, facts, songId)

    internal fun outcome(job: Shape, line: Line, facts: SongFacts?, songId: Long?): Outcome {
        var again: Action? = Action("Try again", post = "/jobs/again", fields = listOf("job" to job.id.toString()))
        val tone = line.tone
        val text = line.text
        if (job.key.startsWith(JobCommands.REMOVING) && (tone == "failed" || job.state == Job.INTERRUPTED)) {
            again = job.job.songId?.let { Action("Try again", post = "/remove", fields = listOf("song" to it.toString())) }
        }
        val peer = job.peer
        if (peer != null && job.state != Job.CANCELLED) return peerOutcome(job, peer, line)
        if (job.state == Job.INTERRUPTED) {
            return Outcome("waiting", "Interrupted", if (job.startedAt != null) INTERRUPTED_RAN else INTERRUPTED_WAITED, again)
        }
        if (tone == "failed") return Outcome("failed", "Failed", sentence(text), again)
        if (tone == "removed") return Outcome("removed", text)
        if (tone == "cancelled") return Outcome("cancelled", text, CANCELLED)
        if (tone == "ready") {
            val href = line.link?.let { href(it.second) }
            if (text == Status.READY) {
                val said = if (job.fromYoutube) youtubeHolds(job.stages) else waits(job.stages, afterSheet = true)
                return Outcome("ready", "Ready", said, href?.let { Action("Open", href = it) })
            }
            return Outcome("ready", text, "", if (line.link != null && href != null) Action(line.link.first, href = href) else null)
        }
        if (tone == "review") {
            val picker = facts?.picker
            return Outcome("review", "Needs your pick", IN_REVIEW,
                           if (picker != null) Action("Pick", href = href(picker)) else inLibrary(songId))
        }
        if (JobCommands.INDEX_READS.any(job.key::startsWith)) {
            val (word, rest) = partition(text, ": ")  // "Read: …", "Not read: …"
            return Outcome(tone, word, if (rest.isNotEmpty()) sentence(rest) else "", if (tone == "waiting") again else null)
        }
        if (tone == "missing") return notFound(job, facts, songId)
        if (tone == "waiting" && job.fromYoutube) return Outcome("waiting", text, youtubeStopped(job.stages), again)
        if (tone == "waiting") {
            return Outcome("waiting", text, waits(job.stages).ifEmpty { if (job.stages.isNotEmpty()) "" else NOT_ASKED }, again)
        }
        // "Added · fetched tonight": the word, then the reason; any other line ("Ignored · overrides.toml") whole
        val (word, rest) = if (text.startsWith("Added · ")) partition(text, " · ") else text to ""
        return Outcome(tone, word, if (rest.isNotEmpty()) sentence(capitalFirst(rest)) else "")
    }

    /** A sync, a take, a pull or a merge over (outcome.py's _peer_outcome). */
    private fun peerOutcome(job: Shape, kind: String, line: Line): Outcome {
        val action = if (kind == "sync") COMPARE_AGAIN else null
        if (job.state == Job.INTERRUPTED) {
            return Outcome("waiting", "Interrupted", if (job.startedAt != null) INTERRUPTED_RAN else INTERRUPTED_WAITED, action)
        }
        if (line.tone == "failed") return Outcome("failed", "Failed", sentence(line.text), action)
        if (kind in NO_UNITS) {
            val said = job.stages.firstOrNull { it.state == Job.DONE && it.detail.isNotEmpty() }?.detail ?: ""
            return Outcome(line.tone, line.text, if (said.isNotEmpty()) sentence(said) else "")
        }
        val taken = job.units.count { it.outcome == "taken" }
        val given = job.units.count { it.outcome == "given" }
        val left = job.units.count { it.outcome == "left" }
        val parts = ArrayList<String>()
        if (taken > 0 || kind != "sync") parts += "${Status.plural(taken, "change")} taken"
        if (given > 0) parts += "${Status.plural(given, "change")} given"
        val said = if (parts.isNotEmpty()) capitalize(parts.joinToString(", ")) + "." else "Nothing changed in either book."
        if (line.tone == "ready") return Outcome("ready", line.text, said)
        val word = if (left > 0) partition(line.text, " · ").first else "Not taken"
        val reason = if (left > 0) "$said ${Status.plural(left, "change")} left as ${if (left == 1) "it was" else "they were"}."
                     else sentence(line.text)
        return Outcome("waiting", word, reason, action)
    }

    /** Not found (outcome.py's _not_found): Ultimate Guitar has no chords for it once the fetch asked it, else the
     * offline index lacks it under this name, then what the lookup got elsewhere or the indexes have elsewhere. */
    private fun notFound(job: Shape, facts: SongFacts?, songId: Long?): Outcome {
        val unmatched = facts != null && facts.notFound
        val head = if (facts != null && facts.askedUg) NO_CHORDS else if (unmatched) NOT_INDEXED else ""
        val search = if (unmatched && songId != null) Action("Search the index", href = "/review?song=$songId")
                     else null
        if (job.stages.any { it.name == "gtptabs" && it.state == Job.DONE && it.detail == GTPTABS_KEPT }) {
            return Outcome("missing", "Not on the sites", joined(head, "Got a Guitar Pro file from gtptabs"),
                           inLibrary(songId), search)
        }
        val where = facts?.elsewhere
        if (where != null && songId != null && where.first in ELSEWHERE) {
            val (source, url) = where
            val fields = listOf("song" to songId.toString()) + if (source == "lacuerda") listOf("lacuerda" to url) else emptyList()
            return Outcome("missing", "Not on the sites", joined(head, ELSEWHERE.getValue(source)),
                           Action("Fetch from there", post = "/lookup", fields = fields), search)
        }
        val named = job.job.display.ifEmpty { job.job.title }
        return Outcome("missing", "Not on the sites", sentence(head),
                       search ?: Action("Ask by name", href = "/#" + PyUrl.urlencode(listOf("q" to named))))
    }

    private fun joined(head: String, rest: String): String = sentence(if (head.isNotEmpty()) "$head. $rest" else rest)

    private fun inLibrary(songId: Long?): Action? = songId?.let { Action("Open in the library", href = "/#song=$it") }

    /** The first stage's wait or error, in two short sentences ("LRCLIB answered 503. The lyrics wait until
     * tonight."); "" for none; [afterSheet], the stages after the sheet. */
    private fun waits(stages: List<Stage>, afterSheet: Boolean = false): String {
        val names = LOOKUP_STEPS.drop(if (afterSheet) 3 else 2).flatMap { it.second }
        val byName = stages.associateBy { it.name }
        return names.firstNotNullOfOrNull { name -> byName[name]?.let(::stageReason)?.takeIf { it.isNotEmpty() } } ?: ""
    }

    private fun youtubeHolds(stages: List<Stage>): String {
        val byName = stages.associateBy { it.name }
        val lyrics = byName["lyrics"]
        val chords = byName["chords"]
        if (lyrics != null && (lyrics.state == Job.SKIPPED || lyrics.state == Job.FAILED) && lyrics.detail.isNotEmpty()) {
            return capital(lyrics.detail)
        }
        return if (chords != null && chords.detail.isNotEmpty()) capital(chords.detail.removePrefix("up to date: ")) else ""
    }

    private fun youtubeStopped(stages: List<Stage>): String = stages.firstOrNull { stage ->
        stage.name in listOf("audio", "lyrics", "chords", "pdf") &&
            (stage.state == Job.SKIPPED || stage.state == Job.FAILED) && stage.detail.isNotEmpty()
    }?.let { capital(it.detail) } ?: ""

    private fun capital(text: String): String = sentence(capitalFirst(text))

    /** `text[:1].upper() + text[1:]`, Python's upper of the first code point. */
    private fun capitalFirst(text: String): String {
        if (text.isEmpty()) return text
        val end = text.offsetByCodePoints(0, 1)
        return PyUnicode.upper(text.substring(0, end)) + text.substring(end)
    }

    /** str.capitalize. */
    private fun capitalize(text: String): String = PyUnicode.capitalize(text)

    private fun stageReason(stage: Stage): String {
        val detail = PyText.strip(stage.detail)
        if (stage.name == "pdf" || stage.name == "songbooks") {
            return if (stage.state == Job.FAILED && detail.isNotEmpty()) sentence(detail) else ""
        }
        val (what, verb) = WHAT[stage.name] ?: return ""
        val waits = "${capitalFirst(what)} $verb"  // the second sentence's start
        if (stage.state == Job.FAILED) {
            FAILED.find(detail)?.let { m ->
                val status = STATUS.find(m.groupValues[2])
                val answered = if (status != null) "answered ${status.groupValues[1]}" else "failed"
                return "${m.groupValues[1]} $answered. $waits until tonight."
            }
        }
        if (stage.state != Job.SKIPPED) return ""
        BLOCKED.find(detail)?.let { m ->
            val until = m.groups[2]?.value?.takeIf { it.isNotEmpty() } ?: "it cools down"
            return "${m.groupValues[1]} turned us back. $waits until $until."
        }
        COOLING.find(detail)?.let { m ->
            return "Waiting out ${m.groupValues[1]} until ${m.groupValues[2]}. $waits."
        }
        SPENT.find(detail)?.let { m ->
            return "${capitalFirst(m.groupValues[1])}. $waits until tonight."
        }
        return ""
    }

    private fun sentence(text: String): String {
        val t = PyText.strip(text)
        return if (t.isEmpty() || listOf(".", "!", "?", "…").any(t::endsWith)) t else "$t."
    }

    /** A link of Status's, relative to the library page at /, as an address from any page. */
    private fun href(href: String): String =
        if (href.startsWith("/") || href.startsWith("https://") || href.startsWith("http://")) href else "/$href"

    private fun partition(text: String, sep: String): Pair<String, String> {
        val at = text.indexOf(sep)
        return if (at < 0) text to "" else text.substring(0, at) to text.substring(at + sep.length)
    }

    /** Whether a stage was skipped for a block, a cooldown or a spent budget, in get.py's words. */
    internal fun waited(detail: String): Boolean {
        val d = PyText.strip(detail)
        return BLOCKED.find(d) != null || COOLING.find(d) != null || SPENT.find(d) != null
    }
}
