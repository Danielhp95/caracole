package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobHistory
import io.github.danielhp95.caracole.server.jobs.JobNotOver
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobStarted
import io.github.danielhp95.caracole.server.jobs.QueueFull
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.time.Instant
import java.util.Base64

/**
 * The job queue's command lines and rules (vectors/web/queue.jsonl) and its request history (vectors/web/history.jsonl),
 * every record answered as caracole serve's queue and history answered it (tests/test_conformance_queue.py's
 * docstring has their shapes): web/jobs.py's builders and rules by JobCommands; each queue's ops by a JobQueue whose
 * commands follow the record's steps, on the record's ticking clock, its worker in this replay's one thread (a `run`
 * awaits the next job that waits; the worker lets the replay go first after each job), its jobs after each op as
 * their history lines hold them; each history's ops by a JobHistory, its file's text after each.
 */
object QueueReplay : AreaReplay {
    override val area = "queue"
    private val START: Instant = Instant.parse("2026-11-03T09:30:00Z")

    override fun replay(misses: Misses) {
        val dir = kotlin.io.path.createTempDirectory("caracole-queue").toFile()
        try {
            for (r in Corpus.records("web/queue.jsonl")) {
                when {
                    r.fn == "caracole.web.jobs.JobQueue" -> queue(misses, r, File(dir, "q${misses.checked}").apply { mkdirs() })
                    r.fn.startsWith("caracole.web.jobs._") -> rule(misses, r)
                    else -> builder(misses, r)
                }
            }
            for (r in Corpus.records("web/history.jsonl")) history(misses, r, File(dir, "h${misses.checked}"))
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- builders and rules -----------------------------------------------------------------------------------

    private fun steps(commands: List<Command>): JsonArray =
        JsonArray(commands.map { JsonArray(listOf(JsonPrimitive(it.label), strings(it.args))) })

    private fun strings(values: List<String>) = JsonArray(values.map(::JsonPrimitive))

    private fun builder(misses: Misses, r: Record) {
        val a = r.args.map { it.jsonPrimitive.content }
        val kw = r.kw
        fun s(name: String): String? = (kw[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
        fun l(name: String): Long? = (kw[name] as? JsonPrimitive)?.takeIf { !it.isString && it !is JsonNull }?.long
        fun b(name: String, default: Boolean): Boolean = (kw[name] as? JsonPrimitive)?.booleanOrNull ?: default
        misses.expect(r) {
            steps(when (r.fn.removePrefix("caracole.web.jobs.")) {
                "add_steps" -> JobCommands.addSteps(a[0], a[1], s("album"), l("duration_ms"), s("lacuerda"))
                "fetch_steps" -> JobCommands.fetchSteps(a[0])
                "lookup_steps" -> JobCommands.lookupSteps(a[0], a[1], s("album"), l("duration_ms"), s("ug"), s("tab"),
                                                          s("lacuerda"), s("harptabs"), s("gametabs"), b("songbooks", true))
                "version_steps" -> JobCommands.versionSteps(a[0], a[1], s("keep"), s("choose"), b("keep_more", false))
                "remove_steps" -> JobCommands.removeSteps(a[0])
                "review_steps" -> JobCommands.reviewSteps(a[0], s("pick"),
                                                          (kw["seen"] as? JsonArray)?.map { it.jsonPrimitive.content } ?: emptyList())
                "lacuerda_artist_steps" -> JobCommands.lacuerdaArtistSteps(a[0], a[1])
                "lacuerda_search_steps" -> JobCommands.lacuerdaSearchSteps(a[0], b("auto", false))
                "harptabs_artist_steps" -> JobCommands.harptabsArtistSteps(a[0], a[1])
                else -> throw IllegalArgumentException("no builder ${r.fn}")
            })
        }
    }

    private fun argv(value: JsonElement): List<String> = value.jsonArray.map { it.jsonPrimitive.content }

    private fun rule(misses: Misses, r: Record) {
        misses.expect(r) {
            when (r.fn.removePrefix("caracole.web.jobs.")) {
                "_looks_up" -> JobCommands.looksUp(argv(r.args[0]))
                "_reports" -> JobCommands.reports(argv(r.args[0]))
                "_fetches" -> JobCommands.fetches(r.args[0].jsonArray.map(::argv))
                "_pick" -> JobCommands.pick(r.args[0].jsonArray.map(::argv))
                "_stages" -> JobCommands.stages(r.args[0].jsonArray.map(::argv)).map { (name, label) -> listOf(name, label) }
                else -> throw IllegalArgumentException("no rule ${r.fn}")
            }
        }
    }

    // --- queues -----------------------------------------------------------------------------------------------

    private fun same(a: JsonElement?, b: JsonElement?): Boolean =
        PyJson.dumps(a ?: JsonNull, sortKeys = true) == PyJson.dumps(b ?: JsonNull, sortKeys = true)

    private fun obj(vararg pairs: Pair<String, Any?>): JsonObject = JsonObject(pairs.associate { (k, v) ->
        k to when (v) {
            null -> JsonNull
            is JsonElement -> v
            is Int -> JsonPrimitive(v)
            is Boolean -> JsonPrimitive(v)
            is String -> JsonPrimitive(v)
            else -> throw IllegalArgumentException("$v")
        }
    })

    /** A request of the record's as the phone's JobSpec: its commands, its kind as JobCommands tells it. */
    private fun spec(request: JsonObject): JobSpec {
        val commands = request.getValue("steps").jsonArray.map { step ->
            val (label, args) = step.jsonArray
            Command(label.jsonPrimitive.content, argv(args))
        }
        val key = request.getValue("song_key").jsonPrimitive.content
        return JobSpec(title = request.getValue("title").jsonPrimitive.content, key = key,
                       kind = JobCommands.kindOf(key, commands.map { it.args }, emptyList()), stages = emptyList(),
                       display = request.getValue("display").jsonPrimitive.content,
                       songId = (request["song_id"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.long,
                       join = request.getValue("join").jsonPrimitive.boolean, commands = commands,
                       fetching = request.getValue("fetching").jsonPrimitive.boolean,
                       note = request.getValue("note").jsonPrimitive.content)
    }

    private class Queue(val misses: Misses, val note: String, val scope: CoroutineScope, val file: File?) {
        lateinit var queue: JobQueue
        val pending = ArrayDeque<JsonObject>()

        fun jobs(): JsonArray =
            JsonArray(queue.snapshot().asReversed().map { JobHistory.record(it, Int.MAX_VALUE, Int.MAX_VALUE) })

        fun text(): JsonElement = file?.takeIf { it.isFile }?.readText(Charsets.UTF_8)?.let(::JsonPrimitive) ?: JsonNull

        /** The queue's jobs and its history's file as the record says they are now. */
        fun state(at: String, want: JsonObject) {
            val jobs = jobs()
            misses.check(same(jobs, want["jobs"])) {
                "$note, $at: the jobs\n  ${PyJson.dumps(jobs, sortKeys = true).take(3000)}\n  Python's " +
                    PyJson.dumps(want["jobs"] ?: JsonNull, sortKeys = true).take(3000)
            }
            if (file != null) {
                val text = text()
                misses.check(same(text, want["file"])) { "$note, $at: the history's file\n  $text\n  Python's ${want["file"]}" }
            }
        }

        suspend fun perform(op: JsonObject) {
            val at = "${op["op"]?.jsonPrimitive?.content} ${PyJson.dumps(op["request"] ?: op["job"] ?: JsonNull).take(120)}"
            val out: JsonElement = try {
                when (val kind = op.getValue("op").jsonPrimitive.content) {
                    "submit" -> try {
                        val (job, new) = queue.submit(spec(op.getValue("request").jsonObject))
                        obj("job" to job.id, "new" to new)
                    } catch (e: QueueFull) {
                        obj("err" to "QueueFull")
                    }
                    "submit_all" -> try {
                        JsonArray(queue.submitAll(op.getValue("requests").jsonArray.map { spec(it.jsonObject) })
                                      .map { (job, new) -> JsonArray(listOf(JsonPrimitive(job.id), JsonPrimitive(new))) })
                    } catch (e: QueueFull) {
                        obj("err" to "QueueFull")
                    }
                    "cancel" -> try {
                        queue.cancel(op.getValue("job").jsonPrimitive.int)?.let { obj("job" to it.id) } ?: JsonNull
                    } catch (e: JobStarted) {
                        obj("err" to "JobStarted", "state" to e.state)
                    }
                    "again" -> try {
                        obj("job" to queue.again(op.getValue("job").jsonPrimitive.int).id)
                    } catch (e: NoSuchElementException) {
                        obj("err" to 404)
                    } catch (e: JobNotOver) {
                        obj("err" to 409)
                    } catch (e: QueueFull) {
                        obj("err" to 503)
                    }
                    "run" -> {
                        pending.clear()
                        op.getValue("steps").jsonArray.forEach { pending.addLast(it.jsonObject) }
                        val next = queue.snapshot().asReversed().firstOrNull { it.state == Job.QUEUED }
                        if (next == null) JsonNull else {
                            queue.await(next.id)
                            misses.check(pending.isEmpty()) { "$note, $at: steps left, ${pending.size}" }
                            JsonPrimitive(next.id)
                        }
                    }
                    else -> throw IllegalArgumentException("no such op: $kind")
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                misses.check(false) { "$note, $at: threw $e" }
                return
            }
            misses.check(same(out, op["out"])) { "$note, $at: answered $out, Python ${op["out"]}" }
            state(at, op)
        }

        /** The record's runner: each command follows the next step of the op that runs it. */
        val runner = CommandRunner { args, context -> follow(args, context) }

        private suspend fun follow(args: List<String>, context: JobContext) {
            val step = pending.removeFirstOrNull()
            if (step == null) {
                misses.check(false) { "$note: $args ran with no step left" }
                throw IllegalStateException("no step left")
            }
            val want = argv(step.getValue("args"))
            misses.check(want == args) { "$note: ran $args, Python's step $want" }
            for (action in step.getValue("do").jsonArray.map { it.jsonObject }) {
                when {
                    "event" in action -> event(context, action.getValue("event").jsonObject)
                    "line" in action -> context.say(action.getValue("line").jsonPrimitive.content)
                    "stop" in action -> {
                        scope.cancel()  // the worker's end, as the server stops
                        currentCoroutineContext().ensureActive()
                    }
                    else -> perform(action)
                }
            }
            val code = (step["code"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.int ?: 0
            if (code != 0) throw CommandExit(code, step.getValue("error").jsonPrimitive.content)
        }

        private fun event(context: JobContext, e: JsonObject) {
            (e["stage"] as? JsonPrimitive)?.takeIf { it.isString }?.let { stage ->
                context.stage(stage.content, e.getValue("state").jsonPrimitive.content,
                              (e["detail"] as? JsonPrimitive)?.contentOrEmpty() ?: "")
            }
            (e["song"] as? JsonObject)?.let { song ->
                context.song(song.getValue("id").jsonPrimitive.long,
                             (song["display"] as? JsonPrimitive)?.contentOrEmpty() ?: "")
            }
            (e["files"] as? JsonObject)?.let { files ->
                context.readable(files.mapValues { it.value.jsonPrimitive.content }, e.getValue("seconds").jsonPrimitive.double)
            }
        }

        private fun JsonPrimitive.contentOrEmpty(): String = if (this is JsonNull) "" else content
    }

    private fun queue(misses: Misses, r: Record, dir: File) {
        val note = r.extra["note"]?.jsonPrimitive?.content ?: "a queue"
        val kw = r.kw
        val history = r.extra["history"] as? JsonObject
        val file = if (history != null) File(dir, "requests.jsonl") else null
        (history?.get("file") as? JsonPrimitive)?.takeIf { it.isString }?.let { file!!.writeText(it.content, Charsets.UTF_8) }
        var now = START.minusSeconds(1)
        val clock = { now = now.plusSeconds(1); now }
        runBlocking {
            val scope = CoroutineScope(coroutineContext + SupervisorJob(coroutineContext[kotlinx.coroutines.Job]))
            val replay = Queue(misses, note, scope, file)
            val words = listOf("add", "fetch", "get", "harptabs", "index", "lacuerda", "match", "peer", "remove",
                               "render", "review", "songbook", "versions", "youtube")
            replay.queue = JobQueue(scope, kw.getValue("limit").jsonPrimitive.int, kw.getValue("keep").jsonPrimitive.int,
                                    clock, Commands(words.associateWith { replay.runner }),
                                    file?.let { JobHistory(it, clock = clock) })
            replay.state("as it starts", r.extra.getValue("loaded").jsonObject)
            for (op in r.extra.getValue("ops").jsonArray) replay.perform(op.jsonObject)
            scope.cancel()
        }
    }

    // --- the history ------------------------------------------------------------------------------------------

    private fun history(misses: Misses, r: Record, dir: File) {
        val note = r.extra["note"]?.jsonPrimitive?.content ?: "a history"
        val file = File(dir, "requests.jsonl")
        dir.mkdirs()
        (r.extra["file"] as? JsonPrimitive)?.takeIf { it.isString }?.let { file.writeText(it.content, Charsets.UTF_8) }
        (r.extra["file_b64"] as? JsonPrimitive)?.let { file.writeBytes(Base64.getDecoder().decode(it.content)) }
        val kw = r.kw
        var now = START
        val history = JobHistory(file, keep = kw.getValue("keep").jsonPrimitive.int, days = kw.getValue("days").jsonPrimitive.int,
                                 lines = kw.getValue("lines").jsonPrimitive.int,
                                 lineChars = kw.getValue("line_chars").jsonPrimitive.int,
                                 maxBytes = kw.getValue("max_bytes").jsonPrimitive.long, clock = { now })
        fun text(): JsonElement = if (file.isFile) JsonPrimitive(file.readText(Charsets.UTF_8)) else JsonNull
        for (element in r.extra.getValue("ops").jsonArray) {
            val op = element.jsonObject
            val kind = op.getValue("op").jsonPrimitive.content
            val want = op.getValue("out").jsonObject
            val got: JsonObject = try {
                when (kind) {
                    "load" -> {
                        val loaded = history.load(JobHistory.time(op.getValue("now")))
                        obj("jobs" to JsonArray(loaded.jobs.map { JobHistory.record(it, Int.MAX_VALUE, Int.MAX_VALUE) }),
                            "next" to loaded.nextId, "file" to text())
                    }
                    "save" -> {
                        val listed = op.getValue("jobs").jsonArray.map { JobHistory.jobOf(it.jsonObject) }
                        val record = op.getValue("job").jsonObject
                        val id = record.getValue("id").jsonPrimitive.int
                        val job = listed.firstOrNull { it.id == id } ?: JobHistory.jobOf(record)
                        now = JobHistory.time(op.getValue("now"))
                        history.save(job, listed, op.getValue("next").jsonPrimitive.int)
                        obj("file" to text())
                    }
                    "rewrite" -> {
                        history.rewrite(op.getValue("jobs").jsonArray.map { JobHistory.jobOf(it.jsonObject) },
                                        op.getValue("next").jsonPrimitive.int)
                        obj("file" to text())
                    }
                    else -> throw IllegalArgumentException("no such op: $kind")
                }
            } catch (e: Exception) {
                misses.check(false) { "$note, $kind: threw $e" }
                continue
            }
            misses.check(same(got, want)) {
                "$note, $kind:\n  ${PyJson.dumps(got, sortKeys = true).take(3000)}\n  Python's " +
                    PyJson.dumps(want, sortKeys = true).take(3000)
            }
        }
    }
}
