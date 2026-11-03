package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.internal.client.Give
import io.github.danielhp95.caracole.core.sync.internal.client.Kept
import io.github.danielhp95.caracole.core.sync.internal.client.Stamps
import io.github.danielhp95.caracole.mirror.SyncError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant

enum class Side { HERE, THERE, SKIP }

/** A comparison with the computer, kept by [id] for 10 minutes. */
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: Boolean,
                      val differences: List<Difference>, val hash: String)

data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>,
                       val agreed: Int, val indexed: List<String>)

/** A sync that couldn't go on, or was refused before it began: why, as one sentence ([message]), and what it had done
 * by then ([outcome]; null when it changed nothing yet). */
class SyncFailed(message: String, val outcome: SyncOutcome? = null, cause: Throwable? = null) : Exception(message, cause)

/**
 * The phone's sync with the computer, which the phone starts (the plan's §5.3): it takes what it takes from the
 * computer's peer routes ([client]), then pushes what the computer takes, so the phone serves nothing to the network.
 *
 * [compare] reads the computer's state (with what it agreed with this phone, the phone's id asking), the phone's own
 * units and base, and compares them three ways (Compare): the differences, and their hash. The comparison is kept by
 * its id for 10 minutes ([comparison]), for the Sync tab's choices to be applied to.
 *
 * [apply] runs six stages, each told to [stage] as it starts and ends (running, then done, skipped, or failed):
 * 1. **compare**: the computer's state read again and compared again; a hash other than the comparison's refuses
 *    the sync before any change (the two changed since the owner chose).
 * 2. **take**: each difference decided (a choice, else its proposal, else, for a conflict, [prefer]; a conflict with
 *    neither is refused before any change; skip leaves it, "skipped"); then, inside Database.write, a backup of the
 *    phone's database (Take.backupBeforeSync: none, nothing taken) and Take.applyUnits from the computer, each unit
 *    left that changed on either side since the comparison.
 * 3. **give**: the units the computer takes, as documents of the phone's state after its take (`POST /peer/push/new`,
 *    each file it needs, `POST /peer/push`), then the computer's request followed every second, 10 minutes at most,
 *    with no lock held. A unit the phone changed since the comparison is left. A request that fails leaves every
 *    unit given, and the sync stops there: no agreement is recorded on either side.
 * 4. **mirror**: the mirror of the computer's pages brought up to date ([mirrorRefresh]; skipped without one); its
 *    failure stops nothing.
 * 5. **agree**: the computer's state read again; what the two hold alike now recorded as agreed at its clock, inside
 *    Database.write (Compare.recordAgreement), with kv `sync:peer:<computer id>` = {address, name, synced_at}, which
 *    GET /api/sync lists. A unit given that the computer doesn't hold as the phone does is left.
 * 6. **index**: the computer's site indexes whose stamp is newer than kv `sync:index:<computer id>` records, fetched
 *    into `stateDir/cache/` and merged (IndexTransfer.merge) inside Database.write, the kv brought up to date; skipped
 *    when none is newer. A failure there leaves the agreement as it is.
 *
 * Any stage that stops the sync is a [SyncFailed], with the outcome so far; a refusal before any change has none.
 */
