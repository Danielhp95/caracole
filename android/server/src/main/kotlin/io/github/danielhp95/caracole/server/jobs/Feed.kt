package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.py.PyFormat
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * web/feed.py on the phone: the library page's Requests tab, as data, every request the queue remembers as
 * library_assets/requests.js draws it (`GET /requests.json`, RequestsRoutes). vectors/web/requests.jsonl holds it to
 * Python's answers, byte for byte (RequestsReplay).
 *
 * Under **Now**, the request that runs, with how long ago it started, its line and its steps (the chips the library
 * page draws under a song's line), and those queued under it in order ("Queued · next", "Queued · 2nd"), each with
 * Cancel (`POST /jobs/cancel`); then the finished ones, newest first under **Today** and **Earlier** (by when each
 * ended, in the phone's time zone), each with its outcome (a word in its tone, a reason, its next step and the one
 * beside it) and when it ended. A next step is a link (`href`) or a form the tab posts with the form token (`post`
 * and its `fields`); the ones that are the request's way on are `primary` ([PRIMARY]).
 *
 * Every request keeps what it ran (`output`): its title and when it was asked for (in the phone's zone, named as
 * Python's `%Z` names it: [ZoneNames]), a lookup's stages, each with its state and why, and each command it ran with
 * its state; what each command printed (`lines`) only for the requests the tab has opened. A request that stopped only
 * because its song needs a pick first says so ("Waits for a pick") rather than failed, and a song not found in the
 * offline index gets what `caracole search` finds for it as a next step when its outcome has none that leads there.
 *
 * What feed.py works out of the job and its song (its line, its chips, its outcome) the caller gives, as
 * jobs_routes.requests_json does: [feed]'s `lines` (Status), `steps` (Outcomes.steps of the running request, with
 * its song's facts) and `outcomes` (Outcomes.outcome of each over, with its song's facts and id). Where one isn't
 * given, Feed works it out of the job alone, as feed.py does: a request over with a line and no outcome, Outcomes'
 * outcome of that line; the running one with no steps, Outcomes.steps with no facts; a request over with neither line
 * nor outcome says its state.
 */
object Feed {
    val STATE_TEXT: Map<String, String> = linkedMapOf(
        "queued" to "Queued", "running" to "Running", "done" to "Done", "failed" to "Failed", "waiting" to "Waiting",
        "skipped" to "Skipped", "cancelled" to "Cancelled", "interrupted" to "Cut short",
    )

    /** The next steps that are the request's way on; the others (Try again, Ask by name…) are plain buttons. */
    val PRIMARY: Set<String> = setOf("Open", "Pick", "Fetch from there", "Open songbook", "Search the index")
    const val SEARCH = "Search the index"

    /** What `caracole fetch --song` says of a song that needs review first (commands/fetch.py). */
    private const val NEEDS_REVIEW = "needs review first"
    const val PICK_STAGE = "Not fetched: its UG sheet waits for the match. Pick it, with Fetch ticked, and we fetch it " +
        "then."
    const val PICK_STEP = "Not fetched: caracole fetch waits for the match. Pick it, with Fetch ticked, and we fetch " +
        "it then."

    private val GROUPS = listOf("Now", "Today", "Earlier")

    /** pages.Pick, as feed.py reads it: the song a finished request waits for a pick of, and whether its pick is what
     * `caracole search` finds (a song not found) rather than a review's candidates. */
    data class Pick(val songId: Long, val search: Boolean = false)

    /**
     * Every request remembered ([jobs], newest first), as the tab draws it: `active`, how many wait or run (the tab's
     * count), and `groups`, Now, Today and Earlier, each that has a request, with its `requests`.
     *
     * [lines] are Status's, by job id; [outcomes] each finished one's (Outcomes.outcome; else read from its line);
     * [steps] the running one's chips (Outcomes.steps; else the job's alone); [picks] the songs of finished requests
     * that wait for a pick now, by song key; [opened], the requests whose output comes with what each command printed;
     * [now], the answer's time; [zone], the phone's, whose days Today and Earlier are and whose clock the times are
     * shown on.
     */
    fun feed(jobs: List<Job>, lines: Map<Int, Line>, outcomes: Map<Int, Outcome> = emptyMap(),
             steps: Map<Int, List<Chip>> = emptyMap(), picks: Map<String, Pick> = emptyMap(),
             opened: Set<Int> = emptySet(), now: Instant = Instant.now(),
             zone: ZoneId = ZoneId.systemDefault(), names: ZoneNames = ZoneNames.load()): JsonObject {
        val pending = waitingPicks(jobs, picks)
        val active = jobs.filter { it.active }.sortedWith(compareBy({ it.state != Job.RUNNING }, { it.id }))
        val queued = active.filter { it.state == Job.QUEUED }
        val groups = GROUPS.associateWith { ArrayList<JsonObject>() }
        for (job in active) {
            val shown = if (job.state == Job.RUNNING) running(job, lines[job.id], steps[job.id] ?: Outcomes.steps(job), now)
                        else queued(job, queued.indexOf(job) + 1)
            groups.getValue("Now") += plus(shown, "output" to output(job, opened = job.id in opened, zone, names))
        }
        val today = now.atZone(zone).toLocalDate()
        val over = jobs.filter { !it.active }.sortedWith(
            compareByDescending<Job> { it.finishedAt ?: it.queuedAt }.thenByDescending { it.id })
        for (job in over) {
            val ended = (job.finishedAt ?: job.queuedAt).atZone(zone)
            val day = ended.toLocalDate() != today
            val pick = pending[job.id]
            val picking = pick != null && waitsForPick(job, pick)
            val said = outcomes[job.id] ?: lines[job.id]?.let { Outcomes.outcome(job, it) }
            groups.getValue(if (day) "Earlier" else "Today") += plus(
                finished(job, said, ended, pick, day),
                "output" to output(job, opened = job.id in opened, zone, names, picking = picking))
        }
        return JsonObject(linkedMapOf(
            "active" to JsonPrimitive(jobs.count { it.active }),
            "groups" to JsonArray(groups.filterValues { it.isNotEmpty() }.map { (name, requests) ->
                JsonObject(linkedMapOf("name" to JsonPrimitive(name), "requests" to JsonArray(requests)))
            }),
        ))
    }

    /** The request that runs: its song, how long ago it started, its line, and its steps. */
    private fun running(job: Job, line: Line?, chips: List<Chip>, now: Instant): JsonObject {
        val shown = head(job, Job.RUNNING, line?.text ?: STATE_TEXT.getValue(Job.RUNNING))
        job.startedAt?.let { shown["ago"] = JsonPrimitive("started ${ago(it, now)}") }
        shown["steps"] = JsonArray(chips.map(Chip::asJson))
        return JsonObject(shown)
    }

    /** A request that waits: its place ("Queued · next", "Queued · 3rd") and Cancel, which takes it out of the queue. */
    private fun queued(job: Job, place: Int): JsonObject {
        val shown = head(job, Job.QUEUED, "Queued · ${ordinal(place)}")
        shown["actions"] = JsonArray(listOf(JsonObject(linkedMapOf(
            "label" to JsonPrimitive("Cancel"), "post" to JsonPrimitive("/jobs/cancel"),
            "fields" to JsonObject(mapOf("job" to JsonPrimitive(job.id.toString()))),
            "aria" to JsonPrimitive("Cancel ${job.display}"), "primary" to JsonPrimitive(false),
        ))))
        return JsonObject(shown)
    }

    /** A finished request: its outcome in a word, the reason, its next steps and when it ended (with its day for one
     * before today). */
    private fun finished(job: Job, said: Outcome?, ended: ZonedDateTime, pick: Pick?, day: Boolean): JsonObject {
        val shown: LinkedHashMap<String, JsonElement>
        val actions = ArrayList<JsonObject>()
        if (said == null) {
            shown = head(job, job.state, STATE_TEXT[job.state] ?: job.state)
        } else {
            shown = head(job, said.tone, said.word)
            if (said.reason.isNotEmpty()) shown["reason"] = JsonPrimitive(said.reason)
            action(said.action)?.let(actions::add)
            action(said.also, primary = false)?.let(actions::add)
        }
        if (pick != null && pick.search) {  // a song the index didn't match: what caracole search finds, if not there
            val href = "/review?song=${pick.songId}"
            if (actions.none { (it["href"] as? JsonPrimitive)?.contentOrNull == href }) {
                actions += JsonObject(linkedMapOf("label" to JsonPrimitive(SEARCH), "href" to JsonPrimitive(href),
                                                  "primary" to JsonPrimitive(false)))
            }
        }
        if (actions.isNotEmpty()) shown["actions"] = JsonArray(actions)
        val clock = "${two(ended.hour)}:${two(ended.minute)}"
        val date = "${two(ended.dayOfMonth)}/${two(ended.monthValue)}/${two(ended.year % 100)}"  // %d/%m/%y
        shown["when"] = JsonObject(linkedMapOf(
            "stamp" to JsonPrimitive(Stamps.of(ended.toInstant())),
            "text" to JsonPrimitive(if (day) "$date, $clock" else clock),
        ))
        return JsonObject(shown)
    }

    private fun head(job: Job, tone: String, text: String): LinkedHashMap<String, JsonElement> = linkedMapOf(
        "id" to JsonPrimitive(job.id), "display" to JsonPrimitive(job.display), "state" to JsonPrimitive(job.state),
        "says" to JsonObject(linkedMapOf("tone" to JsonPrimitive(tone), "text" to JsonPrimitive(text))),
    )

    /** A next step as the tab draws it: a link, or a form it posts with the form token; null for none. [primary]:
     * drawn as the request's way on when it is one ([PRIMARY]). Its fields are a dict: a name given twice keeps its
     * first place and its last value. */
    private fun action(a: Action?, primary: Boolean = true): JsonObject? {
        if (a == null) return null
        val post = a.post
        val href = a.href
        if (post == null && href == null) return null
        val shown = linkedMapOf<String, JsonElement>("label" to JsonPrimitive(a.label),
                                                     "primary" to JsonPrimitive(primary && a.label in PRIMARY))
        if (post != null) {
            val fields = LinkedHashMap<String, JsonElement>()
            for ((name, field) in a.fields) fields[name] = JsonPrimitive(field)
            shown["post"] = JsonPrimitive(post)
            shown["fields"] = JsonObject(fields)
        } else {
            shown["href"] = JsonPrimitive(href)
        }
        return JsonObject(shown)
    }

    /** What the request ran: its title and when it was asked for, a lookup's stages, and each command with how it
     * went; [opened], what each printed. [picking]: it stopped only because the song needs a pick first. */
    private fun output(job: Job, opened: Boolean, zone: ZoneId, names: ZoneNames, picking: Boolean = false): JsonObject {
        val meta = StringBuilder("${job.title} · asked ${shown(job.queuedAt, zone, names)}")
        if (job.note.isNotEmpty()) meta.append(" · ${job.note}")
        job.secondsToSheet?.let { meta.append(" · sheet readable after ${PyFormat.fixed(it, 1)} s") }
        return JsonObject(linkedMapOf(
            "meta" to JsonPrimitive(meta.toString()),
            "opened" to JsonPrimitive(opened),
            "stages" to JsonArray(job.stages.map {
                stage(it, picking = picking && it.name == "sheet" && it.state == Job.SKIPPED)
            }),
            "steps" to JsonArray(job.steps.map { step(it, opened, picking = picking && it.state == Job.FAILED) }),
        ))
    }

    private fun stage(stage: Stage, picking: Boolean): JsonObject {
        val shown = linkedMapOf<String, JsonElement>("label" to JsonPrimitive(stage.label),
                                                     "badge" to badge(stage.state, picking))
        if (picking) shown["note"] = JsonPrimitive(PICK_STAGE)
        if (stage.detail.isNotEmpty()) shown["detail"] = JsonPrimitive(stage.detail)
        return JsonObject(shown)
    }

    private fun step(step: Step, opened: Boolean, picking: Boolean): JsonObject {
        val shown = linkedMapOf<String, JsonElement>("label" to JsonPrimitive(step.label),
                                                     "badge" to badge(step.state, picking))
        if (picking) shown["note"] = JsonPrimitive(PICK_STEP)
        if (opened) {
            val earlier = if (step.dropped != 0) listOf("… ${step.dropped} earlier lines") else emptyList()
            shown["lines"] = JsonArray((earlier + step.output).map(::JsonPrimitive))
        }
        return JsonObject(shown)
    }

    private fun badge(state: String, picking: Boolean): JsonObject =
        if (picking) JsonObject(linkedMapOf("tone" to JsonPrimitive("review"), "text" to JsonPrimitive("Waits for a pick")))
        else JsonObject(linkedMapOf("tone" to JsonPrimitive(state), "text" to JsonPrimitive(STATE_TEXT[state] ?: state)))

    /** feed._ago: how long ago, in whole seconds (cut toward zero, never below 0), minutes or hours. */
    fun ago(then: Instant, now: Instant): String {
        val micros = Duration.between(then, now).let { it.seconds * 1_000_000 + it.nano / 1_000 }
        val seconds = maxOf(0L, micros / 1_000_000)
        return when {
            seconds < 60 -> "$seconds s ago"
            seconds < 3600 -> "${seconds / 60} min ago"
            else -> "${seconds / 3600} h ago"
        }
    }

    /** feed._ordinal: a queued request's place: "next", then "2nd", "3rd", "4th"… */
    fun ordinal(n: Long): String {
        if (n <= 1) return "next"
        val suffix = if (Math.floorMod(n, 100L) in 10..20) "th"
                     else when (Math.floorMod(n, 10L)) { 1L -> "st"; 2L -> "nd"; 3L -> "rd"; else -> "th" }
        return "$n$suffix"
    }

    private fun ordinal(n: Int): String = ordinal(n.toLong())

    /** stamps.shown(at, "", local=True): the time in [zone], named ("2026-11-04 00:27 CET"). */
    fun shown(at: Instant?, zone: ZoneId, names: ZoneNames = ZoneNames.load()): String {
        if (at == null) return ""
        val local = at.atZone(zone)
        return "${local.year.toString().padStart(4, '0')}-${two(local.monthValue)}-${two(local.dayOfMonth)} " +
            "${two(local.hour)}:${two(local.minute)} ${names.label(zone, at)}"
    }

    /** The newest finished request of each song that waits for a pick now, and its song's pick. */
    private fun waitingPicks(jobs: List<Job>, picks: Map<String, Pick>): Map<Int, Pick> {
        val pending = HashMap<Int, Pick>()
        val seen = HashSet<String>()
        for (job in jobs) {  // newest first
            if (!seen.add(job.key)) continue
            val pick = picks[job.key]
            if (!job.active && pick != null) pending[job.id] = pick
        }
        return pending
    }

    /** Whether a finished request stopped only because its song needs a pick first: the one step that failed is its
     * `caracole fetch --song`, which refused the song as needing review, or, for a lookup, its sheet stage was
     * skipped; and the song has a picker ([pick], not a search's). */
    private fun waitsForPick(job: Job, pick: Pick?): Boolean {
        if (pick == null || pick.search) return false
        if (job.stages.isNotEmpty()) {
            return job.state == Job.DONE && job.stages.any { it.name == "sheet" && it.state == Job.SKIPPED }
        }
        if (job.state != Job.FAILED) return false
        val failed = job.steps.filter { it.state == Job.FAILED }
        return failed.size == 1 && failed[0].args.firstOrNull() == "fetch" && failed[0].output.any { NEEDS_REVIEW in it }
    }

    private fun plus(shown: JsonObject, member: Pair<String, JsonElement>): JsonObject =
        JsonObject(LinkedHashMap(shown).apply { put(member.first, member.second) })

    private fun two(n: Int): String = n.toString().padStart(2, '0')
}

/**
 * How Python's `%Z` names a time zone's clock (stamps.shown(local=True): the C library's abbreviation, from tzdata),
 * which java.time and ICU name otherwise ("GMT+01:00"): the table `caracole/page/requests.json`'s `zones` holds,
 * tests/test_conformance_requests.py's, every zone's labels of letters by its offset and since when, read from tzdata;
 * an offset the table doesn't name is named by its number, as tzdata names it (`-03`, `+0545`).
 */
class ZoneNames(private val zones: Map<String, List<Entry>>) {
    /** An offset in seconds east of UTC, its label, and since when (epoch seconds; null: always). */
    data class Entry(val offset: Int, val label: String, val since: Long?)

    /** The label of [zone]'s clock at [at]: the table's latest entry of its offset then, else its number. */
    fun label(zone: ZoneId, at: Instant): String {
        val offset = zone.rules.getOffset(at).totalSeconds
        val moment = at.epochSecond
        return zones[zone.id].orEmpty().lastOrNull { it.offset == offset && (it.since == null || it.since <= moment) }
            ?.label ?: numeric(offset)
    }

    companion object {
        /** Where the build puts caracole's runtime data of the Requests tab on the classpath. */
        const val DATA = "caracole/page/requests.json"

        private val loaded: ZoneNames by lazy { read(text(DATA)) }

        /** The table on the classpath; IllegalStateException when it is missing. */
        fun load(): ZoneNames = loaded

        fun read(text: String): ZoneNames {
            val zones = Json.parseToJsonElement(text).jsonObject["zones"]?.jsonObject
                ?: throw IllegalStateException("$DATA has no zones")
            return ZoneNames(zones.mapValues { (_, entries) ->
                entries.jsonArray.map { entry ->
                    val (offset, label, since) = entry.jsonArray
                    Entry(offset.jsonPrimitive.content.toInt(), label.jsonPrimitive.content,
                          if (since is JsonNull) null else since.jsonPrimitive.long)
                }
            })
        }

        /** tzdata's name of an offset it has no letters for: its sign, its hours, and its minutes when there are some. */
        fun numeric(offset: Int): String {
            val sign = if (offset < 0) "-" else "+"
            val minutes = Math.abs(offset) / 60
            val (h, m) = minutes / 60 to minutes % 60
            return sign + h.toString().padStart(2, '0') + (if (m != 0) m.toString().padStart(2, '0') else "")
        }

        private fun text(name: String): String {
            val stream = ZoneNames::class.java.classLoader?.getResourceAsStream(name)
                ?: throw IllegalStateException("$name isn't on the classpath")
            return stream.use { it.readBytes().toString(Charsets.UTF_8) }
        }
    }
}
