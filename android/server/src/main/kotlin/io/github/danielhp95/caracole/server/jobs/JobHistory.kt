package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.Json
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
 * A request the phone ran with a run of its own (an add, a removal, a sync, an index import) has no command: what it
 * said is not kept (format 1 keeps a command's output alone), and read back it can't be run again (JobQueue.again).
 * [clock] is when a save writes the file whole (the requests of the last [days] days kept).
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
                val record = Json.parseToJsonElement(decode(line)) as? JsonObject ?: throw Bad("not an object")
                if (!isVersion(record["v"])) throw Bad("not a record of this version")
                if ("next" in record && "id" !in record) {
                    nextId = maxOf(nextId, int(record.getValue("next")))
                    continue
                }
                val job = jobOf(record)
                jobs[job.id] = job
                nextId = maxOf(nextId, job.id + 1)
            } catch (e: Exception) {  // Bad, kotlinx's SerializationException (an IllegalArgumentException), a decoding's
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
        ))

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
         * keeps (its kind JobCommands.kindOf's: the line keeps none), never a run of its own. [IllegalArgumentException]
         * for one that isn't one.
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
            val songId = maybe(record["song_id"])?.let { int(it).toLong() }
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
            val spec = JobSpec(title = title, key = key,
                               kind = JobCommands.kindOf(key, commands.map { it.args }, stages.map { it.name }),
                               stages = emptyList(), display = display, songId = songId, commands = commands,
                               fetching = fetching, note = note)
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
            }
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

        /** A whole number, never true or false, nor one JSON writes as a float. */
        private fun int(value: JsonElement): Int {
            val primitive = value as? JsonPrimitive
            if (primitive == null || primitive.isString || primitive is JsonNull || !WHOLE.matches(primitive.content)) {
                throw Bad("not a whole number: $value")
            }
            return primitive.content.toIntOrNull() ?: throw Bad("too large: $value")
        }

        private fun number(value: JsonElement): Double {
            val primitive = value as? JsonPrimitive
            if (primitive == null || primitive.isString || primitive is JsonNull ||
                primitive.content == "true" || primitive.content == "false") {
                throw Bad("not a number: $value")
            }
            return primitive.content.toDoubleOrNull() ?: throw Bad("not a number: $value")
        }

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

        /** `datetime.fromisoformat` of a text (a naive time is UTC, as stamps.py's): the date (`YYYY-MM-DD` or
         * `YYYYMMDD`), then, after any one character, the time (`HH[:MM[:SS[.f…]]]` or `HHMM[SS[.f…]]`, a fraction's
         * digits past six cut, `24:00:00` the next day's start) and its offset (`Z`, `±HH[:MM[:SS[.ffffff]]]`,
         * `±HHMM[SS]`). ISO weeks are not read. */
        fun time(value: JsonElement): Instant = parseIso(str(value))

        internal fun parseIso(text: String): Instant {
            val p = IsoReader(text)
            val date = p.date()
            if (p.done()) return LocalDateTime.of(date, java.time.LocalTime.MIDNIGHT).toInstant(ZoneOffset.UTC)
            p.skipOne()
            val (seconds, nanos) = p.clock()
            val offset = p.offset()
            if (!p.done()) throw Bad("not an ISO time: $text")
            val local = date.atStartOfDay().plusSeconds(seconds).plusNanos(nanos.toLong())
            return local.toInstant(ZoneOffset.UTC).minusNanos(offset)
        }

        private class IsoReader(val text: String) {
            var i = 0
            fun done() = i >= text.length
            fun skipOne() { i += Character.charCount(text.codePointAt(i)) }

            private fun digits(n: Int): Int {
                if (i + n > text.length) throw Bad("not an ISO time: $text")
                var v = 0
                for (k in 0 until n) {
                    val c = text[i + k]
                    if (c !in '0'..'9') throw Bad("not an ISO time: $text")
                    v = v * 10 + (c - '0')
                }
                i += n
                return v
            }

            private fun at(c: Char) = i < text.length && text[i] == c

            fun date(): LocalDate {
                val year = digits(4)
                val extended = at('-')
                if (extended) i++
                val month = digits(2)
                if (extended) { if (!at('-')) throw Bad("not an ISO date: $text"); i++ }
                val day = digits(2)
                return try {
                    LocalDate.of(year, month, day)
                } catch (e: java.time.DateTimeException) {
                    throw Bad("not a date: $text")
                }
            }

            private fun isTimeEnd() = done() || text[i] == '+' || text[i] == '-' || text[i] == 'Z'

            /** Seconds into the day, and nanoseconds. */
            fun clock(): Pair<Long, Int> {
                val hour = digits(2)
                var minute = 0
                var second = 0
                var nanos = 0
                var extended: Boolean? = null
                if (!isTimeEnd()) {
                    extended = at(':')
                    if (extended) i++
                    minute = digits(2)
                    if (!isTimeEnd()) {
                        if (extended) { if (!at(':')) throw Bad("not an ISO time: $text"); i++ }
                        second = digits(2)
                        if (!isTimeEnd()) {
                            if (!at('.') && !at(',')) throw Bad("not an ISO time: $text")
                            i++
                            val start = i
                            while (i < text.length && text[i] in '0'..'9') i++
                            if (i == start) throw Bad("not an ISO time: $text")
                            val fraction = text.substring(start, i).take(6).padEnd(6, '0')
                            nanos = fraction.toInt() * 1000
                        }
                    }
                }
                if (hour == 24) {
                    if (minute != 0 || second != 0 || nanos != 0) throw Bad("not an ISO time: $text")
                    return 86_400L to 0
                }
                if (hour > 23 || minute > 59 || second > 59) throw Bad("not an ISO time: $text")
                return (hour * 3600L + minute * 60L + second) to nanos
            }

            /** The offset, in nanoseconds east of UTC (0 for none and for Z). */
            fun offset(): Long {
                if (done()) return 0
                if (at('Z')) { i++; return 0 }
                val sign = if (at('-')) -1 else 1
                i++
                val hours = digits(2)
                var minutes = 0
                var seconds = 0
                var micros = 0
                if (!done()) {
                    val extended = at(':')
                    if (extended) i++
                    minutes = digits(2)
                    if (!done()) {
                        if (extended) { if (!at(':')) throw Bad("not an offset: $text"); i++ }
                        seconds = digits(2)
                        if (!done()) {
                            if (!at('.')) throw Bad("not an offset: $text")
                            i++
                            micros = digits(6)
                        }
                    }
                }
                if (hours > 23 || minutes > 59 || seconds > 59) throw Bad("not an offset: $text")
                return sign * ((hours * 3600L + minutes * 60L + seconds) * 1_000_000_000L + micros * 1000L)
            }
        }
    }
}