class SyncEngine(val database: Database, val store: LibraryStore, val stateDir: File,
                 val client: (String) -> PeerClient, val mirrorRefresh: (suspend (String) -> Unit)?) {
    /** The clock comparisons are kept by and the phone's own stamps are made of; a test's own. */
    internal var clock: () -> Instant = { Instant.now() }

    /** How often give asks the computer how its request goes, and how many times at most (10 minutes). */
    internal var pollEveryMs: Long = POLL_EVERY_MS
    internal var polls: Int = POLLS

    private val kept = Kept<Comparison>(KEPT_SECONDS)

    /** The phone and the computer at [address], compared; kept by its id for 10 minutes. */
    fun compare(address: String): Comparison {
        val compared = compared(client(address), address)
        val comparison = Comparison(Kept.newId(), address, compared.peer, compared.syncedBefore, compared.differences,
                                    compared.hash)
        kept.put(comparison.id, comparison, clock())
        return comparison
    }

    /** The comparison of [id] made within 10 minutes; null for one older, or never made. */
    fun comparison(id: String): Comparison? = kept.get(id, clock())

    suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?,
                      stage: (name: String, state: String, detail: String) -> Unit): SyncOutcome {
        val unsettled = c.differences.count { it.proposal == CONFLICT && choices[it.id] == null && prefer == null }
        if (unsettled > 0) {
            throw SyncFailed("Choose a side for every conflict first: ${plural(unsettled, "conflict")} " +
                             "${if (unsettled == 1) "has" else "have"} none.")
        }
        val client = client(c.address)
        val done = Done()

        // 1. compare
        stage(COMPARE, RUNNING, "Comparing again with ${c.peer.name.ifEmpty { c.address }}…")
        val fresh = step(stage, COMPARE, null) { io { compared(client, c.address) } }
        if (fresh.hash != c.hash) {
            stage(COMPARE, FAILED, CHANGED_SINCE)
            throw SyncFailed(CHANGED_SINCE)
        }
        stage(COMPARE, DONE, if (fresh.differences.isEmpty()) "Nothing differs." else plural(fresh.differences.size, "difference"))
        val me = database.read { Compare.ownId(it) }
        val computer = fresh.peer.server!!

        val toTake = ArrayList<Difference>()
        val toGive = ArrayList<Difference>()
        for (d in fresh.differences) {
            when (choices[d.id] ?: when (d.proposal) { MINE -> Side.HERE; THEIRS -> Side.THERE; else -> prefer }) {
                Side.THERE -> toTake.add(d)
                Side.HERE -> toGive.add(d)
                Side.SKIP, null -> done.left.add(d.id to SKIPPED)
            }
        }

        // 2. take
        if (toTake.isEmpty()) {
            stage(TAKE, SKIPPED_STATE, "Nothing to take here.")
        } else {
            stage(TAKE, RUNNING, "Taking ${plural(toTake.size, "change")}…")
            val now = Stamps.of(clock())
            val wanted = toTake.map { it.id to it.theirs?.digest }
            val expectedHere = toTake.associate { it.id to it.mine?.digest }
            var seen = 0
            val applied = step(stage, TAKE, done) {
                io {
                    database.write { db ->
                        Take.backupBeforeSync(db, stateDir, now)
                            ?: throw SyncFailed("Nothing taken: there's no room for a copy of the phone's database " +
                                                "first.", done.outcome())
                        Take.applyUnits(db, store, client, wanted, expectedHere, now) { _, _ ->
                            seen++
                            stage(TAKE, RUNNING, "Taken $seen of ${toTake.size}…")
                        }
                    }
                }
            }
            done.taken.addAll(applied.taken)
            done.left.addAll(applied.left)
            stage(TAKE, DONE, "Took ${applied.taken.size} of ${toTake.size}" +
                              if (applied.left.isEmpty()) "." else "; left ${applied.left.size}.")
        }

        // 3. give
        val given = if (toGive.isEmpty()) {
            stage(GIVE, SKIPPED_STATE, "Nothing to give there.")
            emptyList()
        } else {
            give(client, stage, done, me, fresh, toGive)
        }

        // 4. mirror
        val refresh = mirrorRefresh
        if (refresh == null) {
            stage(MIRROR, SKIPPED_STATE, "No copy of the computer's pages on this phone.")
        } else {
            stage(MIRROR, RUNNING, "Copying the computer's pages…")
            try {
                refresh(c.address)
                stage(MIRROR, DONE, "")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                stage(MIRROR, FAILED, said(e))
            }
        }

        // 5. agree
        stage(AGREE, RUNNING, "Reading the computer's state again…")
        val after = step(stage, AGREE, done) {
            val after = io { client.state(me) }
            val at = after.now ?: Stamps.of(clock())
            val (mine, agreed) = io {
                database.write { db ->
                    val mine = Units.libraryState(db)
                    val agreed = Compare.recordAgreement(db, computer, mine, after.units, at)
                    db.kvSetJson(PEER_KEY + computer, JsonObject(linkedMapOf(
                        "address" to JsonPrimitive(c.address), "name" to JsonPrimitive(after.name),
                        "synced_at" to JsonPrimitive(at),
                    )))
                    mine to agreed
                }
            }
            done.agreed = agreed
            for (id in given) {
                if (mine[id]?.digest == after.units[id]?.digest) done.given.add(id) else done.left.add(id to LEFT_THERE)
            }
            after
        }
        stage(AGREE, DONE, "The two agree on ${plural(done.agreed, "unit")}.")

        // 6. index
        index(client, stage, done, computer, after.indexes)
        return done.outcome()
    }

    // --- the stages' parts ------------------------------------------------------------------------------------------

    /** What the sync did so far. */
    private class Done {
        val taken = ArrayList<String>()
        val given = ArrayList<String>()
        val left = ArrayList<Pair<String, String>>()
        var agreed = 0
        val indexed = ArrayList<String>()

        fun outcome() = SyncOutcome(taken.toList(), given.toList(), left.toList(), agreed, indexed.toList())
    }

    private class Compared(val peer: PeerState, val differences: List<Difference>, val syncedBefore: Boolean,
                           val hash: String)

    /** The computer's state, the phone's units and base, and what the two hold differently. */
    private fun compared(client: PeerClient, address: String): Compared {
        val me = database.read { Compare.ownId(it) }
        val peer = client.state(me)
        val server = peer.server
            ?: throw PeerError("The caracole at $address has no id to sync by: it may be older than the app.")
        if (server == me) {
            throw PeerError("The caracole at $address is this phone's own (the same id, $me): its database is a copy " +
                            "of the phone's. Give it another: caracole peer new-id.")
        }
        val (mine, base) = database.read { db -> Units.libraryState(db) to Compare.baseOf(db, server) }
        val merged = Compare.mergedBase(base, peer.base)
        val found = Compare.order(Compare.compare(mine, peer.units, merged))
        return Compared(peer, found, merged != null, Compare.comparedHash(found))
    }

    /** The units the computer takes pushed, and its request followed to its end: the ids it was given. */
    private suspend fun give(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, me: String,
                             fresh: Compared, toGive: List<Difference>): List<String> {
        stage(GIVE, RUNNING, "Giving ${plural(toGive.size, "change")}…")
        val (state, documents) = database.read { db ->
            Units.libraryState(db) to toGive.associate { d -> d.id to Units.document(db, store.libraryDir, d.id) }
        }
        val entries = ArrayList<Give.Entry>()
        for (d in toGive) {
            val now = state[d.id]?.digest
            if (now != d.mine?.digest) done.left.add(d.id to CHANGED_HERE)
            else entries.add(Give.Entry(d.id, expected = d.theirs?.digest, digest = now, unit = documents[d.id]))
        }
        if (entries.isEmpty()) {
            stage(GIVE, DONE, "Nothing left to give there.")
            return emptyList()
        }
        val at = fresh.peer.now ?: Stamps.of(clock())
        try {
            val files = Give.files(entries)
            val token = fresh.peer.token
            val job = io {
                val (push, need) = client.pushNew(token, me, files)
                need.forEachIndexed { i, sha ->
                    stage(GIVE, RUNNING, "Sending file ${i + 1} of ${need.size}…")
                    client.pushFile(token, push, sha, Give.read(database, store.libraryDir, sha))
                }
                client.push(token, push, Give.document(me, PHONE_NAME, CARACOLE, at, state, entries))
            }
            stage(GIVE, RUNNING, "The computer takes ${plural(entries.size, "change")}…")
            awaitJob(client, job)
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            val why = said(e)
            for (entry in entries) done.left.add(entry.id to "not given: $why")
            stage(GIVE, FAILED, why)
            throw SyncFailed(why, done.outcome(), e)
        }
        stage(GIVE, DONE, "The computer took what it could of ${plural(entries.size, "change")}.")
        return entries.map { it.id }
    }

    /** The computer's request [id] followed, every [pollEveryMs], until it is over: done, or why it isn't. */
    private suspend fun awaitJob(client: PeerClient, id: Int) {
        repeat(polls) {
            val job = io { client.job(id) }
            when (val state = (job["state"] as? JsonPrimitive)?.takeIf { it.isString }?.content) {
                "queued", "running" -> delay(pollEveryMs)
                "done" -> return
                else -> throw PeerError("The computer's request $id that takes the changes is ${state ?: "unknown"}" +
                                        (Give.failedDetail(job)?.let { ": $it" } ?: "."))
            }
        }
        throw PeerError("The computer didn't finish taking the changes within ${polls * pollEveryMs / 60_000} " +
                        "minutes: sync again once its request is over.")
    }

    /** The computer's newer indexes, merged; a failure is said on the stage and leaves the rest as it is. */
    private suspend fun index(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, computer: String,
                              indexes: Map<String, String>) {
        val had = database.read { db -> Stamps.sites(db.kvGetJson(INDEX_KEY + computer)) }
        val newer = indexes.filter { (site, stamp) -> had[site]?.let { Stamps.newer(stamp, it) } ?: true }.keys.sorted()
        if (newer.isEmpty()) {
            stage(INDEX, SKIPPED_STATE, "No index is newer there.")
            return
        }
        stage(INDEX, RUNNING, "Fetching the computer's newer indexes: ${newer.joinToString(", ")}…")
        val cache = File(stateDir, "cache")
        val file = File(cache, "index-${Kept.newId()}.sqlite")
        try {
            io {
                if (!cache.isDirectory && !cache.mkdirs()) throw PeerError("The phone's storage failed: $cache can't be made.")
                client.index(file, newer)
            }
            stage(INDEX, RUNNING, "Merging ${newer.joinToString(", ")}…")
            io {
                database.write { db ->
                    IndexTransfer.merge(db, file, Stamps.of(clock()), newer)
                    db.kvSetJson(INDEX_KEY + computer, Stamps.json(had + newer.associateWith { indexes.getValue(it) }))
                }
            }
            done.indexed.addAll(newer)
            stage(INDEX, DONE, "Merged ${newer.joinToString(", ")}.")
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            stage(INDEX, FAILED, said(e))
        } catch (e: NotImplementedError) {
            // A merge this build can't do yet (the skeleton's stub of a lane still to land) leaves the sync as done.
            stage(INDEX, FAILED, "The phone can't merge an index yet.")
        } finally {
            file.delete()
        }
    }

    /** [block], a stage's work; any failure said on [name] and a SyncFailed with what [done] holds. */
    private inline fun <T> step(stage: (String, String, String) -> Unit, name: String, done: Done?, block: () -> T): T =
        try {
            block()
        } catch (e: SyncFailed) {
            stage(name, FAILED, e.message ?: "")
            throw e
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            val why = said(e)
            stage(name, FAILED, why)
            throw SyncFailed(why, done?.outcome(), e)
        }

    private suspend fun <T> io(block: suspend () -> T): T = withContext(Dispatchers.IO) { block() }

    private fun said(e: Throwable): String = when (e) {
        is SyncError, is PeerError, is SyncFailed -> e.message ?: e.javaClass.simpleName
        else -> "${e.javaClass.simpleName}${e.message?.let { ": $it" } ?: ""}"
    }

    private fun plural(n: Int, word: String) = "$n ${if (n == 1) word else word + "s"}"

    companion object {
        const val COMPARE = "compare"
        const val TAKE = "take"
        const val GIVE = "give"
        const val MIRROR = "mirror"
        const val AGREE = "agree"
        const val INDEX = "index"

        /** The stages a sync job shows, in order, as (name, label). */
        val STAGES = listOf(COMPARE to "Compare", TAKE to "Take", GIVE to "Give", MIRROR to "Mirror", AGREE to "Agree",
                            INDEX to "Index")

        /** kv: a computer synced with, by its id: {address, name, synced_at}. */
        const val PEER_KEY = "sync:peer:"

        /** kv: the stamps of the computer's indexes the phone merged last, by its id: {site: stamp}. */
        const val INDEX_KEY = "sync:index:"

        /** The phone's library's name, and its caracole's version, as its push names them. */
        const val PHONE_NAME = "Phone"
        const val CARACOLE = "0.1.0"

        const val KEPT_SECONDS = 600L
        const val POLL_EVERY_MS = 1_000L
        const val POLLS = 600

        const val SKIPPED = "skipped"
        const val CHANGED_HERE = "changed here since the comparison"
        const val LEFT_THERE = "the computer left it as it was"
        const val CHANGED_SINCE = "The two libraries changed since the comparison: compare again."

        private const val MINE = "mine"
        private const val THEIRS = "theirs"
        private const val CONFLICT = "conflict"
        private const val RUNNING = "running"
        private const val DONE = "done"
        private const val FAILED = "failed"
        private const val SKIPPED_STATE = "skipped"
    }
}
