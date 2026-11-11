package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.Filed
import io.github.danielhp95.caracole.core.inbox.Inbox
import io.github.danielhp95.caracole.core.inbox.InboxFolder
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.QueueFull
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * `caracole inbox -- NAME` (the phone's own, PhoneKinds' inbox kind): the file shared to the app that waits as NAME in
 * `stateDir/inbox/` ([InboxShare.folder]) filed as inbox.py files an `_inbox/` entry (core.inbox's [Inbox.file],
 * inside one Database.write), its stage `file` saying how it went in PhoneKinds' words: "Filed as guitar-1.gp5 of
 * Oasis - Wonderwall" (kept, a lost copy put back, or a copy the library holds already), "Waiting for a song that
 * fits: NAME" (no song fits: it stays, and is tried again after each sync and lookup), "Not filed: why" (a failure:
 * it stays, the failure remembered, [InboxFolder.failed], so that it is tried again after a sync or a day on; or the
 * bytes of a copy caracole keeps whose place holds other bytes now, [Inbox.changed]: it stays, as inbox.py leaves it
 * in `_inbox/`, nothing replaced). A song a file was kept for has its pages made again ([PhoneParts.pages]), and the
 * job says its song. [clock]: the time the file is filed (a test's).
 */
class InboxRunner(val parts: PhoneParts, private val clock: () -> Instant = Instant::now) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val kind = PhoneKinds.INBOX
        val stage = kind.stage.first
        val name = nameOf(args)
        val folder = InboxShare.folder(parts)
        context.stage(stage, "running", PhoneKinds.fill(kind.running, "name" to name))
        fun failed(why: String): Nothing {
            val line = PhoneKinds.fill(kind.failed, "why" to why)
            context.stage(stage, "failed", line)
            throw CommandExit(1, line)
        }
        val data = folder.read(name) ?: failed("$name isn't waiting to be filed any more")
        if (!Inbox.keeps(name)) {
            folder.drop(name)
            failed(InboxShare.notKept(name))
        }
        val now = clock().truncatedTo(ChronoUnit.SECONDS).toString()
        fun failedFiling(why: String): Nothing {
            runCatching { folder.failed(name, clock()) }  // remembered, so the next jobs don't try it again at once
            failed(why)
        }
        val said = try {
            parts.database.write { db ->
                val filed = Inbox.file(db, parts.store, name, data, now)
                val said = said(db, filed, name, data)
                val songs = said.songs
                if (songs.isNotEmpty()) {
                    // The file is kept whatever its pages come to: a page not made is said, never the filing's failure.
                    try {
                        val made = parts.pages.render(db, songs.map { it.id }, null)
                        for (why in made.failed.values) context.say("pages not made: $why")
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        context.say("pages not made: ${e.message ?: e::class.simpleName}")
                    }
                }
                filed to said
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: SharedFolder) {
            failedFiling(e.message.orEmpty())
        } catch (e: Exception) {  // a write that failed (IOException), or what inbox.py raises too: said, the file kept
            failedFiling(e.message ?: e::class.simpleName.orEmpty())
        }
        val (filed, words) = said
        if (filed != Filed.Unmatched) folder.drop(name)
        words.notFiled?.let { failed(it) }
        words.songs.firstOrNull()?.let { context.song(it.id, it.display) }
        context.stage(stage, "done", words.line)
    }

    /** What filing came to in the job's words: its [line], the songs whose pages are owed (a file kept or put back),
     * and why it was [notFiled] when its copy's place holds other bytes now. */
    private class Said(val line: String, val songs: List<SongRow> = emptyList(), val notFiled: String? = null)

    private fun said(db: Db, filed: Filed, name: String, data: ByteArray): Said {
        val kind = PhoneKinds.INBOX
        fun done(kept: String, song: SongRow) = PhoneKinds.fill(kind.done, "name" to kept, "song" to song.display)
        return when (filed) {
            is Filed.Kept -> {
                val song = song(db, filed.songId)
                Said(done(filed.name, song), listOf(song))
            }
            is Filed.PutBack -> {
                val put = filed.paths.map { path ->
                    db.one("SELECT song_id, name FROM files WHERE path = ?", path) { it.long(0)!! to it.text(1)!! }
                        ?: throw IllegalStateException("$path put back and not kept")
                }
                val songs = put.map { song(db, it.first) }
                Said(done(put.first().second, songs.first()), songs.distinctBy { it.id })
            }
            Filed.Duplicate -> {
                val copy = Inbox.held(db, parts.store, name, data)
                Said(copy?.let { done(it.name, song(db, it.songId)) }
                         ?: PhoneKinds.fill(kind.done, "name" to name, "song" to "its song"))
            }
            Filed.Unmatched -> {
                val waits = PhoneKinds.fill(kind.otherwise!!, "name" to name)
                val changed = Inbox.changed(db, parts.store, name, data)
                Said(waits, notFiled = changed?.let {
                    "$name is ${it.name} of ${song(db, it.songId).display}, whose place holds other bytes now, " +
                        "and nothing is replaced"
                })
            }
        }
    }

    private fun song(db: Db, id: Long): SongRow = Songs.byId(db, id) ?: throw IllegalStateException("no song $id")

    /** The one name after `--`: the file that waits. */
    private fun nameOf(args: List<String>): String {
        val at = args.indexOf("--")
        val words = if (at >= 0) args.subList(at + 1, args.size) else args.drop(1)
        if (words.size != 1 || words[0].isEmpty()) throw CommandExit(2, "Usage: caracole inbox -- NAME")
        return words[0]
    }
}

