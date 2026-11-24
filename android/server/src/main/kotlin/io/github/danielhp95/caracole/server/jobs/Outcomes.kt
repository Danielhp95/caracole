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
import java.time.Duration
import java.time.Instant

/** outcome.py's Chip: a step of a request, its [state] (waiting, running, done, failed; skipped, every stage of it
 * ended skipped, over, in its place; or plain, over and neither, "Match · not on UG"), the site it names in full
 * ([site], Outcomes.SITE_NAMES': "Ultimate Guitar"; "" for none) and what it found ([found], Outcomes.found: "" for
 * nothing, a plain step, a skipped one and one that waits). A step of a sync, a take or a request of other commands
 * has neither. */
data class Chip(val name: String, val state: String, val site: String = "", val found: String = "") {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "name" to JsonPrimitive(name), "site" to JsonPrimitive(site), "state" to JsonPrimitive(state),
        "found" to JsonPrimitive(found),
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

    /** A transcription's steps (transcribe_job.STAGES). */
    val TRANSCRIBE_STEPS: List<Pair<String, List<String>>> = listOf(
        "Song" to listOf("song"), "Vocals" to listOf("vocals"), "Words" to listOf("words"),
        "Chords" to listOf("chords"), "PDF" to listOf("pdf"),
    )

    /** A staged job's steps and the stage of its words a Ready one says may wait (outcome._staged); null for any
     * other job. */
    private fun staged(job: Shape): Pair<List<Pair<String, List<String>>>, String>? = when {
        job.fromYoutube -> YOUTUBE_STEPS to "lyrics"
        job.transcribes -> TRANSCRIBE_STEPS to "words"
        else -> null
    }

    /** A step's site in full, by its tag (outcome.SITE_NAMES: get.py's NAMES by icons.tag, YouTube's, and where an
     * auto sheet or a file you filed came from); a tag it lacks is named as it is. */
    val SITE_NAMES: Map<String, String> = linkedMapOf(
        "UG" to "Ultimate Guitar", "LRCLIB" to "LRCLIB", "Megalobiz" to "Megalobiz", "AZLyrics" to "AZLyrics",
        "LaCuerda" to "LaCuerda", "gtptabs" to "gtptabs.com", "MuseScore" to "MuseScore", "harptabs" to "harptabs.com",
        "gametabs" to "gametabs.net", "iReal" to "iReal Pro's forum", YOUTUBE_SOURCE to "YouTube", "auto" to "auto-chords", "inbox" to "your inbox",
    )

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

    /** How long a request runs before the library page draws its steps (outcome.BAR_AFTER). */
    val BAR_AFTER: Duration = Duration.ofSeconds(1)

    private const val MATCHED_IN = "UG"
    const val NOT_ON_UG = "Match · not on UG"
    private const val MATCH_NOT_FOUND = "not in UG's index"  // get.py's
    private const val GTPTABS_KEPT = "Guitar Pro file downloaded"  // get.py's

    /** A running sheet stage's site, by its words (get.py's SHEET_FROM, icons.tag). */
    internal val ASKS = mapOf("from LaCuerda" to "LaCuerda", "from UG" to "UG", "from iReal Pro" to "iReal")

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

    /** The request's steps, as the Requests tab draws the one that runs, and a finished one [listsSteps] takes;
     * [facts], its song's. */
    fun steps(job: Job, facts: SongFacts? = null): List<Chip> = steps(Shape(job), facts)

    /** Whether the Requests tab lists [job]'s steps once it is over (outcome.lists_steps): a lookup's, or a sheet from
     * a YouTube video's, that started, as it left them; never one cancelled before it ran, nor a request of other
     * commands. */
    fun listsSteps(job: Job): Boolean {
        if (job.active || job.startedAt == null) return false
        val shape = Shape(job)
        return shape.looksUp || staged(shape) != null
    }

