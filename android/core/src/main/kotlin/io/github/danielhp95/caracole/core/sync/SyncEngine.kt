package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.IndexExport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Sites
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.internal.client.Address
import io.github.danielhp95.caracole.core.sync.internal.client.Give
import io.github.danielhp95.caracole.core.sync.internal.client.Kept
import io.github.danielhp95.caracole.core.sync.internal.client.IndexStamps
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

/** A comparison with the computer, kept by [id] for 10 minutes: [syncedBefore], when the two last agreed (the latest
 * time either side's base records; null: never), as sync_routes.py's `synced_before`. */
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: String?,
                      val differences: List<Difference>, val hash: String)

data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>,
                       val agreed: Int, val indexed: List<String>)

/** A sync that couldn't go on, or was refused before it began: why, as one sentence ([message]), and what it had done
 * by then ([outcome]; null when it changed nothing yet). */
class SyncFailed(message: String, val outcome: SyncOutcome? = null, cause: Throwable? = null) : Exception(message, cause)

/** The caracole at the address is this phone's own (the same id): its database is a copy of the phone's. */
class SameCaracole(message: String) : Exception(message)

/**
 * The phone's sync with the computer, which the phone starts (the plan's §5.3): it takes what it takes from the
 * computer's peer routes ([client]), then pushes what the computer takes, so the phone serves nothing to the network.
 * Its words are `caracole peer sync --push`'s (commands/peer.py), which does the same from a computer.
 *
 * [compare] reads the computer's state (with what it agreed with this phone, the phone's id asking), the phone's own
 * units and base, and compares them three ways (Compare): the differences, and their hash. The comparison is kept by
 * its id for 10 minutes ([comparison]), for the Sync tab's choices to be applied to; [stillAsCompared] compares
 * again, as the tab's Sync does before it queues anything.
 *
 * [apply] runs six stages, each told to [stage] as it starts and ends (running, then done, skipped, or failed):
 * 1. **compare**: the computer's state read again and compared again; a hash other than the comparison's refuses
 *    the sync before any change ([STALE]: the two changed since the owner chose).
 * 2. **take**: each difference decided (a choice, else its proposal, else, for a conflict, [prefer]; a conflict with
 *    neither is refused before any change; skip leaves it, [SKIPPED]); then, inside Database.write, a backup of the
 *    phone's database (Take.backupBeforeSync: none, nothing taken) and Take.applyUnits from the computer, each unit
 *    left that changed on either side since the comparison.
 * 3. **give**: the units the computer takes, as documents of the phone's state after its take, as peer_push.push_units
 *    gives them (`POST /peer/push/new`, each file it needs, `POST /peer/push`): a unit the phone changed since the
 *    comparison is left out ([CHANGED_HERE]), and so is a song whose file the phone can no longer read as kept
 *    ([FILE_CHANGED]). Then the computer's request is followed every second, 10 minutes at most, with no lock held,
 *    and each unit is given or left as its request says it (its `units`). A request that can't be sent or followed
 *    stops the sync there: no agreement is recorded on either side.
 * 4. **mirror**: the mirror of the computer's pages brought up to date ([mirrorRefresh]; skipped without one); its
 *    failure stops nothing.
 * 5. **agree**: the computer's state read again; what the two hold alike now recorded as agreed at its clock, inside
 *    Database.write (Compare.recordAgreement), with kv `sync:peer:<computer id>` = {address, name, synced_at}, which
 *    GET /api/sync lists, and the computer's settings that state gives taken ([takeSettings], PhoneConfig.take: kv
 *    `phone:settings`, which the phone's lookups read; a computer that gives none leaves them as they were).
 *    Nothing of either side's politeness crosses (docs/superpowers/specs/2026-11-03-politeness-crossing.md): the
 *    phone's cooldowns, request counts, pace and the records that gate its requests stay its own, and so do the
 *    computer's.
 * 6. **index**, both ways:
 *    - the computer's site indexes the phone knows (IndexTransfer's sites) whose stamp is newer than kv
 *      `sync:index:<computer id>` records, fetched into `stateDir/cache/` and merged (IndexTransfer.merge) inside
 *      Database.write, the kv brought up to date, then the WAL checkpointed;
 *    - then, merged or not (whatever came of that, a failure too), the pages the phone's lookups stored since the
 *      last push to that computer (Reads.since: what they read, never a time window, since UG's stamp moves with the
 *      computer's nightly refresh and LaCuerda's rows hold no time) exported (IndexExport.export) into
 *      `stateDir/cache/` within the same write, so that the notes are those of the file, and pushed
 *      (PeerClient.pushIndex, `POST /peer/index`); once the computer answers 202 (its `caracole index merge`
 *      queued), those notes are forgotten (Reads.forget, up to the newest of them), which the stage's detail says.
 *      A push refused or lost keeps them for the next sync. Nothing is sent when none is noted.
 *    Skipped when no index is newer there and no page was read here. Either part's failure is said on the stage
 *    and stops nothing: the agreement stays as it is. The reads go to the computer the phone syncs with next: a
 *    second computer gets those read after (Reads keeps one record of what was pushed, its notes forgotten once).
 *
 * Any stage that stops the sync is a [SyncFailed], with the outcome so far; a refusal before any change has none.
 * The push names the phone's library [name] and its caracole's [version] (the app's own, which it may pass).
 */
