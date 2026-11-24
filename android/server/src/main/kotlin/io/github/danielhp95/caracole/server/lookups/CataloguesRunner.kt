package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.catalogues.CatalogueError
import io.github.danielhp95.caracole.core.catalogues.CatalogueSource
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.Choice
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.catalogues.Names
import io.github.danielhp95.caracole.core.catalogues.choose
import io.github.danielhp95.caracole.core.catalogues.date
import io.github.danielhp95.caracole.core.catalogues.download
import io.github.danielhp95.caracole.core.catalogues.words
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.isSqliteError
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TransferError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Duration
import java.time.Instant

/**
 * `caracole catalogues [--metered-ok]` (the phone's own command, PhoneKinds' catalogues kind): every site's index the
 * laptop publishes in GitHub's release (core.catalogues), this app's schema's newest file downloaded and merged, on
 * the queue's one worker, so never beside a lookup's write or any other job's. Its one stage, `catalogues`, says:
 *
 * 1. a time GitHub said to ask again after (kv [Catalogues.NOT_BEFORE]) still to come: [Limited]'s words, with no
 *    request (a record that isn't a time is none);
 * 2. the release listed ([CatalogueSource.list]) and its file chosen ([choose]): none of this schema, the reason in
 *    [words] (a newer schema, an older one, none at all); the one imported last (kv [Catalogues.IMPORTED]), "Up to
 *    date: the catalogues of DATE" ([UP_TO_DATE]), done, nothing downloaded;
 * 3. on a metered network ([metered]) with no `--metered-ok`: "52 MB to download: waiting for your go-ahead to use
 *    mobile data" (the kind's second way to end, a wait: nothing starts it again on Wi-Fi by itself), nothing
 *    downloaded, the file's name and size kept in kv [ASKING] (`{"name", "bytes"}`) for the app's question; asked
 *    again with `--metered-ok` (the go-ahead, a job of its own key, [GO]), downloaded whatever the network;
 * 4. less room in `stateDir` than [Catalogues.ROOM_FACTOR] times the file ([free]): "The import needs about 1.2 GB
 *    free; the phone has 700 MB.", nothing downloaded;
 * 5. the file downloaded ([download]: unpacked and checked) into `stateDir/cache/catalogues/`, saying "Downloading ·
 *    31 of 52 MB" as it goes;
 * 6. in one write, merged (IndexTransfer.merge, `notAfter` the clock and a day, as a sync's merge: no record dated
 *    later is newer than the phone's), kv [Catalogues.IMPORTED] its name once the merge took it, and "Catalogues of
 *    DATE", with a sentence for the sites the file holds that this version doesn't know (caracole_export's `sites`
 *    against [IndexTransfer.SITES], [unknown]); once the merge has begun, whatever came of it, the WAL checkpointed
 *    and the search's answers forgotten ([forget]).
 *
 * Whatever came of it, the folder `stateDir/cache/catalogues/` is emptied, a file a killed job left among it, and
 * [sweep] empties it as the phone starts. A [Limited] anywhere keeps its time in kv [Catalogues.NOT_BEFORE]. Failed, its words are "Not imported: WHY" (its
 * kind's), the command's exit 1.
 *
 * Each run asks GitHub with caracole's user agent as the phone's settings say it then (PhoneConfig.read: the
 * computer's once a sync brought it), through [source] made of that client (GitHub's API, the owner's choice);
 * [clock], [metered], [free] and [forget] are the app's (a test's).
 */