    internal fun steps(job: Shape, facts: SongFacts?): List<Chip> {
        if (job.peer != null || job.staged) {
            return job.stages.filter { it.state != Job.SKIPPED }.map { stage ->
                Chip(JobViews.stepName(job.job.spec.kind.takeIf { job.own } ?: job.peer ?: "", stage),
                     if (stage.state == Job.INTERRUPTED) Job.FAILED else stage.state)
            }
        }
        if (job.stages.isNotEmpty()) staged(job)?.let { return stagedSteps(job, it.first) }
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
            val read = names.mapNotNull { byName[it] }.map { it to sheetWaited(it) }
            val state = stateOf(read.map { it.second }) ?: continue
            chips += when (name) {
                "Match" -> match(byName.getValue("match"), state, found(read))
                "Sheet" -> sheetSource(byName.getValue("sheet"), state, facts).let { where ->
                    Chip(name, state, SITE_NAMES[where] ?: where, found(read))
                }
                else -> Chip(name, state, "", found(read))
            }
        }
        return chips
    }

    private fun stagedSteps(job: Shape, table: List<Pair<String, List<String>>>): List<Chip> {
        val byName = job.stages.associateBy { it.name }
        val chips = ArrayList<Chip>()
        for ((name, names) in table) {
            val read = names.mapNotNull { byName[it] }.map { stage ->
                stage to if ((stage.name == "audio" && stage.state == Job.SKIPPED && stage.detail.isNotEmpty()) ||
                    stage.state == Job.INTERRUPTED) Job.FAILED else stage.state
            }
            val state = stateOf(read.map { it.second }) ?: continue
            chips += Chip(name, state, if (name == "Audio") SITE_NAMES.getValue(YOUTUBE_SOURCE) else "", found(read))
        }
        return chips
    }

    /** A stage's state as its step reads it: the sheet's, skipped for a block, a cooldown or a spent budget, failed;
     * one the server stopped, failed. */
    private fun sheetWaited(stage: Stage): String =
        if (stage.state == Job.INTERRUPTED || (stage.name == "sheet" && stage.state == Job.SKIPPED && waited(stage.detail)))
            Job.FAILED else stage.state

    /** What a step found (outcome._found), from its stages, each with its state as the step reads it: each one done in
     * its words, each one failed in the outcome's ([stageReason]) when they say something, else in its own; in order,
     * joined by " · "; "" for none. A stage the server cut off (interrupted) found nothing: its words are what it
     * said while it ran. */
    private fun found(read: List<Pair<Stage, String>>): String = read
        .filter { (stage, state) -> (state == Job.DONE || state == Job.FAILED) && stage.state != Job.INTERRUPTED }
        .map { (stage, state) -> if (state == Job.DONE) stage.detail else stageReason(stage).ifEmpty { stage.detail } }
        .filter { it.isNotEmpty() }
        .joinToString(" · ")

    /** Match (outcome._match), in Ultimate Guitar's offline index, in every state but a song it lacks, plain. */
    private fun match(stage: Stage, state: String, found: String): Chip =
        if (state == Job.DONE && stage.detail.startsWith(MATCH_NOT_FOUND)) Chip(NOT_ON_UG, "plain")
        else Chip("Match", state, SITE_NAMES.getValue(MATCHED_IN), found)

    private fun sheetSource(stage: Stage, state: String, facts: SongFacts?): String = when {
        state == Job.RUNNING -> ASKS[stage.detail] ?: ""
        state == Job.FAILED -> ASKS[stage.runningDetail] ?: ""
        state == Job.DONE && facts != null -> facts.sheetFrom
        else -> ""
    }

    /** What the library page draws under a song's request line (outcome.progress): a lookup's steps, every one it
     * has from its start, and the step in hand ([inHand]), its place `at` and `count` ("3 of 7"), `doing`, what its
     * running stage says it does, a long one ([Status.doing]: "heard 1:20 of 3:45"), and `waits`, true, while that
     * step waits for the book ([waitsForTheBook]); nothing for a request that runs no lookup, one queued or
     * cancelled, one Ready, and one that hasn't run [BAR_AFTER] at [now] ([hasRun]). */
    fun progress(job: Job, line: Line, facts: SongFacts?, now: Instant = Instant.now()): Map<String, JsonElement> =
        progress(Shape(job), line, facts, now)

    internal fun progress(job: Shape, line: Line, facts: SongFacts?, now: Instant = Instant.now()):
        Map<String, JsonElement> {
        if (!(job.looksUp || staged(job) != null) || job.state == Job.QUEUED || job.state == Job.CANCELLED ||
            (line.tone == "ready" && line.text == Status.READY) || !hasRun(job.job, now)) return emptyMap()
        val chips = steps(job, facts)
        if (chips.isEmpty()) return emptyMap()
        val shown = linkedMapOf<String, JsonElement>("steps" to JsonArray(chips.map { it.asJson() }))
        val at = inHand(chips, running = job.state == Job.RUNNING)
        if (at != null) {
            shown["at"] = JsonPrimitive(at)
            shown["count"] = JsonPrimitive("${at + 1} of ${chips.size}")
            val told = if (job.state == Job.RUNNING) job.stages.firstOrNull { it.state == Job.RUNNING } else null
            if (told != null && Status.doing(told)) shown["doing"] = JsonPrimitive(told.detail)
            if (job.state == Job.RUNNING && waitsForTheBook(job.stages)) shown["waits"] = JsonPrimitive(true)
        }
        return shown
    }

    /** Whether the stage that runs waits for the book (outcome._waits_for_the_book): its detail begins as
     * [Status.WAITING], as [Status.stageLine] reads it for "Waiting for the book…". The phone takes no lock, so none of
     * its own lookups waits; the rule is Python's, held by the vectors. */
    internal fun waitsForTheBook(stages: List<Stage>): Boolean =
        stages.firstOrNull { it.state == Job.RUNNING }?.detail?.startsWith(Status.WAITING) == true

    /** Whether [job] has run [BAR_AFTER] (outcome._has_run): never, one that never started; one over, from its start
     * to its end (to [now] when it has no end); one that runs, to [now]. */
    internal fun hasRun(job: Job, now: Instant): Boolean {
        val started = job.startedAt ?: return false
        val end = job.finishedAt.takeIf { !job.active } ?: now
        return Duration.between(started, end) >= BAR_AFTER
    }

    /** The place of the step in hand (outcome._in_hand): while the request runs, the step that runs, else the first
     * that waits, else the last; once over, the first that failed, else none. */
    internal fun inHand(chips: List<Chip>, running: Boolean): Int? {
        val states = chips.map { it.state }
        if (!running) return states.indexOf(Job.FAILED).takeIf { it >= 0 }
        for (state in listOf(Job.RUNNING, Job.WAITING)) {
            val at = states.indexOf(state)
            if (at >= 0) return at
        }
        return chips.lastIndex.takeIf { it >= 0 }
    }

    /** A step's state from its stages'; skipped once every one ended skipped; null for a step with no stage, not
     * drawn. */
    private fun stateOf(states: List<String>): String? {
        if (states.isEmpty()) return null
        if (states.all { it == Job.SKIPPED }) return Job.SKIPPED
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
            again = job.job.songId?.let {
                Action("Try again", post = "/remove",
                       fields = listOf("song" to it.toString(), "identity" to JobCommands.songKeyOf(job.key)))
            }
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
                val said = staged(job)?.let { stagedHolds(job.stages, it.second) } ?: waits(job.stages, afterSheet = true)
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
        staged(job)?.let { if (tone == "waiting") return Outcome("waiting", text, stagedStopped(job.stages, it.first), again) }
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
            val fields = listOf("song" to songId.toString(), "identity" to JobCommands.songKeyOf(job.key)) +
                if (source == "lacuerda") listOf("lacuerda" to url) else emptyList()
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

    private fun stagedHolds(stages: List<Stage>, words: String): String {
        val byName = stages.associateBy { it.name }
        val lyrics = byName[words]
        val chords = byName["chords"]
        if (lyrics != null && (lyrics.state == Job.SKIPPED || lyrics.state == Job.FAILED) && lyrics.detail.isNotEmpty()) {
            return capital(lyrics.detail)
        }
        return if (chords != null && chords.detail.isNotEmpty()) capital(chords.detail.removePrefix("up to date: ")) else ""
    }

    private fun stagedStopped(stages: List<Stage>, table: List<Pair<String, List<String>>>): String {
        val names = table.flatMap { it.second }.filter { it != "song" }.toSet()
        return stages.firstOrNull { stage ->
            stage.name in names &&
                (stage.state == Job.SKIPPED || stage.state == Job.FAILED) && stage.detail.isNotEmpty()
        }?.let { capital(it.detail) } ?: ""
    }

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
