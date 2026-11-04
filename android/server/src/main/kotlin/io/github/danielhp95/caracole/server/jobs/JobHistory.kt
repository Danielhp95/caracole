package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.math.BigDecimal
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.SecureRandom
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.logging.Logger

/**
 * web/history.py on the phone: the requests the queue remembers, kept across a restart in [file]
 * (`stateDir/requests.jsonl`, [at]), its format 1 byte for byte, so that the Requests tab shows them again.
 *
 * - A line a request as it stood when it last changed (`{"v":1,"id":12,"title":…}`, every field of web/jobs.py's Job,
 *   its steps with what each command printed, its stages, its times), or the first line of a file written whole,
 *   `{"v":1,"next":31}`, the id the next request gets. The queue saves a request when it is queued or joined, when it
 *   starts and when it is over or cancelled ([save]: a line appended in one write); its last line is what it was.
 * - [load]: the requests of the last [days] days, the [keep] newest of them, the ids after theirs; one that waited or
 *   ran when the phone's caracole stopped is interrupted (its running step and stage too, the rest skipped); a line
 *   that can't be read (cut short, not JSON, not a request of this version) is skipped. The file is written whole
 *   again with them.
 * - It never grows without bound: a step keeps its last [lines] lines of [lineChars] characters at most, and the file
 *   is written whole again ([rewrite]: a temporary file in the same folder, synced, then renamed over it) with the
 *   requests the queue remembers when it holds more than three lines a request kept or more than [maxBytes].
 * - The file is private (0600) in a private folder (0700). Nothing here ever stops a request: a history that can't be
 *   read or written is logged, and the queue goes on.
 *
 * A request the phone ran with a run of its own (an add, a removal, a sync, an index import, the render job) has no
 * command, and format 1 keeps a command's output alone: its line adds what format 1 can't say, `"phone": {"kind",
 * "done_line", "said"}` (its JobSpec.kind, its doneLine, what its run said), which history.py's reader leaves be, so
 * the file is one it reads still; a request of commands alone has none (its kind JobCommands.kindOf's, as caracole
 * serve's views tell it), so its line is caracole serve's byte for byte. Read back, such a request can't be run again (JobQueue.again's
 * JobNotRepeatable). Its times are read as Python 3.14's `datetime.fromisoformat` reads them ([parseIso]); its whole
 * numbers as Python's ints, but an id, a code, a count or a `together` past Int's range, which the phone never writes,
 * makes its line one that can't be read. [clock] is when a save writes the file whole (the requests of the last [days]
 * days kept).
 */