class SyncEngine(val database: Database, val store: LibraryStore, val stateDir: File,
                 val client: (String) -> PeerClient, val mirrorRefresh: (suspend (String) -> Unit)?,
                 val name: String = PHONE_NAME, val version: String = CARACOLE) {
    /** The clock comparisons are kept by and the phone's own stamps are made of; a test's own. */
    internal var clock: () -> Instant = { Instant.now() }

    /** How often give asks the computer how its request goes, and how many times at most (10 minutes). */
    internal var pollEveryMs: Long = POLL_EVERY_MS
    internal var polls: Int = POLLS

    private val kept = Kept<Comparison>(KEPT_SECONDS)

    /** The phone and the computer at [address] (a [peerAddress]), compared; kept by its id for 10 minutes. A
     * [PeerError] (or mirror's SyncError) when the computer can't be asked; [SameCaracole] when it is this phone. */
    fun compare(address: String): Comparison {
        val compared = compared(client(address), address)
        val comparison = Comparison(Kept.newId(), address, compared.peer, compared.syncedBefore, compared.differences,
                                    compared.hash)
        kept.put(comparison.id, comparison, clock())
        return comparison
    }

    /** The comparison of [id] made within 10 minutes; null for one older, or never made. */
    fun comparison(id: String): Comparison? = kept.get(id, clock())

    /** The comparison of [id] forgotten (its Sync queued, or refused for the two changed since). */
    fun forget(id: String) = kept.remove(id)

    /** Whether the two compare now as they did in [c] (the same hash), the computer's state read again; what
     * [compare] throws else. */
    fun stillAsCompared(c: Comparison): Boolean = compared(client(c.address), c.address).hash == c.hash

    suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?,
                      stage: (name: String, state: String, detail: String) -> Unit): SyncOutcome {
        val unsettled = c.differences.count { it.proposal == CONFLICT && choices[it.id] == null && prefer == null }
        if (unsettled > 0) throw SyncFailed(unsettled(unsettled))
        val client = client(c.address)
        val done = Done()

        // 1. compare
        stage(COMPARE, RUNNING, "")
        val fresh = step(stage, COMPARE, null) { io { compared(client, c.address) } }
        if (fresh.hash != c.hash) {
            stage(COMPARE, FAILED, STALE)
            throw SyncFailed(STALE)
        }
        stage(COMPARE, DONE, plural(fresh.differences.size, "difference"))
        val me = database.read { Compare.ownId(it) }
        val computer = fresh.peer.server!!

        val toTake = ArrayList<Difference>()
        val toGive = ArrayList<Difference>()
        for (d in fresh.differences) {
            when (choices[d.id] ?: when (d.proposal) { MINE -> Side.HERE; THEIRS -> Side.THERE; else -> prefer }) {
                Side.THERE -> toTake.add(d)
                Side.HERE -> toGive.add(d)
                Side.SKIP -> done.left.add(d.id to SKIPPED)
                null -> done.left.add(d.id to UNSETTLED)
            }
        }

        // 2. take
        if (toTake.isEmpty()) {
            stage(TAKE, SKIPPED_STATE, "")
        } else {
            stage(TAKE, RUNNING, plural(toTake.size, "change"))
            val now = Stamps.of(clock())
            val wanted = toTake.map { it.id to it.theirs?.digest }
            val expectedHere = toTake.associate { it.id to it.mine?.digest }
            var seen = 0
            val applied = step(stage, TAKE, done) {
                io {
                    database.write { db ->
                        Take.backupBeforeSync(db, stateDir, now)
                            ?: throw SyncFailed(NO_BACKUP, done.outcome())
                        Take.applyUnits(db, store, client, wanted, expectedHere, now) { _, _ ->
                            seen++
                            stage(TAKE, RUNNING, "$seen of ${plural(toTake.size, "change")}")
                        }
                    }
                }
            }
            done.taken.addAll(applied.taken)
            done.left.addAll(applied.left)
            stage(TAKE, DONE, "took ${applied.taken.size}" + if (applied.left.isEmpty()) "" else ", left ${applied.left.size}")
        }

        // 3. give
        if (toGive.isEmpty()) stage(GIVE, SKIPPED_STATE, "") else give(client, stage, done, me, fresh, toGive)

        // 4. mirror
        val refresh = mirrorRefresh
        if (refresh == null) {
            stage(MIRROR, SKIPPED_STATE, "no copy of the computer's pages on this phone")
        } else {
            stage(MIRROR, RUNNING, "")
            try {
                refresh(c.address)
                stage(MIRROR, DONE, "")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                stage(MIRROR, FAILED, said(e))
            }
        }

        // 5. agree
        stage(AGREE, RUNNING, "")
        val after = step(stage, AGREE, done) {
            val after = io { client.state(me) }
            val at = after.now ?: Stamps.of(clock())
            done.agreed = io {
                database.write { db ->
                    val agreed = Compare.recordAgreement(db, computer, Units.libraryState(db), after.units, at)
                    db.kvSetJson(PEER_KEY + computer, JsonObject(linkedMapOf(
                        "address" to JsonPrimitive(c.address), "name" to JsonPrimitive(after.name),
                        "synced_at" to JsonPrimitive(at),
                    )))
                    takeSettings(db, after)
                    agreed
                }
            }
            after
        }
        stage(AGREE, DONE, "${plural(done.agreed, "unit")} the two agree on")

        // 6. index
        index(client, stage, done, computer, after.indexes, after.token)
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

    private class Compared(val peer: PeerState, val differences: List<Difference>, val syncedBefore: String?,
                           val hash: String)

    /** The computer's state, the phone's units and base, and what the two hold differently (sync_routes._compared). */
    private fun compared(client: PeerClient, address: String): Compared {
        val me = database.read { Compare.ownId(it) }
        val peer = client.state(me)
        val server = peer.server
            ?: throw PeerError("The caracole at $address has no id to sync by: it may be older than the app.")
        if (server == me) {
            throw SameCaracole("The caracole at $address is this one (the same id, $me): its database is a copy of " +
                               "this one's. Give one of them another: caracole peer new-id.")
        }
        val (mine, ours) = database.read { db -> Units.libraryState(db) to Compare.baseOf(db, server) }
        val found = Compare.order(Compare.compare(mine, peer.units, Compare.mergedBase(ours, peer.base)))
        val agreed = listOfNotNull(ours, peer.base).flatMap { base -> base.values.map { it.second } }
        return Compared(peer, found, agreed.maxWithOrNull(Py.CODE_POINT_ORDER), Compare.comparedHash(found))
    }

    /** The units the computer takes pushed (peer_push.push_units), and its request followed to its end: each unit
     * given, or left with why. */
    private suspend fun give(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, me: String,
                             fresh: Compared, toGive: List<Difference>) {
        stage(GIVE, RUNNING, plural(toGive.size, "change"))
        val (state, documents) = database.read { db ->
            Units.libraryState(db) to toGive.associate { d -> d.id to Units.document(db, store.libraryDir, d.id) }
        }
        val before = done.left.size
        val entries = ArrayList<Give.Entry>()
        for (d in toGive) {
            val now = state[d.id]?.digest
            if (now != d.mine?.digest) done.left.add(d.id to CHANGED_HERE)
            else entries.add(Give.Entry(d.id, expected = d.theirs?.digest, digest = now, unit = documents[d.id]))
        }
        if (entries.isEmpty()) {
            stage(GIVE, DONE, "gave 0, left ${toGive.size}")
            return
        }
        val at = fresh.peer.now ?: Stamps.of(clock())
        val token = fresh.peer.token
        val sent: List<Give.Entry>
        val ended: JsonObject
        val job: Int
        try {
            val (push, need) = io { client.pushNew(token, me, Give.files(entries)) }
            val unreadable = HashSet<String>()
            need.forEachIndexed { i, sha ->
                stage(GIVE, RUNNING, "file ${i + 1} of ${need.size}")
                val bytes = io { Give.read(database, store.libraryDir, sha) }
                if (bytes == null) unreadable.add(sha) else io { client.pushFile(token, push, sha, bytes) }
            }
            sent = entries.filter { entry -> Give.files(listOf(entry)).none { it in unreadable } }
            for (entry in entries) if (entry !in sent) done.left.add(entry.id to FILE_CHANGED)
            job = io { client.push(token, push, Give.document(me, name, version, at, state, sent)) }
            stage(GIVE, RUNNING, "the computer's request $job takes ${plural(sent.size, "change")}")
            ended = awaitJob(client, job)
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            val why = said(e)
            stage(GIVE, FAILED, why)
            throw SyncFailed("There couldn't be given its ${entries.size}: $why", done.outcome(), e)
        }
        val units = Give.units(ended)
        val jobState = Give.text(ended["state"])
        for (entry in sent) {
            val (outcome, why) = units[entry.id] ?: (null to "")
            if (outcome == "taken") {
                done.given.add(entry.id)
            } else {
                done.left.add(entry.id to why.ifEmpty {
                    if (jobState != "done") "its request $job there $jobState" else "not taken there"
                })
            }
        }
        val left = done.left.size - before
        stage(GIVE, DONE, "gave ${done.given.size}" + if (left == 0) "" else ", left $left")
    }

    /** The computer's request [id] followed, every [pollEveryMs], until it is over (peer_push.wait_for): how it ended.
     * A PeerError when it isn't over within [polls] asks (it goes on there all the same). */
    private suspend fun awaitJob(client: PeerClient, id: Int): JsonObject {
        repeat(polls) { asked ->
            val job = io { client.job(id) }
            when (Give.text(job["state"])) {
                "queued", "running" -> if (asked < polls - 1) delay(pollEveryMs)
                else -> return job
            }
        }
        throw PeerError("The caracole at ${client.address} hasn't taken the push yet: its request $id, in its " +
                        "Requests tab, goes on.")
    }

    /** The computer's newer indexes merged, then the pages the phone's lookups read pushed, merged or not; each
     * part's failure said on the stage, leaving the rest as it is. */
    private suspend fun index(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, computer: String,
                              indexes: Map<String, String>, token: String) {
        val (had, noted) = database.read { db ->
            IndexStamps.sites(db.kvGetJson(INDEX_KEY + computer)) to sendable(Reads.since(db, computer))
        }
        val newer = indexes.filter { (site, stamp) ->
            Sites.named(site) != null && (had[site]?.let { IndexStamps.newer(stamp, it) } ?: true)
        }.keys.sortedBy { site -> Sites.ALL.indexOfFirst { it.name == site } }
        if (newer.isEmpty() && noted.isEmpty()) {
            stage(INDEX, SKIPPED_STATE, NOTHING_TO_INDEX)
            return
        }
        stage(INDEX, RUNNING, if (newer.isEmpty()) sending(noted) else newer.joinToString(", "))
        val parts = ArrayList<String>()
        var failed = false
        if (newer.isNotEmpty()) {
            try {
                merge(client, computer, had, newer, indexes)
                done.indexed.addAll(newer)
                parts.add("merged ${newer.joinToString(", ")}")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                failed = true
                parts.add(said(e))
            }
        }
        if (noted.isNotEmpty()) {
            if (newer.isNotEmpty()) stage(INDEX, RUNNING, sending(noted))
            try {
                pushReads(client, computer, token)?.let(parts::add)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                failed = true
                parts.add("${pagesRead(noted)} kept for the next sync: ${said(e)}")
            }
        }
        stage(INDEX, if (failed) FAILED else DONE, parts.joinToString("; "))
    }

    /** The computer's indexes of [newer] fetched into `stateDir/cache/` and merged, the kv's stamps brought up to
     * date, the WAL checkpointed; the file gone after, whatever came of it. */
    private suspend fun merge(client: PeerClient, computer: String, had: Map<String, String>, newer: List<String>,
                              indexes: Map<String, String>) {
        val file = File(cache(), "index-${Kept.newId()}.sqlite")
        try {
            io { client.index(file, newer) }
            io {
                database.write { db ->
                    IndexTransfer.merge(db, file, Stamps.of(clock()), newer)
                    db.kvSetJson(INDEX_KEY + computer, IndexStamps.json(had + newer.associateWith { indexes.getValue(it) }))
                }
                database.checkpoint()  // the WAL a big merge grew, given back (lane prep-db)
            }
        } finally {
            file.delete()
        }
    }

    /**
     * The pages Reads noted since the last push to [computer], exported (IndexExport) in the write that reads them, so
     * that the file holds every page noted and those alone, and pushed (`POST /peer/index`); once the computer answers
     * 202, the notes forgotten up to the newest of them. What it did, in the stage's words; null when nothing is noted
     * by then. A PeerError (or mirror's SyncError) when the push fails, the notes kept; the file gone after either way.
     */
    private suspend fun pushReads(client: PeerClient, computer: String, token: String): String? {
        val file = File(cache(), "reads-${Kept.newId()}.sqlite")
        try {
            val (pages, upTo) = io {
                database.write { db ->
                    val pages = sendable(Reads.since(db, computer))
                    if (pages.isEmpty()) return@write null
                    val newest = pages.flatMap { (site, named) -> named.mapNotNull { db.kvGet("${Reads.READ}$site:$it") } }
                        .maxWithOrNull(Py.CODE_POINT_ORDER) ?: return@write null
                    IndexExport.export(db, file, pages, Stamps.of(clock()), version)
                    pages to newest
                }
            } ?: return null
            val job = io { client.pushIndex(token, file) }
            io { database.write { db -> Reads.forget(db, computer, upTo) } }
            return "sent ${pagesRead(pages)}, none left to send: its request $job merges them"
        } finally {
            file.delete()
        }
    }

    /** `stateDir/cache/`, made when missing; a PeerError in the phone's words when it can't be. */
    private fun cache(): File {
        val cache = File(stateDir, "cache")
        if (!cache.isDirectory && !cache.mkdirs()) throw PeerError("The phone's storage failed: $cache can't be made.")
        return cache
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
        is SyncError, is PeerError, is SyncFailed, is SameCaracole -> e.message ?: e.javaClass.simpleName
        else -> "${e.javaClass.simpleName}${e.message?.let { ": $it" } ?: ""}"
    }

    companion object {
        const val COMPARE = "compare"
        const val TAKE = "take"
        const val GIVE = "give"
        const val MIRROR = "mirror"
        const val AGREE = "agree"
        const val INDEX = "index"

        /** The stages a sync job shows, in order, as (name, label): `caracole peer sync --progress`'s
         * (jobs.PEER_SYNC_STAGES), and the phone's mirror and index between and after them. */
        val STAGES = listOf(
            COMPARE to "Comparing", TAKE to "Taking what changed there", GIVE to "Giving what changed here",
            MIRROR to "Copying the computer's pages", AGREE to "What the two agree on",
            INDEX to "Bringing the indexes up to date",
        )

        /** kv: a computer synced with, by its id: {address, name, synced_at}. */
        const val PEER_KEY = "sync:peer:"

        /** kv: the stamps of the computer's indexes the phone merged last, by its id: {site: stamp}. */
        const val INDEX_KEY = "sync:index:"

        /** The index stage's words with no index newer there and no page read here. */
        const val NOTHING_TO_INDEX = "no index is newer there, and no page read here to send"

        /** "3 pages read here", of Reads.since's pages. */
        fun pagesRead(pages: Map<String, List<String>>): String = plural(pages.values.sumOf { it.size }, "page") + " read here"

        private fun sending(pages: Map<String, List<String>>) = "sending the ${pagesRead(pages)}"

        /** Those of Reads' [pages] an export holds (IndexExport.PAGES' sites): a note of another site's, which no
         * site lane makes, never stops the rest from going. */
        private fun sendable(pages: Map<String, List<String>>) = pages.filterKeys { it in IndexExport.PAGES }

        /** The phone's library's name, and its caracole's version, as its push names them unless it is given others. */
        const val PHONE_NAME = "Phone"
        const val CARACOLE = "0.1.0"

        const val KEPT_SECONDS = 600L
        const val POLL_EVERY_MS = 1_000L
        const val POLLS = 600

        /** Why a unit is left, in commands/peer.py's and peer_sync.py's words. */
        const val SKIPPED = "skipped, as chosen"
        const val UNSETTLED = "a conflict: choose a side for it"
        const val CHANGED_HERE = "changed here since the comparison"
        const val FILE_CHANGED = "a file it keeps changed here since caracole kept it"

        /** commands/peer.py's STALE: the two changed since the comparison. */
        const val STALE = "The two changed since that comparison: compare them again, and choose again."
        const val NO_BACKUP = "Nothing taken: no backup of the database first, not enough room."

        /** sync_routes.apply's refusal of a conflict settled neither way. */
        fun unsettled(n: Int) = "Choose a side for every conflict first: $n ${if (n == 1) "has" else "have"} none."

        /** peer_sync.peer_address: the address of another caracole serve as typed ("192.168.1.20:8737",
         * "http://phone.lan:8737/"), as caracole asks it: `http://` when no scheme is given, no trailing `/`. A
         * [PeerError] in its words for one that isn't. */
        fun peerAddress(text: String): String = Address.peerAddress(text)

        /** The agree stage's take of the computer's settings (docs/superpowers/specs/2026-11-03-politeness-crossing.md,
         * "Settings"): those [state] gives kept by PhoneConfig.take, replacing the last; a state that gives none (a
         * computer older than them, or a `settings` that isn't an object: [PeerState.settings] null) leaves the
         * phone's as they were. SettingsReplay replays vectors/sync/settings_take.jsonl through it. */
        fun takeSettings(db: Db, state: PeerState) {
            state.settings?.let { PhoneConfig.take(db, it) }
        }

        private const val MINE = "mine"
        private const val THEIRS = "theirs"
        private const val CONFLICT = "conflict"
        private const val RUNNING = "running"
        private const val DONE = "done"
        private const val FAILED = "failed"
        private const val SKIPPED_STATE = "skipped"

        private fun plural(n: Int, word: String) = "$n ${if (n == 1) word else word + "s"}"
    }
}