/**
 * The files shared to the app that wait for a song, tried again after each sync and lookup, for 30 days, as
 * `_inbox/` keeps a file until a song fits: the phone calls [afterJob] after every job (Assembly). After a job that
 * ran of a kind that may bring a song ([AFTER]: a sync, a lookup, an add), and after the first job of the process
 * whatever its kind (a share whose job the process's end cut short is tried again then: Try again can't repeat it),
 * each file that fits now ([Inbox.fits]: a song fits it, or it is a copy caracole keeps) is queued to be filed
 * ([InboxShare.spec]); one that still fits no song waits, saying nothing. A file whose filing failed
 * ([InboxFolder.failedAt]) is tried again only after a sync, or once [AFTER_FAILURE] has passed, never after every
 * lookup. Files that waited [InboxFolder.DAYS] days are dropped after any job. [clock]: a test's.
 */
class InboxRetry(val parts: PhoneParts, private val clock: () -> Instant = Instant::now) {
    private val started = AtomicBoolean(false)

    fun afterJob(job: Job) {
        val folder = InboxShare.folder(parts)
        val now = clock()
        folder.sweep(now)
        val first = started.compareAndSet(false, true)
        val ran = job.startedAt != null
        if (!first && (!ran || job.spec.kind !in AFTER)) return
        val synced = ran && job.spec.kind == "sync"
        val due = folder.waiting().filter { name ->
            val failed = folder.failedAt(name)
            failed == null || synced || !failed.isAfter(now.minus(AFTER_FAILURE))
        }
        if (due.isEmpty()) return
        val fit = try {
            parts.database.read { db ->
                val among = Inbox.Candidates.of(db)  // every song's names made once, for every file
                due.filter { name -> folder.read(name)?.let { Inbox.fits(db, parts.store, name, it, among) } == true }
            }
        } catch (e: Exception) {
            return  // the database can't be read now: the next job tries again
        }
        for (name in fit) {
            try {
                parts.queue.submit(InboxShare.spec(parts, name, clock))
            } catch (_: QueueFull) {
                return  // the queue is full: the next job's end tries again
            }
        }
    }

    companion object {
        /** The kinds of job after which the waiting files are tried again: a sync, a lookup, an add. */
        val AFTER: Set<String> = setOf("sync", "song", "add")

        /** How long a file whose filing failed waits before a lookup or an add tries it again (a sync tries it). */
        val AFTER_FAILURE: Duration = Duration.ofDays(1)
    }
}

/**
 * A file shared to the app (ShareActivity's, SEND or SEND_MULTIPLE of a stream), staged in `stateDir/inbox/` under
 * the name it was shared by ([InboxFolder.nameFor]) and its filing queued as the inbox runner's job (PhoneKinds' inbox
 * kind, keyed by that name: a job of it that waits or runs is its answer).
 */
object InboxShare {
    /** The most a shared file may hold: a Guitar Pro file is a few kilobytes, a score's PDF a few megabytes. */
    const val MAX_BYTES: Int = 64 shl 20

    /** What a share came to: the [name] it waits under and its [job]; or no job, and [said], why. */
    data class Shared(val name: String, val job: Job?, val said: String?)

    /** Where the files shared to the app wait. */
    fun folder(parts: PhoneParts): InboxFolder = InboxFolder(File(parts.stateDir, "inbox"))

    /** The words for a file of an extension inbox.py files nothing of. */
    fun notKept(name: String): String = "caracole keeps Guitar Pro files and scores, and $name is neither"

    /**
     * [data], shared as [shared] (its display name) of [type] (its MIME type), staged and its filing queued, at
     * [clock]'s time (a test's). A name that has no extension inbox.py files ([Inbox.keeps], once its bytes and type
     * named one) is never staged, nor one past [MAX_BYTES]; a full queue leaves it staged, to be tried after the next
     * sync or lookup.
     */
    fun share(parts: PhoneParts, shared: String?, type: String?, data: ByteArray,
              clock: () -> Instant = Instant::now): Shared {
        val kind = PhoneKinds.INBOX
        val name = InboxFolder.nameFor(shared, type, data)
        if (!Inbox.keeps(name)) return Shared(name, null, PhoneKinds.fill(kind.failed, "why" to notKept(name)))
        if (data.size > MAX_BYTES) {
            return Shared(name, null, PhoneKinds.fill(kind.failed, "why" to "$name is over ${MAX_BYTES shr 20} MiB"))
        }
        val staged = folder(parts).stage(name, data, clock())
        return try {
            Shared(staged, parts.queue.submit(spec(parts, staged, clock)).first, null)
        } catch (_: QueueFull) {
            Shared(staged, null, PhoneKinds.fill(kind.otherwise!!, "name" to staged) +
                " (the queue is full: it is tried again after the next sync or lookup)")
        }
    }

    /** The job that files the file waiting as [name]: the inbox runner's, as PhoneKinds' inbox kind words it, filed
     * at [clock]'s time (a test's). */
    fun spec(parts: PhoneParts, name: String, clock: () -> Instant = Instant::now): JobSpec {
        val kind = PhoneKinds.INBOX
        return JobSpec(
            title = PhoneKinds.fill(kind.title, "name" to name), key = kind.key + name, kind = kind.kind,
            stages = listOf(kind.stage), display = PhoneKinds.fill(kind.display, "name" to name),
            run = { context -> InboxRunner(parts, clock).run(listOf("inbox", "--", name), context) },
        )
    }
}