class JobHistory(val file: File, val keep: Int = JobQueue.KEEP, val days: Int = DAYS, val lines: Int = LINES,
                 val lineChars: Int = LINE_CHARS, val maxBytes: Long = MAX_BYTES,
                 private val clock: () -> Instant = { Instant.now() }) {
    /** What [load] read back: the requests to show again, oldest first, and the id the next request gets. */
    data class Loaded(val jobs: List<Job>, val nextId: Int)

    private var count = 0  // lines in the file
    private var size = 0L  // its bytes
    private var failed = false  // the last write failed: said once until one succeeds

    // --- reading ----------------------------------------------------------------------------------------------------

    /** The requests to show again, oldest first, each one that waited or ran interrupted, and the id the next request
     * gets; the file written again whole with them. */
    fun load(now: Instant): Loaded {
        val data = try {
            read() ?: return Loaded(emptyList(), 1)
        } catch (e: IOException) {
            log.warning("caracole: its request history $file can't be read (${e.message}): it starts with none")
            return Loaded(emptyList(), 1)
        }
        val jobs = LinkedHashMap<Int, Job>()
        var nextId = 1
        var skipped = 0
        for (line in splitLines(data)) {
            if (line.all { it.toInt().toChar() in ASCII_SPACE }) continue
            try {
                val record = PyJson.loads(decode(line)) as? JsonObject ?: throw Bad("not an object")
                if (!isVersion(record["v"])) throw Bad("not a record of this version")
                if ("next" in record && "id" !in record) {
                    nextId = maxOf(nextId, int(record.getValue("next")))
                    continue
                }
                val job = jobOf(record)
                jobs[job.id] = job
                nextId = maxOf(nextId, job.id + 1)
            } catch (e: Exception) {  // Bad, PyJson's DecodeError and RecursionError, a decoding's
                skipped++
            }
        }
        if (skipped > 0) {
            log.warning("caracole: $skipped line(s) of its request history $file couldn't be read and are left out")
        }
        for (job in jobs.values) {
            if (job.active) interrupt(job, job.finishedAt ?: job.startedAt ?: job.queuedAt)
        }
        val kept = kept(jobs.values.sortedBy { it.id }, now)
        rewrite(kept, nextId)
        return Loaded(kept, nextId)
    }

    /** The file's bytes, or, of a file grown beyond its size (its rewrites failing), its end alone, from its first
     * whole line; null for no file. */
    private fun read(): ByteArray? {
        if (!file.exists()) return null
        RandomAccessFile(file, "r").use { f ->
            val size = f.length()
            if (size > READ_AT_MOST) {
                f.seek(size - READ_AT_MOST)
                while (true) {
                    val b = f.read()
                    if (b < 0 || b == '\n'.code) break
                }
            }
            val rest = ByteArray((size - f.filePointer).coerceAtLeast(0).toInt())
            f.readFully(rest)
            return rest
        }
    }

    /** Of [jobs] (oldest first), those a file written whole keeps: every one waiting or running, and the [keep]
     * newest of those over within [days] days. */
    private fun kept(jobs: List<Job>, now: Instant): List<Job> {
        val since = now.minus(Duration.ofDays(days.toLong()))
        val over = jobs.filter { !it.active && !(it.finishedAt ?: it.queuedAt).isBefore(since) }
        val keptIds = over.drop(maxOf(0, over.size - keep)).map { it.id }.toSet()
        return jobs.filter { it.active || it.id in keptIds }
    }

    // --- writing ----------------------------------------------------------------------------------------------------

    /** Adds [job] as it is now, in one write; then, when the file holds too much, writes it again whole with [jobs]
     * (the queue's, oldest first) and [nextId]. */
    fun save(job: Job, jobs: List<Job>, nextId: Int) {
        val line = line(record(job, lines, lineChars))
        try {
            folder()
            if (!file.exists()) createPrivate(file.toPath())
            FileOutputStream(file, true).use { it.write(line) }
        } catch (e: Exception) {
            couldNot("add to", e)
            return
        }
        ok()
        count += 1
        size += line.size
        if (count > 3 * keep || size > maxBytes) rewrite(kept(jobs, clock()), nextId)
    }

    /** Writes the file again whole: its first line [nextId], then [jobs] (oldest first), the oldest over left out while
     * it holds more than [maxBytes] (never the newest, nor one waiting or running). */
    fun rewrite(jobs: List<Job>, nextId: Int) {
        val written = jobs.map { line(record(it, lines, lineChars)) }
        val head = line(JsonObject(linkedMapOf("v" to JsonPrimitive(VERSION), "next" to JsonPrimitive(nextId))))
        var total = head.size.toLong() + written.sumOf { it.size.toLong() }
        val dropped = HashSet<Int>()
        for (n in 0 until maxOf(0, jobs.size - 1)) {
            if (total <= maxBytes) break
            if (!jobs[n].active) {
                dropped += n
                total -= written[n].size
            }
        }
        val data = java.io.ByteArrayOutputStream().apply {
            write(head)
            written.forEachIndexed { n, bytes -> if (n !in dropped) write(bytes) }
        }.toByteArray()
        val temporary = File(file.absoluteFile.parentFile, ".${file.name}.${token()}.tmp")
        try {
            folder()
            createPrivate(temporary.toPath())
            FileOutputStream(temporary).use { out ->
                out.write(data)
                out.fd.sync()
            }
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            syncFolder(file.absoluteFile.parentFile)
        } catch (e: Exception) {
            runCatching { temporary.delete() }
            couldNot("write", e)
            return
        }
        ok()
        count = 1 + written.size - dropped.size
        size = data.size.toLong()
    }

    private fun line(record: JsonObject): ByteArray = (PyJson.dumps(record, compact = true) + "\n").toByteArray(Charsets.UTF_8)

    private fun couldNot(what: String, e: Exception) {
        if (!failed) {
            log.warning("caracole: can't $what its request history $file (${e.message}): the requests go on, and a " +
                        "restart may forget them")
        }
        failed = true
    }

    private fun ok() {
        if (failed) log.info("caracole: its request history $file is written again")
        failed = false
    }

    /** The file's folder, made private (0700) when it is made. */
    private fun folder() {
        val parent = file.absoluteFile.parentFile ?: return
        if (parent.isDirectory) return
        parent.parentFile?.mkdirs()
        if (parent.mkdir()) {
            try {
                Files.setPosixFilePermissions(parent.toPath(), PosixFilePermissions.fromString("rwx------"))
            } catch (e: UnsupportedOperationException) {
                parent.setReadable(false, false); parent.setReadable(true, true)
                parent.setWritable(false, false); parent.setWritable(true, true)
                parent.setExecutable(false, false); parent.setExecutable(true, true)
            }
        }
    }

    companion object {
        const val FILE_NAME = "requests.jsonl"
        const val VERSION = 1
        const val DAYS = 30  // a request over longer ago than this is not read back (and the newest KEEP at most)
        const val LINES = 200  // the last lines of a step's output kept
        const val LINE_CHARS = 1000  // characters of a line kept
        const val MAX_BYTES = 4L * 1024 * 1024  // the file written whole beyond this
        private const val READ_AT_MOST = 4 * MAX_BYTES  // of a file grown beyond its size: its end alone is read
        private val JOB_STATES = setOf(Job.QUEUED, Job.RUNNING, Job.DONE, Job.FAILED, Job.CANCELLED, Job.INTERRUPTED)
        private val STEP_STATES = setOf(Job.WAITING, Job.RUNNING, Job.DONE, Job.FAILED, Job.SKIPPED, Job.INTERRUPTED)
        private val ASCII_SPACE = setOf(' ', '\t', '\n', '\r', '\u000b', '\u000c')  // bytes.strip()'s
        private val log: Logger = Logger.getLogger("caracole.history")
        private val random = SecureRandom()

        /** The phone's history: `stateDir/requests.jsonl`. */
        fun at(stateDir: File): JobHistory = JobHistory(File(stateDir, FILE_NAME))

        /** A request the phone stopped before it was over: interrupted, its running step and stage too, those waiting
         * skipped; over [at], unless it says when already (history.py's interrupt). */
        internal fun interrupt(job: Job, at: Instant) {
            job.state = Job.INTERRUPTED
            job.finishedAt = job.finishedAt ?: at
            for (step in job.steps) {
                if (step.state == Job.RUNNING) step.state = Job.INTERRUPTED
                else if (step.state == Job.WAITING) step.state = Job.SKIPPED
            }
            for (stage in job.stages) {
                if (stage.state == Job.RUNNING) stage.state = Job.INTERRUPTED
                else if (stage.state == Job.WAITING) stage.state = Job.SKIPPED
            }
        }

        // --- a request as a line, and back -----------------------------------------------------------------------

        /** A request as its line holds it (history.py's _record): a step's last [lines] lines, each of [lineChars]
         * characters at most. */
        fun record(job: Job, lines: Int = LINES, lineChars: Int = LINE_CHARS): JsonObject = JsonObject(linkedMapOf(
            "v" to JsonPrimitive(VERSION),
            "id" to JsonPrimitive(job.id),
            "title" to JsonPrimitive(job.title),
            "song_key" to JsonPrimitive(job.key),
            "display" to JsonPrimitive(job.named),
            "state" to JsonPrimitive(job.state),
            "fetching" to JsonPrimitive(job.fetching),
            "note" to JsonPrimitive(job.note),
            "queued_at" to JsonPrimitive(iso(job.queuedAt)),
            "started_at" to (job.startedAt?.let { JsonPrimitive(iso(it)) } ?: JsonNull),
            "finished_at" to (job.finishedAt?.let { JsonPrimitive(iso(it)) } ?: JsonNull),
            "steps" to JsonArray(job.steps.map { step(it, lines, lineChars) }),
            "stages" to JsonArray(job.stages.map { stage ->
                JsonObject(linkedMapOf("name" to JsonPrimitive(stage.name), "label" to JsonPrimitive(stage.label),
                                       "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail),
                                       "running_detail" to JsonPrimitive(stage.runningDetail)))
            }),
            "song_id" to (job.songId?.let(::JsonPrimitive) ?: JsonNull),
            "song_display" to (job.songDisplay?.let(::JsonPrimitive) ?: JsonNull),
            "files" to JsonObject(job.files.mapValues { JsonPrimitive(it.value) }),
            "seconds_to_sheet" to (job.secondsToSheet?.let(PyJson::float) ?: JsonNull),
            "together" to JsonArray(job.together.map(::JsonPrimitive)),
            "units" to JsonArray(job.units.map { JsonArray(listOf(JsonPrimitive(it.id), JsonPrimitive(it.outcome),
                                                                   JsonPrimitive(it.why))) }),
        ) + phone(job, lines, lineChars))

        /** What a request of the phone's own (a run of its own, or read back as one) says that format 1 can't: its
         * kind, its doneLine, what its run said (its last [lines] lines, each of [lineChars] at most); nothing for a
         * request of commands alone, as caracole serve queues them. */
        private fun phone(job: Job, lines: Int, lineChars: Int): Map<String, JsonElement> {
            if (job.spec.run == null && !job.readOwn) return emptyMap()
            val said = if (lines > 0) job.said.takeLast(lines) else emptyList()
            return mapOf("phone" to JsonObject(linkedMapOf(
                "kind" to JsonPrimitive(job.spec.kind),
                "done_line" to (job.spec.doneLine?.let(::JsonPrimitive) ?: JsonNull),
                "said" to JsonArray(said.map { JsonPrimitive(cut(it, lineChars)) }),
            )))
        }

        private fun step(step: Step, lines: Int, lineChars: Int): JsonObject {
            val output = if (lines > 0) step.output.takeLast(lines) else emptyList()
            return JsonObject(linkedMapOf(
                "label" to JsonPrimitive(step.label),
                "args" to JsonArray(step.args.map(::JsonPrimitive)),
                "state" to JsonPrimitive(step.state),
                "code" to (step.code?.let(::JsonPrimitive) ?: JsonNull),
                "output" to JsonArray(output.map { JsonPrimitive(cut(it, lineChars)) }),
                "dropped" to JsonPrimitive(step.dropped + step.output.size - output.size),
            ))
        }

        /** A line of at most [chars] characters (code points), else its first chars − 1 and "…". */
        private fun cut(line: String, chars: Int): String {
            if (line.codePointCount(0, line.length) <= chars) return line
            return line.substring(0, line.offsetByCodePoints(0, maxOf(0, chars - 1))) + "…"
        }

        /**
         * A request from its line (history.py's _job), as the queue holds it: its [JobSpec] made of what the line
         * keeps (its kind the line's `phone` one, else JobCommands.kindOf's), never a run of its own.
         * [IllegalArgumentException] for one that isn't one; a `phone` that isn't one is left be, as history.py
         * leaves it.
         */
        fun jobOf(record: JsonObject): Job {
            val state = str(record.required("state"))
            if (state !in JOB_STATES) throw Bad("no such state: $state")
            val id = int(record.required("id"))
            val title = str(record.required("title"))
            val key = str(record.required("song_key"))
            val steps = list(record.required("steps")).map(::stepOf)
            val fetching = bool(record.opt("fetching", JsonPrimitive(false)))
            val note = str(record.opt("note", JsonPrimitive("")))
            val display = str(record.opt("display", JsonPrimitive("")))
            val queuedAt = time(record.required("queued_at"))
            val startedAt = maybe(record["started_at"])?.let(::time)
            val finishedAt = maybe(record["finished_at"])?.let(::time)
            val stages = list(record.opt("stages", JsonArray(emptyList()))).map(::stageOf)
            val songId = maybe(record["song_id"])?.let(::long)
            val songDisplay = maybe(record["song_display"])?.let(::str)
            val files = dict(record.opt("files", JsonObject(emptyMap()))).mapValues { str(it.value) }
            val seconds = maybe(record["seconds_to_sheet"])?.let(::number)
            val together = list(record.opt("together", JsonArray(emptyList()))).map(::int)
            val units = list(record.opt("units", JsonArray(emptyList()))).map { unit ->
                val parts = list(unit)
                if (parts.size != 3) throw Bad("not a unit: $unit")
                JobUnit(str(parts[0]), str(parts[1]), str(parts[2]))
            }
            val commands = steps.map { it.command }
            val phone = runCatching { phoneOf(record["phone"]) }.getOrNull()
            val spec = JobSpec(title = title, key = key,
                               kind = phone?.kind ?: JobCommands.kindOf(key, commands.map { it.args }, stages.map { it.name }),
                               stages = emptyList(), display = display, songId = songId, commands = commands,
                               fetching = fetching, note = note, doneLine = phone?.doneLine)
            return Job(id, spec, queuedAt).also { job ->
                job.state = state
                job.startedAt = startedAt
                job.finishedAt = finishedAt
                job.steps = steps
                job.stages = stages
                job.songId = songId
                job.songDisplay = songDisplay
                job.files = LinkedHashMap(files)
                job.secondsToSheet = seconds
                job.together = together
                job.units = units
                job.named = display
                job.said = phone?.said ?: emptyList()
                job.readOwn = phone != null
            }
        }

        private class Phone(val kind: String, val doneLine: String?, val said: List<String>)

        private fun phoneOf(value: JsonElement?): Phone? {
            val record = value as? JsonObject ?: return null
            return Phone(str(record.required("kind")), maybe(record["done_line"])?.let(::str),
                         list(record.opt("said", JsonArray(emptyList()))).map(::str))
        }

        private fun stepOf(value: JsonElement): Step {
            val record = dict(value)
            val state = str(record.required("state"))
            if (state !in STEP_STATES) throw Bad("no such state: $state")
            return Step(str(record.required("label")), list(record.required("args")).map(::str)).also { step ->
                step.state = state
                step.code = maybe(record["code"])?.let(::int)
                step.output = list(record.opt("output", JsonArray(emptyList()))).map(::str)
                step.dropped = int(record.opt("dropped", JsonPrimitive(0)))
            }
        }

        private fun stageOf(value: JsonElement): Stage {
            val record = dict(value)
            return Stage(str(record.required("name")), str(record.required("label"))).also { stage ->
                stage.state = str(record.opt("state", JsonPrimitive(Job.WAITING)))
                stage.detail = str(record.opt("detail", JsonPrimitive("")))
                stage.runningDetail = str(record.opt("running_detail", JsonPrimitive("")))
            }
        }

        /** A line that isn't a request (history.py's ValueError, TypeError or KeyError). */
        private class Bad(message: String) : IllegalArgumentException(message)

        private fun JsonObject.required(name: String): JsonElement = this[name] ?: throw Bad("no $name")
        private fun JsonObject.opt(name: String, default: JsonElement): JsonElement = this[name] ?: default
        private fun maybe(value: JsonElement?): JsonElement? = if (value == null || value is JsonNull) null else value

        private fun str(value: JsonElement): String =
            (value as? JsonPrimitive)?.takeIf { it.isString }?.content ?: throw Bad("not a string: $value")

        private val WHOLE = Regex("-?(0|[1-9][0-9]*)")

        /** The text of a whole number as PyJson.loads gives a Python int (never true or false, nor a float). */
        private fun whole(value: JsonElement): String {
            val primitive = value as? JsonPrimitive
            if (primitive == null || primitive.isString || primitive is JsonNull || !WHOLE.matches(primitive.content)) {
                throw Bad("not a whole number: $value")
            }
            return primitive.content
        }

        /** A whole number that is an Int (an id, a code, a count): one past its range can't be the phone's. */
        private fun int(value: JsonElement): Int = whole(value).toIntOrNull() ?: throw Bad("too large: $value")

        /** A whole number that is a Long (a song's id). */
        private fun long(value: JsonElement): Long = whole(value).toLongOrNull() ?: throw Bad("too large: $value")

        /** A Python int or float as `float(value)`: a literal of PyJson.loads (an int's digits, a float's repr, NaN,
         * Infinity), never true or false. */
        private fun number(value: JsonElement): Double {
            val primitive = value as? JsonPrimitive
            if (primitive == null || primitive.isString || primitive is JsonNull ||
                primitive.content == "true" || primitive.content == "false") {
                throw Bad("not a number: $value")
            }
            return when (primitive.content) {
                "NaN" -> Double.NaN
                "Infinity" -> Double.POSITIVE_INFINITY
                "-Infinity" -> Double.NEGATIVE_INFINITY
                else -> if (NUMBER.matches(primitive.content)) primitive.content.toDouble() else throw Bad("not a number: $value")
            }
        }

        private val NUMBER = Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][-+]?[0-9]+)?")

        private fun bool(value: JsonElement): Boolean {
            val primitive = value as? JsonPrimitive
            if (primitive == null || primitive.isString || primitive is JsonNull) throw Bad("not true or false: $value")
            return when (primitive.content) {
                "true" -> true
                "false" -> false
                else -> throw Bad("not true or false: $value")
            }
        }

        private fun list(value: JsonElement): List<JsonElement> = value as? JsonArray ?: throw Bad("not a list: $value")

        private fun dict(value: JsonElement): JsonObject = value as? JsonObject ?: throw Bad("not an object: $value")

        /** `record.get("v") == 1` as Python compares it: 1, 1.0, and true too. */
        private fun isVersion(value: JsonElement?): Boolean {
            val primitive = value as? JsonPrimitive ?: return false
            if (primitive.isString || primitive is JsonNull) return false
            if (primitive.content == "true") return true
            if (primitive.content == "false") return false
            return try {
                BigDecimal(primitive.content).compareTo(BigDecimal.ONE) == 0
            } catch (e: NumberFormatException) {
                false
            }
        }

        /** bytes.splitlines(): at `\n`, `\r\n` and `\r`. */
        private fun splitLines(data: ByteArray): List<ByteArray> {
            val out = ArrayList<ByteArray>()
            var start = 0
            var i = 0
            while (i < data.size) {
                val b = data[i]
                if (b == '\n'.code.toByte() || b == '\r'.code.toByte()) {
                    out += data.copyOfRange(start, i)
                    i += if (b == '\r'.code.toByte() && i + 1 < data.size && data[i + 1] == '\n'.code.toByte()) 2 else 1
                    start = i
                } else {
                    i++
                }
            }
            if (start < data.size) out += data.copyOfRange(start, data.size)
            return out
        }

        /** Strict UTF-8, as `bytes.decode("utf-8")`: a byte sequence that isn't throws. */
        private fun decode(line: ByteArray): String = Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(line)).toString()

        private fun token(): String = ByteArray(6).also(random::nextBytes).joinToString("") { "%02x".format(it) }

        private fun createPrivate(path: Path) {
            try {
                Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))
            } catch (e: UnsupportedOperationException) {
                Files.createFile(path)
                val file = path.toFile()
                file.setReadable(false, false); file.setReadable(true, true)
                file.setWritable(false, false); file.setWritable(true, true)
            }
        }

        /** Syncs the folder, so that a rename survives a crash; a system that can't is let be. */
        private fun syncFolder(folder: File) {
            try {
                FileChannel.open(folder.toPath(), StandardOpenOption.READ).use { it.force(true) }
            } catch (e: Exception) {
                // as history.py: let be
            }
        }

        // --- times ------------------------------------------------------------------------------------------------

        /** A time as history.py writes one: `datetime.isoformat()` in UTC, `2026-11-03T09:30:00+00:00`, its
         * microseconds when it has any. */
        fun iso(at: Instant): String {
            val t = at.atOffset(ZoneOffset.UTC)
            val micros = t.nano / 1000
            val base = "${pad(t.year, 4)}-${pad(t.monthValue, 2)}-${pad(t.dayOfMonth, 2)}T" +
                "${pad(t.hour, 2)}:${pad(t.minute, 2)}:${pad(t.second, 2)}"
            return base + (if (micros != 0) "." + pad(micros, 6) else "") + "+00:00"
        }

        private fun pad(n: Int, width: Int): String = n.toString().padStart(width, '0')

        /** history.py's `_time`: `datetime.fromisoformat` of a text ([parseIso]), a naive time UTC (stamps.py's). */
        fun time(value: JsonElement): Instant = parseIso(str(value))

        /**
         * `datetime.fromisoformat(text)` as CPython 3.14's C implementation reads it (Modules/_datetimemodule.c's
         * datetime_fromisoformat, step for step, over the text's UTF-8 bytes, a read past their end a NUL as the C
         * string's), a naive time taken as UTC; [IllegalArgumentException] where it raises ValueError. Its quirks are
         * Python's: a date `YYYY-MM-DD`, `YYYYMMDD` or an ISO week (`2026-W45-1`, `2026W451`, `2026-W45`); any one
         * character before the time; `HH[:MM[:SS[.f…]]]` or `HHMM[SS[f…]]`, a fraction's digits past six cut;
         * `24:00` the next day's start; any one character between the time and an offset (`09:30:00 +01:00`); an
         * offset `Z` or `±HH[:MM[:SS[.f…]]]` (`±HHMM…`), its parts unchecked but its whole within a day either way.
         * vectors/web/history.jsonl's `_time` records hold it to Python's answers.
         */
        internal fun parseIso(text: String): Instant = FromIsoformat(text).read()

        /** CPython 3.14's datetime_fromisoformat over [text], its functions by their C names. */
        private class FromIsoformat(val text: String) {
            private lateinit var b: ByteArray

            private fun bad(): Nothing = throw Bad("Invalid isoformat string: $text")

            /** The byte at [i], NUL past the end (the C string's terminator). */
            private fun at(i: Int): Int = if (i in b.indices) b[i].toInt() and 0xff else 0

            private fun isDigit(c: Int): Boolean = c in '0'.code..'9'.code

            /** parse_digits: [n] digits from [p] into a number, or null where one isn't a digit. */
            private fun digits(p: Int, n: Int): Int? {
                var v = 0
                for (k in 0 until n) {
                    val c = at(p + k)
                    if (!isDigit(c)) return null
                    v = v * 10 + (c - '0'.code)
                }
                return v
            }

            // datetime_fromisoformat ---------------------------------------------------------------------------

            fun read(): Instant {
                val points = text.codePoints().toArray()
                if (points.size < 7) bad()  // _sanitize_isoformat_str: "at least 7 characters long"
                for (pos in intArrayOf(7, 8, 10)) {  // a surrogate separator is read as T
                    if (pos > points.size) break
                    if (pos < points.size && points[pos] in 0xD800..0xDFFF) {
                        points[pos] = 'T'.code
                        break
                    }
                }
                if (points.any { it in 0xD800..0xDFFF }) bad()  // PyUnicode_AsUTF8AndSize's UnicodeEncodeError
                b = String(points, 0, points.size).toByteArray(Charsets.UTF_8)
                val len = b.size
                val separator = separator(len)
                if (separator < 0) bad()  // YYYY-Www- (9): no date reads
                val date = IntArray(3)
                var rv = date(separator, date)
                val time = IntArray(4)
                val tz = LongArray(2)
                if (rv == 0 && len > separator) {
                    var p = separator
                    val lead = at(p)
                    p += if (lead and 0x80 == 0) 1 else when (lead and 0xf0) {
                        0xe0 -> 3
                        0xf0 -> 4
                        else -> 2
                    }
                    rv = time(p, len - p, time, tz)
                }
                if (rv < 0) bad()
                // tzinfo_from_isoformat_results: an offset strictly within a day either way (new_timezone)
                val offsetMicros = if (rv == 1) tz[0] * 1_000_000L + tz[1] else null
                if (offsetMicros != null && (offsetMicros <= -DAY_MICROS || offsetMicros >= DAY_MICROS)) bad()
                var (year, month, day) = date
                var (hour, minute, second, micro) = time
                if (hour == 24 && month in 1..12) {
                    val inMonth = daysInMonth(year, month)
                    if (day <= inMonth) {
                        if (minute != 0 || second != 0 || micro != 0) {
                            throw Bad("minute, second, and microsecond must be 0 when hour is 24")
                        }
                        hour = 0
                        day += 1
                        if (day > inMonth) {
                            day = 1
                            month += 1
                            if (month > 12) {
                                month = 1
                                year += 1
                            }
                        }
                    }
                }
                // new_datetime: check_date_args, check_time_args
                if (year !in 1..9999 || month !in 1..12 || day < 1 || day > daysInMonth(year, month)) bad()
                if (hour !in 0..23 || minute !in 0..59 || second !in 0..59 || micro !in 0..999_999) bad()
                val local = LocalDateTime.of(year, month, day, hour, minute, second, micro * 1000)
                return local.toInstant(ZoneOffset.UTC).minusNanos((offsetMicros ?: 0L) * 1000L)
            }

            private fun daysInMonth(year: Int, month: Int): Int = when (month) {
                2 -> if (isLeap(year)) 29 else 28
                4, 6, 9, 11 -> 30
                else -> 31
            }

            private fun isLeap(year: Int): Boolean = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)

            /** _find_isoformat_datetime_separator: where the date ends, by its characters 4, 5, 8 and 10. */
            private fun separator(len: Int): Int {
                if (len == 7) return 7
                if (at(4) == '-'.code) {
                    if (at(5) == 'W'.code) {
                        if (len < 8) return -1
                        if (len > 8 && at(8) == '-'.code) {
                            if (len == 9) return -1
                            if (len > 10 && isDigit(at(10))) return 8
                            return 10
                        }
                        return 8
                    }
                    return 10
                }
                if (at(4) == 'W'.code) {
                    var idx = 7
                    while (idx < len) {
                        if (!isDigit(at(idx))) break
                        idx++
                    }
                    if (idx < 9) return idx
                    return if (idx % 2 == 0) 7 else 8
                }
                return 8
            }

            /** parse_isoformat_date: 0, its year, month and day in [out]; or a negative code. */
            private fun date(len: Int, out: IntArray): Int {
                var p = 0
                out[0] = digits(p, 4) ?: return -1
                p += 4
                val usesSeparator = at(p) == '-'.code
                if (usesSeparator) p++
                if (at(p) == 'W'.code) {
                    p++
                    val week = digits(p, 2) ?: return -3
                    p += 2
                    val weekDay: Int
                    if (p < len) {
                        if (usesSeparator && at(p++) != '-'.code) return -2
                        weekDay = digits(p, 1) ?: return -4
                    } else {
                        weekDay = 1
                    }
                    val rv = isoToYmd(out[0], week, weekDay, out)
                    return if (rv != 0) -3 + rv else 0
                }
                out[1] = digits(p, 2) ?: return -1
                p += 2
                if (usesSeparator && at(p++) != '-'.code) return -2
                out[2] = digits(p, 2) ?: return -1
                return 0
            }

            /** iso_to_ymd: an ISO year, week and weekday as a date in [out]; 0, or a negative code. */
            private fun isoToYmd(isoYear: Int, week: Int, weekDay: Int, out: IntArray): Int {
                if (isoYear < 1 || isoYear > 9999) return -4
                if (week <= 0 || week >= 53) {
                    var outOfRange = true
                    if (week == 53) {
                        val first = LocalDate.of(isoYear, 1, 1).dayOfWeek.value - 1  // Monday 0
                        if (first == 3 || (first == 2 && isLeap(isoYear))) outOfRange = false
                    }
                    if (outOfRange) return -2
                }
                if (weekDay <= 0 || weekDay >= 8) return -3
                val january1 = LocalDate.of(isoYear, 1, 1)
                val first = january1.dayOfWeek.value - 1
                var monday = -first.toLong()  // iso_week1_monday, from January 1st
                if (first > 3) monday += 7
                val date = january1.plusDays(monday + (week - 1) * 7L + weekDay - 1)
                out[0] = date.year
                out[1] = date.monthValue
                out[2] = date.dayOfMonth
                return 0
            }

            /** parse_hh_mm_ss_ff over [start, end): 0 at the string's end, 1 before something else, or a negative
             * code; hour, minute, second and microsecond in [out]. */
            private fun hhMmSsFf(start: Int, end: Int, out: IntArray): Int {
                out.fill(0)
                var p = start
                var hasSeparator = true
                var i = 0
                while (i < 3) {
                    out[i] = digits(p, 2) ?: return -3
                    p += 2
                    val c = at(p)
                    p++
                    if (i == 0) hasSeparator = c == ':'.code
                    if (c == '.'.code || c == ','.code) {
                        if (i < 2) return -3  // a decimal mark on the hour or the minute
                        if (p >= end) return -3  // no digit after it
                        break
                    } else if (p >= end) {
                        return if (c != 0) 1 else 0
                    } else if (hasSeparator && c == ':'.code) {
                        if (i == 2) return -4
                    } else if (!hasSeparator) {
                        p--
                    } else {
                        return -4
                    }
                    i++
                }
                val toParse = minOf(end - p, 6)
                var micro = digits(p, toParse) ?: return -3
                p += toParse
                if (toParse < 6) micro *= CORRECTION[toParse - 1]
                out[3] = micro
                while (isDigit(at(p))) p++  // the digits past six cut
                return if (at(p) != 0) 1 else 0
            }

            /** parse_isoformat_time over [len] bytes from [start]: 0 (no offset), 1 (an offset in [tz]: seconds,
             * microseconds), or a negative code; the time in [out]. */
            private fun time(start: Int, len: Int, out: IntArray, tz: LongArray): Int {
                val end = start + len
                var at = start
                do {
                    val c = at(at)
                    if (c == 'Z'.code || c == '+'.code || c == '-'.code) break
                } while (++at < end)
                val rv = hhMmSsFf(start, at, out)
                if (rv < 0) return rv
                if (at == end) return if (rv == 1) -5 else 0
                if (at(at) == 'Z'.code) {
                    tz[0] = 0
                    tz[1] = 0
                    return if (at(at + 1) != 0) -5 else 1
                }
                val sign = if (at(at) == '-'.code) -1 else 1
                val offset = IntArray(4)
                val parsed = hhMmSsFf(at + 1, end, offset)
                tz[0] = sign * (offset[0] * 3600L + offset[1] * 60L + offset[2])
                tz[1] = sign * offset[3].toLong()
                return if (parsed != 0) -5 else 1
            }

            companion object {
                private val CORRECTION = intArrayOf(100000, 10000, 1000, 100, 10)
                private const val DAY_MICROS = 86_400_000_000L
            }
        }
    }
}
