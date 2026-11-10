package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.backup.Backup
import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.core.backup.OwnRecords
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.viewer.render.RenderNames
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * `caracole backup` (the phone's own command, PhoneKinds' backup and restore kinds), run on the queue's one worker,
 * so never beside a lookup's write or any other job's:
 *
 * - `backup --label LABEL`: a backup of the library made now (core.backup's [Backups.make], in one write), its stage
 *   `backup` saying "Backed up (LABEL)", or why not ("Not backed up: …", no room among the whys);
 * - `backup --restore NAME`: the backup of that name in `stateDir/backups/` restored ([Backups.restore]: the tables
 *   and the kept files put back, this side's own records kept as they are, [OwnRecords]), and in the same savepoint
 *   the phone's pages owed again (every song's `render:<id>:phone` and `phone:render-build` forgotten, so the render
 *   job makes each again: the files on disk are no longer those the restored records name); its stage `restore`
 *   saying "Restored the library of DATE", or why not. Its outcome is what it did to the files.
 *
 * [backup] and [restore] are the jobs the app queues (BackupsActivity, BackupWorker): jobs of the phone's own, whose
 * lines are PhoneKinds' words (JobViews), each run by this runner as its command line says; Try again runs one again
 * while the app runs (one read back from the history after a restart has nothing to run, as the render job's).
 */
class BackupRunner(val parts: PhoneParts, private val clock: () -> Instant = { Instant.now() },
                   private val zone: ZoneId = ZoneId.systemDefault()) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        when {
            args.size == 3 && args[1] == LABEL -> make(args[2], context)
            args.size == 3 && args[1] == RESTORE -> restore(args[2], context)
            else -> throw CommandExit(2, "caracole backup takes $LABEL LABEL or $RESTORE NAME")
        }
    }

    /** The job of a backup made now, labelled [label] (Backups.LABELS): a job of the phone's own, PhoneKinds' backup
     * kind, its run this runner's `backup --label LABEL`. */
    fun backup(label: String): JobSpec {
        val kind = PhoneKinds.BACKUP
        return JobSpec(title = kind.title, key = kind.key + label, kind = kind.kind, stages = listOf(kind.stage),
                       display = PhoneKinds.fill(kind.display, "label" to label),
                       run = { context -> run(listOf(COMMAND, LABEL, label), context) })
    }

    /** The job of [backup] restored: PhoneKinds' restore kind, its run `backup --restore NAME`. */
    fun restore(backup: Backup): JobSpec = restore(backup.file.name, date(backup.at, zone))

    /** The job of the backup named [name] restored, said as made at [date]. */
    fun restore(name: String, date: String): JobSpec {
        val kind = PhoneKinds.RESTORE
        return JobSpec(title = PhoneKinds.fill(kind.title, "date" to date), key = kind.key + name, kind = kind.kind,
                       stages = listOf(kind.stage), display = PhoneKinds.fill(kind.display, "date" to date),
                       run = { context -> run(listOf(COMMAND, RESTORE, name), context) })
    }

    private fun make(label: String, context: JobContext) {
        val kind = PhoneKinds.BACKUP
        val stage = kind.stage.first
        context.stage(stage, "running")
        val made = try {
            parts.database.writeBlocking { db -> Backups.make(db, parts.store, parts.stateDir, clock(), label) }
        } catch (e: Exception) {
            fail(context, kind, said(e))
        } ?: fail(context, kind, NO_ROOM)
        context.say(made.name)
        context.stage(stage, "done", PhoneKinds.fill(kind.done, "label" to label))
    }

    private fun restore(name: String, context: JobContext) {
        val kind = PhoneKinds.RESTORE
        val stage = kind.stage.first
        context.stage(stage, "running")
        val backup = name.takeIf { '/' !in it && '\\' !in it && !it.startsWith(".") }
            ?.let { Backups.of(File(File(parts.stateDir, Backups.FOLDER), it)) }
            ?: fail(context, kind, "there is no backup $name")
        val restored = try {
            Backups.restore(parts.database, parts.store, backup.file, keep = OwnRecords::document) { db, own ->
                OwnRecords.putBack(db, own)
                owePages(db)
            }
        } catch (e: Exception) {
            fail(context, kind, said(e))
        }
        for (path in restored.missing) context.say("not kept by the backup, and gone: $path")
        context.outcome(JsonObject(linkedMapOf(
            "written" to JsonPrimitive(restored.written), "removed" to JsonPrimitive(restored.removed),
            "missing" to JsonArray(restored.missing.map { JsonPrimitive(it) }),
        )))
        context.stage(stage, "done", PhoneKinds.fill(kind.done, "date" to date(backup.at, zone)))
    }

    /** The job's stage failed with [kind]'s words for [why], and the command with them. */
    private fun fail(context: JobContext, kind: PhoneKinds.Kind, why: String): Nothing {
        val line = PhoneKinds.fill(kind.failed, "why" to why)
        context.stage(kind.stage.first, "failed", line)
        throw IllegalStateException(line)
    }

    private fun said(e: Exception): String = e.message?.lineSequence()?.map(Py::strip)?.firstOrNull { it.isNotEmpty() }
        ?: e::class.simpleName ?: "it stopped"

    companion object {
        const val COMMAND = "backup"
        const val LABEL = "--label"
        const val RESTORE = "--restore"

        /** Why a backup wasn't made when there is no room. */
        const val NO_ROOM = "there isn't room for it on the phone"

        private val DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm", Locale.ROOT)

        /** When a backup was made, as its restore's words say it: the phone's time, to the minute. */
        fun date(at: Instant, zone: ZoneId = ZoneId.systemDefault()): String = DATE.format(at.atZone(zone))

        /** The phone's pages owed again, every song's: its record of each forgotten, and the build's. */
        fun owePages(db: Db) {
            db.execute("DELETE FROM kv WHERE key = ? OR key GLOB ?", RenderNames.BUILD_KEY, "render:[0-9]*${RenderNames.PHONE_KV}")
        }
    }
}