class CataloguesRunner(
    val parts: PhoneParts,
    val source: (Http) -> CatalogueSource = { CatalogueSource.Api(it) },
    private val clock: () -> Instant = Instant::now,
    private val metered: () -> Boolean = { false },
    private val forget: () -> Unit = {},
    private val free: (File) -> Long = File::getUsableSpace,
) : CommandRunner {
    /** The file a job killed in its middle left in `stateDir/cache/catalogues/` (up to the whole unpacked index)
     * deleted: called as the phone starts, while no job runs. */
    fun sweep() = empty(File(parts.stateDir, CACHE))

    /** The job the app queues (Settings, the first start): one at a time, a request while one waits or runs answered
     * by that one; with [meteredOk], the owner's go-ahead to download on a metered network, a job of its own key
     * ([GO]), so that a plain job waiting never answers it. */
    fun spec(meteredOk: Boolean): JobSpec {
        val kind = PhoneKinds.CATALOGUES
        val args = if (meteredOk) listOf(COMMAND, METERED_OK) else listOf(COMMAND)
        return JobSpec(title = kind.title, key = kind.key + (if (meteredOk) GO else ""), kind = kind.kind,
                       stages = listOf(kind.stage), display = kind.display, join = false,
                       run = { context -> run(args, context) })
    }

    override suspend fun run(args: List<String>, context: JobContext) {
        val meteredOk = when (args) {
            listOf(COMMAND) -> false
            listOf(COMMAND, METERED_OK) -> true
            else -> throw CommandExit(2, "Usage: caracole catalogues [$METERED_OK]")
        }
        val cache = File(parts.stateDir, CACHE)
        try {
            withContext(Dispatchers.IO) { import(meteredOk, cache, context) }
        } catch (e: Limited) {
            quietly { parts.database.write { db -> db.kvSet(Catalogues.NOT_BEFORE, Stamps.of(e.until)) } }
            fail(context, e.message.orEmpty())
        } catch (e: CatalogueError) {
            fail(context, e.message.orEmpty())
        } finally {
            empty(cache)
        }
    }

    private suspend fun import(meteredOk: Boolean, cache: File, context: JobContext) {
        val kind = PhoneKinds.CATALOGUES
        fun doing(words: String) = context.stage(STAGE, "running", PhoneKinds.fill(kind.running, "doing" to words))
        context.stage(STAGE, "running")
        val (until, imported, agent) = parts.database.read { db ->
            Triple(notBefore(db), db.kvGet(Catalogues.IMPORTED), PhoneConfig.read(db).userAgent)
        }
        val at = clock()
        // GitHub's reset is within the hour: one further on than MOST_AHEAD is a clock that was wrong, passed over.
        if (until != null && until.isAfter(at) && !until.isAfter(at.plus(MOST_AHEAD))) throw Limited(until)
        empty(cache)  // what a killed job left
        val http = Http(userAgent = agent)
        val source = source(http)
        doing(LISTING)
        val take = when (val choice = choose(source.list(), Database.SCHEMA_VERSION, imported)) {
            is Choice.Take -> choice
            is Choice.UpToDate -> {
                parts.database.write { db -> db.kvDelete(ASKING) }
                val day = Names.read(choice.name)?.let(::date) ?: choice.name
                context.stage(STAGE, "done", PhoneKinds.fill(UP_TO_DATE, "date" to day))
                return
            }
            else -> throw CatalogueError(words(choice)!!)
        }
        val bytes = take.file.bytes
        if (metered() && !meteredOk) {
            parts.database.write { db ->
                db.kvSetJson(ASKING, JsonObject(linkedMapOf("name" to JsonPrimitive(take.file.name),
                                                            "bytes" to JsonPrimitive(bytes))))
            }
            context.stage(STAGE, "done", PhoneKinds.fill(kind.otherwise!!, "size" to size(bytes)))
            return
        }
        val room = free(parts.stateDir)
        val needs = Catalogues.ROOM_FACTOR.toLong() * bytes
        if (room < needs) {
            throw CatalogueError(PhoneKinds.fill(NO_ROOM, "needs" to size(needs), "has" to size(room)))
        }
        if (!cache.isDirectory && !cache.mkdirs()) throw CatalogueError("The phone's storage failed: no ${cache.name} folder.")
        val to = File(cache, take.file.name.removeSuffix(".gz"))
        var said = ""
        doing(downloading(0, bytes))
        val fetched = download(http, take.file, to, source.redirects) { got ->
            val now = downloading(got, bytes)
            if (now != said) {
                said = now
                doing(now)
            }
        }
        doing(IMPORTING)
        val unknown = try {
            parts.database.write { db ->
                IndexTransfer.merge(db, fetched.file, Stamps.of(clock()), notAfter = notAfter())
                db.kvSet(Catalogues.IMPORTED, take.file.name)
                db.kvDelete(ASKING)
                sitesOf(db, fetched.file).filter { it !in IndexTransfer.SITES }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: TransferError) {
            throw CatalogueError(Py.strip(e.message.orEmpty().replace(fetched.file.path, THE_FILE)).let(::capital))
        } catch (e: Exception) {
            if (!e.isSqliteError()) throw e
            throw CatalogueError("The phone's database failed: ${e.message ?: e::class.simpleName}.", e)
        } finally {
            // The merge began: whatever it took, the WAL it grew given back and the search's answers forgotten.
            quietly { parts.database.checkpoint() }
            forget()
        }
        context.stage(STAGE, "done", PhoneKinds.fill(kind.done, "date" to date(take.named)) +
            (if (unknown.isEmpty()) "" else "." + unknown(unknown)))
    }

    /** The latest time a merged record may say it was read at (IndexTransfer.merge's `notAfter`): the clock and a day
     * more, for the laptop's clock ahead of the phone's, as a sync's merge (SyncEngine). */
    private fun notAfter(): Long = Stamps.micros(clock().plus(Duration.ofDays(1)))

    /** kv [Catalogues.NOT_BEFORE] as a time; none for no record, or one that isn't a time Stamps reads. */
    private fun notBefore(db: Db): Instant? = try {
        db.kvGet(Catalogues.NOT_BEFORE)?.let(Stamps::parse)?.let(Stamps::instant)
    } catch (e: ArithmeticException) {
        null  // a time out of range
    }

    /** [block] run, a failure of it passed over, but a cancellation's. */
    private inline fun quietly(block: () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // nothing more to do: what it was for is a nicety
        }
    }

    /** The job's stage failed with the kind's words for [why], and the command with them. */
    private fun fail(context: JobContext, why: String): Nothing {
        val line = PhoneKinds.fill(PhoneKinds.CATALOGUES.failed, "why" to why)
        context.stage(STAGE, "failed", line)
        throw CommandExit(1, line)
    }

    /** The names caracole_export's `sites` lists in [file] (a JSON array of texts), none where it can't be read. */
    private fun sitesOf(db: Db, file: File): List<String> = try {
        db.attach(file, READ_AS)
        try {
            val text = db.one("SELECT value FROM $READ_AS.${IndexTransfer.META} WHERE key = 'sites'") { it.text(0) }
            (text?.let(PyJson::loads) as? JsonArray).orEmpty()
                .mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
        } finally {
            db.detach(READ_AS)
        }
    } catch (e: Exception) {
        if (e is CancellationException) throw e
        emptyList()  // the merge read the file whole: what it lists of no use to it is said where it can be read
    }

    /** Every file in [cache] deleted (the folder kept). */
    private fun empty(cache: File) {
        cache.listFiles()?.forEach { it.deleteRecursively() }
    }

    /** [text] with its first letter, an ASCII one, a capital. */
    private fun capital(text: String): String =
        if (text.isNotEmpty() && text[0] in 'a'..'z') (text[0] - 32) + text.substring(1) else text

    companion object {
        const val COMMAND = "catalogues"
        const val METERED_OK = "--metered-ok"

        /** The furthest ahead of the clock a kept [Catalogues.NOT_BEFORE] is kept to; past it, it is passed over. */
        val MOST_AHEAD: Duration = Duration.ofHours(2)

        /** kv: the file a metered network left waiting for the owner's go-ahead, `{"name": …, "bytes": …}`. */
        const val ASKING = "catalogues:asking"

        /** Where a file is downloaded to, under `stateDir`, and gone after. */
        const val CACHE = "cache/catalogues"

        private const val STAGE = "catalogues"
        private const val READ_AS = "catalogue"
        private const val THE_FILE = "the file"
        private const val LISTING = "Asking GitHub for the catalogues…"
        private const val IMPORTING = "Importing the catalogues…"

        /** The go-ahead's key after the kind's (`catalogues:go`). */
        const val GO = "go"

        /** The line of a release whose file is the one imported last, its {date}. */
        const val UP_TO_DATE = "Up to date: the catalogues of {date}"

        /** Why not, when the phone has less room than the import needs: {needs} and {has}. */
        const val NO_ROOM = "The import needs about {needs} free; the phone has {has}."

        /** The sentence after the done line for the sites a file holds that this version doesn't know ("" for none):
         * "It also holds ireal's, which this version doesn't read. Update the app to search it.", each by its name in
         * the file, several joined with ", " and " and ". */
        fun unknown(sites: List<String>): String {
            if (sites.isEmpty()) return ""
            val named = sites.map { "$it's" }
            val list = if (named.size == 1) named[0] else named.dropLast(1).joinToString(", ") + " and " + named.last()
            return " It also holds $list, which this version doesn't read. Update the app to search " +
                (if (sites.size == 1) "it." else "them.")
        }

        /** "Downloading · 31 of 52 MB": [got] of [total] bytes, in the unit and the precision [size] says [total] in. */
        fun downloading(got: Long, total: Long): String {
            val so = when {
                total >= GB -> tenths(got, 100_000_000)
                total >= WHOLE_MB -> ((got + 500_000) / 1_000_000).toString()
                else -> tenths(got, 100_000)
            }
            return "Downloading · $so of ${size(total)}"
        }

        /** A size as the pages say one (sync-words.js's `size`): 0.4 MB, 3.4 MB, 207 MB, 1.2 GB, a megabyte a million
         * bytes, 0.1 MB at least; ASCII digits, no locale's. */
        fun size(bytes: Long): String {
            val b = maxOf(bytes, 0)
            return when {
                b >= GB -> tenths(b, 100_000_000) + " GB"
                b >= WHOLE_MB -> ((b + 500_000) / 1_000_000).toString() + " MB"
                else -> tenths(maxOf(b, 100_000), 100_000) + " MB"
            }
        }

        /** [bytes] in tenths of [tenth] bytes, rounded half up, as "1.2". */
        private fun tenths(bytes: Long, tenth: Long): String {
            val n = (bytes + tenth / 2) / tenth
            return "${n / 10}.${n % 10}"
        }

        /** The sizes from which [size] says gigabytes, and whole megabytes (sync-words.js's 999.5 and 9.95 MB). */
        private const val GB = 999_500_000L
        private const val WHOLE_MB = 9_950_000L
    }
}
