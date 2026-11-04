package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.IndexExport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Merged
import io.github.danielhp95.caracole.core.index.TabCounts
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Sites
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.file.FileError
import io.github.danielhp95.caracole.core.sync.file.FileSource
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
import io.github.danielhp95.caracole.core.sync.file.SyncFile
import io.github.danielhp95.caracole.core.sync.internal.client.Address
import io.github.danielhp95.caracole.core.sync.internal.client.Give
import io.github.danielhp95.caracole.core.sync.internal.client.Documents
import io.github.danielhp95.caracole.core.sync.internal.client.Kept as KeptById
import io.github.danielhp95.caracole.core.sync.internal.client.IndexStamps
import io.github.danielhp95.caracole.mirror.SyncError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant
import java.time.ZoneId

enum class Side { HERE, THERE, SKIP }

/** How a sync settles a conflict no choice and no preference settles: [ASK] refuses the sync before any change (the
 * Sync sheet asks the owner first); [LEAVE] leaves it as it is on both sides ([SyncEngine.UNSETTLED]) and goes on, the
 * unattended sync's way, which never settles one. */
enum class Conflicts { ASK, LEAVE }

/** A site whose newest read differs on the two sides (a comparison's `indexes`): each side's stamp (null: never
 * read), and which is [newer], `"here"` or `"there"`. */
data class IndexWaiting(val site: String, val title: String, val here: String?, val there: String?, val newer: String)

/**
 * A comparison with the computer (or, [kind] `"file"`, with a file: [file]), kept by [id] for 10 minutes:
 * [syncedBefore], when the two last agreed (the latest time either side's base records; null: never), as
 * sync_routes.py's `synced_before`; [differences], every one the two hold (within [holds], the parts the other side
 * holds: all three for a computer), and [hash] (Compare.comparedHash) of those; [base] and [kept], the merged base and
 * the kept answers they were compared against (Compare.mergedBase, mergedKept); [listed], the songs either side's
 * songbooks list (Scope.listedSongs); [songbooks], each songbook difference's two documents; [indexes], each site
 * whose newest read differs.
 */
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: String?,
                      val differences: List<Difference>, val hash: String,
                      val kind: String = SyncEngine.COMPUTER, val file: SyncFile? = null,
                      val holds: List<String> = Scope.PARTS, val listed: Map<String, List<String>> = emptyMap(),
                      val songbooks: Map<String, Pair<JsonObject?, JsonObject?>> = emptyMap(),
                      val indexes: List<IndexWaiting> = emptyList(), val base: Map<String, String?>? = null,
                      val kept: Map<String, KeptPair> = emptyMap())

/** What a sync did: the units taken here, given there, and left (with why), how many the two agree on after, the
 * sites merged; and [report], the sync's report (the sync redesign's §3.5: with whom, when, its parts, each index
 * taken or given counted before and after), null for a sync that stopped. */
data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>,
                       val agreed: Int, val indexed: List<String>, val report: JsonObject? = null)

/** What `POST /sync/test` says of the computer at [address] ([SyncEngine.tested]): its state, how many songs and
 * songbooks it holds, its indexes' newest read (null: none), and when the phone last synced with it (null: never). */
data class Tested(val peer: PeerState, val address: String, val songs: Int, val songbooks: Int, val indexes: String?,
                  val syncedAt: String?)

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
                 val name: String = PHONE_NAME, val version: String = CARACOLE,
                 val pagesFromFile: ((SyncFile, List<String>) -> Unit)? = null) {
    /** The clock comparisons are kept by and the phone's own stamps are made of; a test's own. */
    internal var clock: () -> Instant = { Instant.now() }

    /** The zone a refusal says a day in (an older file's "on 03/11/26"): the phone's; a test's own. */
    internal var zone: ZoneId = ZoneId.systemDefault()

    /** How often give asks the computer how its request goes, and how many times at most (10 minutes). */
    internal var pollEveryMs: Long = POLL_EVERY_MS
    internal var polls: Int = POLLS

    private val kept = KeptById<Comparison>(KEPT_SECONDS)

    /** The phone and the computer at [address] (a [peerAddress]), compared; kept by its id for 10 minutes. A
     * [PeerError] (or mirror's SyncError) when the computer can't be asked; [SameCaracole] when it is this phone. */
    fun compare(address: String): Comparison {
        val compared = compared(client(address), address)
        val comparison = Comparison(KeptById.newId(), address, compared.peer, compared.syncedBefore, compared.differences,
                                    compared.hash, COMPUTER, null, Scope.PARTS, compared.listed, compared.songbooks,
                                    compared.indexes, compared.base, compared.kept)
        kept.put(comparison.id, comparison, clock())
        return comparison
    }

    /** The comparison of [id] made within 10 minutes; null for one older, or never made. */
    fun comparison(id: String): Comparison? = kept.get(id, clock())

    /** The comparison of [id] forgotten (its Sync queued, or refused for the two changed since). */
    fun forget(id: String) = kept.remove(id)

    /** Whether the two compare now as they did in [c] (the same hash), the computer's state (or the file) read
     * again; what [compare] throws else. */
    fun stillAsCompared(c: Comparison): Boolean =
        if (c.kind == FILE) compareFile(reread(c.file!!)).hash == c.hash
        else compared(client(c.address), c.address).hash == c.hash

    /** A comparison's file read again, as it is now (an index export by the name it was read by). */
    private fun reread(file: SyncFile): SyncFile = SyncFiles.read(file.file, file.name.takeIf { file.indexOnly })

    /** A unit's two documents in [c] (`GET /api/sync/unit`): this side's now, and the other's (the computer's, asked
     * now; a file's, from it); null for a side that hasn't got it. */
    fun documents(c: Comparison, unitId: String): Pair<JsonObject?, JsonObject?> {
        val here = database.read { db -> Units.document(db, store.libraryDir, unitId) }
        val there = if (c.kind == FILE) FileSource(c.file!!, database, store.libraryDir).use { it.unit(unitId) }
                    else client(c.address).unit(unitId)
        return here to there
    }

    /** What the computer at [address] holds (`POST /sync/test`): its songs, songbooks, its indexes' newest read and
     * when the phone last synced with it, its state read once; it changes nothing. What [compare] throws else. */
    fun tested(address: String): Tested {
        val me = database.read { Compare.ownId(it) }
        val peer = client(address).state(me)
        val server = peer.server
            ?: throw PeerError("The caracole at $address has no id to sync by: it may be older than the app.")
        if (server == me) throw sameCaracole(address, me)
        val syncedAt = database.read { db -> Documents.text((db.kvGetJson(PEER_KEY + server) as? JsonObject)?.get("synced_at")) }
        return Tested(peer, address, peer.units.keys.count { it.startsWith("song/") },
                      peer.units.keys.count { it.startsWith("songbook/") },
                      peer.indexes.values.maxWithOrNull { a, b -> newer(a, b) }, syncedAt)
    }

    /**
     * [c] applied: what the owner chose ([choices], else each difference's proposal, else [prefer] for a conflict)
     * within [parts] (Scope.inScope: a part left out is never read as a removal), in six stages (the class's), or,
     * for a file's comparison, [FILE_STAGES]. With [Conflicts.ASK] a conflict settled neither way refuses the sync
     * before any change; with [Conflicts.LEAVE] it is left ([UNSETTLED]) and the sync goes on.
     */
    suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?, parts: List<String> = Scope.PARTS,
                      conflicts: Conflicts = Conflicts.ASK,
                      stage: (name: String, state: String, detail: String) -> Unit): SyncOutcome {
        val asked = checkedParts(parts)
        if (c.kind == FILE) return applyFile(c, choices, prefer, asked, conflicts, stage)
        val scoped = Scope.inScope(c.differences, asked, c.listed)
        val unsettled = scoped.count { it.proposal == CONFLICT && choices[it.id] == null && prefer == null }
        if (unsettled > 0 && conflicts == Conflicts.ASK) throw SyncFailed(unsettled(unsettled))
        val client = client(c.address)
        val done = Done()

        // 1. compare
        stage(COMPARE, RUNNING, "")
        val fresh = step(stage, COMPARE, null) { io { compared(client, c.address) } }
        if (fresh.hash != c.hash) {
            stage(COMPARE, FAILED, STALE)
            throw SyncFailed(STALE)
        }
        val inScope = Scope.inScope(fresh.differences, asked, fresh.listed)
        stage(COMPARE, DONE, plural(inScope.size, "difference"))
        val me = database.read { Compare.ownId(it) }
        val computer = fresh.peer.server!!

        val toTake = ArrayList<Difference>()
        val toGive = ArrayList<Difference>()
        for (d in inScope) {
            when (choices[d.id] ?: when (d.proposal) { MINE -> Side.HERE; THEIRS -> Side.THERE; else -> prefer }) {
                Side.THERE -> toTake.add(d)
                Side.HERE -> toGive.add(d)
                Side.SKIP -> done.left.add(d.id to SKIPPED)
                null -> done.left.add(d.id to UNSETTLED)
            }
        }

        // 2. take
        if (toTake.isEmpty()) stage(TAKE, SKIPPED_STATE, "") else take(client, stage, done, toTake)

        // 3. give
        if (toGive.isEmpty()) stage(GIVE, SKIPPED_STATE, "") else give(client, stage, done, me, fresh, toGive)

        // 4. mirror
        val refresh = mirrorRefresh
        if (Scope.LIBRARY !in asked) {
            stage(MIRROR, SKIPPED_STATE, LIBRARY_LEFT_OUT)
        } else if (refresh == null) {
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
            done.at = at
            after
        }
        stage(AGREE, DONE, "${plural(done.agreed, "unit")} the two agree on")

        // 6. index
        if (Scope.INDEXES !in asked) stage(INDEX, SKIPPED_STATE, INDEXES_LEFT_OUT)
        else index(client, stage, done, computer, after.indexes, after.token)
        return done.outcome(report(after.name, COMPUTER, c.address, done.at ?: Stamps.of(clock()), asked, done.reported))
    }

    // --- an import: a sync with a file ---------------------------------------------------------------------------

    /**
     * This library and the `.caracole` file at [file] (or an index export; [name], its own name when [file] is a
     * staged copy) compared, as a sync compares two sides (peer_file.compare_file): against this side's base for the
     * file's caracole merged with the one the file keeps for this side, with the answers both remembered, within the
     * parts the file holds (Scope.inScope with its `holds`: a part it lacks is never read as removed); kept by its id
     * for 10 minutes. A [FileError] in the owner's words for a file refused (SyncFiles.read, checkImportable and
     * checkWhole: another format, this library's own export, one older than the last sync with its caracole, one
     * that can't be read whole), before anything is changed; an index export compares as no difference.
     */
    fun compareFile(file: File, name: String? = null): Comparison {
        val read = SyncFiles.read(file, name)
        val c = compareFile(read)
        kept.put(c.id, c, clock())
        return c
    }

    private fun compareFile(sf: SyncFile): Comparison {
        val me = database.read { Compare.ownId(it) }
        database.read { db -> SyncFiles.checkImportable(sf, db, me, zone) }
        SyncFiles.checkWhole(sf)
        val state = sf.state ?: PeerState(Units.FORMAT, null, Documents.text(sf.manifest["caracole"]) ?: "?", sf.name,
                                          sf.made, emptyMap(), null, "")
        val compared = try {
            FileSource(sf, database, store.libraryDir).use { source ->
                database.read { db -> SyncFiles.compareFile(db, sf, source, me) to source.documents() }
            }
        } catch (e: PeerError) {
            throw FileError(e.message ?: "")
        }
        val (found, documents) = compared
        val songbooks = found.found.filter { it.id.startsWith(SONGBOOK) }.associateTo(LinkedHashMap()) { d ->
            d.id to (database.read { db -> Units.document(db, store.libraryDir, d.id) } to
                     (documents[d.id]?.get("unit") as? JsonObject))
        }
        val newest = database.read { db -> IndexTransfer.newest(db) }
        return Comparison(KeptById.newId(), "", state, found.syncedBefore, found.found, Compare.comparedHash(found.found),
                          FILE, sf, sf.holds, found.listed, songbooks, waiting(newest, state.indexes), found.base,
                          found.kept)
    }

    /**
     * An import of [c]'s file, as `caracole peer import` makes one (commands/peer.py), in [FILE_STAGES]:
     * 1. **check**: the file read and compared again; a hash other than the comparison's refuses it before any
     *    change ([STALE]), as does a refusal of the file's (its words); then each difference within [parts] decided.
     * 2. **take**: a backup first (none: nothing taken), then each unit the file gives, from it (FileSource), as a
     *    pull takes one.
     * 3. **mirror**: the units taken handed to the pages hook ([pagesFromFile]), which keeps the file's pages of them;
     *    skipped with no hook or nothing taken; its failure stops nothing.
     * 4. **agree**: what the two now agree on recorded as agreed with the file's caracole at its `made`, of the units
     *    the file speaks for, and each conflict answered "keep mine" remembered (SyncFiles.recordImport); skipped for
     *    an index export, or a file of neither the library nor the songbooks.
     * 5. **index**: its indexes merged (IndexTransfer.merge), each site counted before and after.
     * A file takes nothing back: nothing is given. The report's `with` is the file's library, of kind `"file"`.
     */
    private suspend fun applyFile(c: Comparison, choices: Map<String, Side>, prefer: Side?, parts: List<String>,
                                  conflicts: Conflicts, stage: (String, String, String) -> Unit): SyncOutcome {
        val done = Done()
        val now = Stamps.of(clock())

        // 1. check
        stage(CHECK, RUNNING, "")
        val fresh = step(stage, CHECK, null) {
            io {
                try {
                    compareFile(reread(c.file!!))
                } catch (e: FileError) {
                    throw SyncFailed(e.message ?: "", null, e)
                }
            }
        }
        if (fresh.hash != c.hash) {
            stage(CHECK, FAILED, STALE)
            throw SyncFailed(STALE)
        }
        val sf = fresh.file!!
        val held = parts.filter { it in sf.holds }
        val scoped = Scope.inScope(fresh.differences, parts, fresh.listed)
        val unsettled = scoped.count { it.proposal == CONFLICT && choices[it.id] == null && prefer == null }
        if (unsettled > 0 && conflicts == Conflicts.ASK) {
            stage(CHECK, FAILED, unsettled(unsettled))
            throw SyncFailed(unsettled(unsettled))
        }
        val toTake = ArrayList<Difference>()
        val toKeep = ArrayList<Difference>()
        for (d in scoped) {
            when (choices[d.id] ?: when (d.proposal) { MINE -> Side.HERE; THEIRS -> Side.THERE; else -> prefer }) {
                Side.THERE -> toTake.add(d)
                Side.HERE -> toKeep.add(d)
                Side.SKIP -> done.left.add(d.id to SKIPPED)
                null -> done.left.add(d.id to UNSETTLED)
            }
        }
        val keptHere = SyncFiles.keptAnswers(scoped, toKeep)
        stage(CHECK, DONE, "${plural(scoped.size, "difference")} with ${Py.strip(sf.name).ifEmpty { "a file" }}'s file")

        // 2. take
        val taken = if (toTake.isEmpty()) {
            stage(TAKE, SKIPPED_STATE, "")
            emptyList()
        } else {
            FileSource(sf, database, store.libraryDir).use { source -> take(source, stage, done, toTake).taken }
        }

        // 3. mirror
        val hook = pagesFromFile
        when {
            hook == null -> stage(MIRROR, SKIPPED_STATE, "no copy of the file's pages on this phone")
            taken.isEmpty() -> stage(MIRROR, SKIPPED_STATE, "nothing taken")
            else -> {
                stage(MIRROR, RUNNING, "")
                try {
                    io { hook(sf, taken) }
                    stage(MIRROR, DONE, plural(taken.size, "unit"))
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    stage(MIRROR, FAILED, said(e))
                }
            }
        }

        // 4. agree
        if (sf.indexOnly || held.none { it == Scope.LIBRARY || it == Scope.SONGBOOKS }) {
            stage(AGREE, SKIPPED_STATE, "")
        } else {
            stage(AGREE, RUNNING, "")
            done.agreed = step(stage, AGREE, done) {
                io { database.write { db -> SyncFiles.recordImport(db, sf, Units.libraryState(db), keptHere) } }
            }
            stage(AGREE, DONE, "${plural(done.agreed, "unit")} the two agree on" +
                if (keptHere.isEmpty()) "" else ", ${keptHere.size} kept here")
        }

        // 5. index
        if (Scope.INDEXES !in parts || Scope.INDEXES !in sf.holds) {
            stage(INDEX, SKIPPED_STATE, "")
        } else {
            stage(INDEX, RUNNING, "")
            try {
                val entries = io { mergeFile(sf) }
                done.reported.addAll(entries)
                done.indexed.addAll(entries.map { Documents.text(it["site"])!! })
                stage(INDEX, DONE, if (entries.isEmpty()) "nothing read more recently"
                                   else "${entries.size} ${if (entries.size == 1) "index" else "indexes"} merged")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                stage(INDEX, FAILED, said(e))
            }
        }
        return done.outcome(report(sf.name, FILE, null, now, held, done.reported))
    }

    /** A file's indexes merged into the database: an index export where it is, a `.caracole` file's copied out to
     * `stateDir/cache/` first and deleted after. The report's entries of the sites it changed. */
    private fun mergeFile(sf: SyncFile): List<JsonObject> {
        val copy = if (sf.indexOnly) null else File(cache(), "import-indexes-${KeptById.newId()}.sqlite")
        try {
            if (copy != null) FileSource(sf, database, store.libraryDir).use { it.indexes(copy) }
            val from = copy ?: sf.file
            val sites = (sf.manifest["indexes"] as? JsonArray)?.mapNotNull { Documents.text(it) } ?: emptyList()
            val counted = database.writeBlocking { db ->
                val before = TabCounts.of(db)
                val merged = IndexTransfer.merge(db, from, Stamps.of(clock()))
                val newest = IndexTransfer.newest(db)
                taken(merged, before, TabCounts.of(db), merged.sites.keys.toList().ifEmpty { sites }) { newest[it] }
            }
            database.checkpoint()
            return counted
        } finally {
            copy?.delete()
        }
    }

    // --- the stages' parts ------------------------------------------------------------------------------------------

    /** What the sync did so far. */
    private class Done {
        val taken = ArrayList<String>()
        val given = ArrayList<String>()
        val left = ArrayList<Pair<String, String>>()
        var agreed = 0
        val indexed = ArrayList<String>()
        val reported = ArrayList<JsonObject>()  // the report's indexes, each taken or given
        var at: String? = null

        fun outcome(report: JsonObject? = null) =
            SyncOutcome(taken.toList(), given.toList(), left.toList(), agreed, indexed.toList(), report)
    }

    private class Compared(val peer: PeerState, val differences: List<Difference>, val syncedBefore: String?,
                           val hash: String, val base: Map<String, String?>?, val kept: Map<String, KeptPair>,
                           val listed: Map<String, List<String>>, val songbooks: Map<String, Pair<JsonObject?, JsonObject?>>,
                           val indexes: List<IndexWaiting>)

    /** The computer's state, the phone's units, base and kept answers, and what the two hold differently
     * (sync_routes._compared), with the songs either side's songbooks list (each songbook the two hold differently
     * asked of the computer once) and the indexes newer on either side. */
    private fun compared(client: PeerClient, address: String): Compared {
        val me = database.read { Compare.ownId(it) }
        val peer = client.state(me)
        val server = peer.server
            ?: throw PeerError("The caracole at $address has no id to sync by: it may be older than the app.")
        if (server == me) throw sameCaracole(address, me)
        val read = database.read { db ->
            val ours = Compare.baseOf(db, server)
            val mine = Units.libraryState(db)
            val books = mine.keys.filter { it.startsWith(SONGBOOK) }.associateWith { Units.value(db, it) }
            Read(mine, ours, Compare.keptOf(db, server), books, IndexTransfer.newest(db))
        }
        val base = Compare.mergedBase(read.base, peer.base)
        val keptAnswers = Compare.mergedKept(read.base, read.keptHere, peer.base, peer.kept)
        val found = Compare.order(Compare.compare(read.mine, peer.units, base, keptAnswers))
        val songbooks = found.filter { it.id.startsWith(SONGBOOK) }.associateTo(LinkedHashMap()) { d ->
            d.id to (database.read { db -> Units.document(db, store.libraryDir, d.id) } to client.unit(d.id))
        }
        val listed = listed(read.books, songbooks.mapValues { it.value.second }, read.mine.keys + peer.units.keys)
        val agreed = listOfNotNull(read.base, peer.base).flatMap { b -> b.values.map { it.second } }
        return Compared(peer, found, agreed.maxWithOrNull(Py.CODE_POINT_ORDER), Compare.comparedHash(found), base,
                        keptAnswers, listed, songbooks, waiting(read.newest, peer.indexes))
    }

    /** What [compared] reads of the phone, in one read. */
    private class Read(val mine: Map<String, SyncUnit>, val base: Base?, val keptHere: Kept,
                       val books: Map<String, kotlinx.serialization.json.JsonElement?>, val newest: Map<String, String>)

    /** The songs songbooks list (Scope.listedOn), of this side's songbooks and of the other's [theirs] (those the
     * two hold differently: of the others, the two hold the same). */
    private fun listed(mine: Map<String, kotlinx.serialization.json.JsonElement?>, theirs: Map<String, JsonObject?>,
                       units: Set<String>): Map<String, List<String>> =
        Scope.listedOn(listOf(mine, theirs.filterValues { it != null }), units)

    /** Each site whose newest read differs on the two sides, in caracole's order (IndexTransfer's sites), with which
     * is newer. */
    private fun waiting(here: Map<String, String>, there: Map<String, String>): List<IndexWaiting> =
        Sites.ALL.mapNotNull { site ->
            val a = here[site.name]
            val b = there[site.name]
            if (a == b) return@mapNotNull null
            val newer = when {
                a == null -> THERE_SIDE
                b == null -> HERE_SIDE
                IndexStamps.newer(b, a) -> THERE_SIDE
                else -> HERE_SIDE
            }
            IndexWaiting(site.name, site.title, a, b, newer)
        }

    /** The comparison with the computer refused: it is this phone (the same id). */
    private fun sameCaracole(address: String, me: String) =
        SameCaracole("The caracole at $address is this one (the same id, $me): its database is a copy of " +
                     "this one's. Give one of them another: caracole peer new-id.")

    /** The take stage: a backup of the phone's database, then each unit of [toTake] taken from [source], each left
     * that changed on either side since the comparison. */
    private suspend fun take(source: UnitSource, stage: (String, String, String) -> Unit, done: Done,
                             toTake: List<Difference>): Applied {
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
                    Take.applyUnits(db, store, source, wanted, expectedHere, now) { _, _ ->
                        seen++
                        stage(TAKE, RUNNING, "$seen of ${plural(toTake.size, "change")}")
                    }
                }
            }
        }
        done.taken.addAll(applied.taken)
        done.left.addAll(applied.left)
        stage(TAKE, DONE, "took ${applied.taken.size}" + if (applied.left.isEmpty()) "" else ", left ${applied.left.size}")
        return applied
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
     * part's failure said on the stage, leaving the rest as it is. Each site merged or given is counted for the
     * report, before and after. */
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
                done.reported.addAll(merge(client, computer, had, newer, indexes))
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
                pushReads(client, computer, token, done)?.let(parts::add)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                failed = true
                parts.add("${pagesRead(noted)} kept for the next sync: ${said(e)}")
            }
        }
        stage(INDEX, if (failed) FAILED else DONE, parts.joinToString("; "))
    }

    /** The computer's indexes of [newer] fetched into `stateDir/cache/` and merged, the kv's stamps brought up to
     * date, the WAL checkpointed; the file gone after, whatever came of it. The report's entries of the sites the
     * merge changed, each site's tabs counted before and after (TabCounts). */
    private suspend fun merge(client: PeerClient, computer: String, had: Map<String, String>, newer: List<String>,
                              indexes: Map<String, String>): List<JsonObject> {
        val file = File(cache(), "index-${KeptById.newId()}.sqlite")
        try {
            io { client.index(file, newer) }
            return io {
                val counted = database.write { db ->
                    val before = TabCounts.of(db)
                    val merged = IndexTransfer.merge(db, file, Stamps.of(clock()), newer)
                    db.kvSetJson(INDEX_KEY + computer, IndexStamps.json(had + newer.associateWith { indexes.getValue(it) }))
                    taken(merged, before, TabCounts.of(db), newer) { indexes[it] }
                }
                database.checkpoint()  // the WAL a big merge grew, given back (lane prep-db)
                counted
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
     * Each site given is counted on the computer (`GET /api/sync/indexes`) before the push and after its merge job, for
     * the report; a computer that can't count them (one older than the app) gives no count, and the report none.
     */
    private suspend fun pushReads(client: PeerClient, computer: String, token: String, done: Done): String? {
        val file = File(cache(), "reads-${KeptById.newId()}.sqlite")
        try {
            val noted = io {
                database.write { db ->
                    val pages = sendable(Reads.since(db, computer))
                    if (pages.isEmpty()) return@write null
                    val read = pages.mapValues { (site, named) ->
                        named.mapNotNull { db.kvGet("${Reads.READ}$site:$it") }.maxWithOrNull(Py.CODE_POINT_ORDER)
                    }
                    val newest = read.values.filterNotNull().maxWithOrNull(Py.CODE_POINT_ORDER) ?: return@write null
                    IndexExport.export(db, file, pages, Stamps.of(clock()), version)
                    Triple(pages, newest, read)
                }
            } ?: return null
            val (pages, upTo, read) = noted
            val before = io { counts(client) }
            val job = io { client.pushIndex(token, file) }
            io { database.write { db -> Reads.forget(db, computer, upTo) } }
            if (before != null) {
                val after = try {
                    val ended = awaitJob(client, job)
                    if (Give.text(ended["state"]) == "done") io { counts(client) } else null
                } catch (e: PeerError) {
                    null
                }
                if (after != null) {
                    for (site in Sites.ALL.map { it.name }.filter { it in pages }) {
                        val was = before[site] ?: continue
                        val now = after[site] ?: continue
                        done.reported.add(entry(site, GIVEN, was.tabs, now.tabs, read[site]))
                    }
                }
            }
            return "sent ${pagesRead(pages)}, none left to send: its request $job merges them"
        } finally {
            file.delete()
        }
    }

    /** The computer's indexes counted (PeerClient.indexes), or null for a computer that can't count them. */
    private fun counts(client: PeerClient): Map<String, IndexCount>? = try {
        client.indexes()
    } catch (e: PeerError) {
        null
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
        /** A comparison's other side, as §3.4.1's `peer.kind` and the report's `with.kind` name it. */
        const val COMPUTER = "computer"
        const val FILE = "file"

        const val CHECK = "check"
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

        /** The mirror stage's words with Library unticked, and the index stage's with Site indexes unticked. */
        const val LIBRARY_LEFT_OUT = "Library isn't synced this time"
        const val INDEXES_LEFT_OUT = "Site indexes aren't synced this time"

        /** The parts named, each once, in Scope.PARTS' order; an IllegalArgumentException in commands/peer.py's
         * words for one that isn't a part. */
        fun checkedParts(parts: Collection<String>): List<String> {
            parts.firstOrNull { it !in Scope.PARTS }?.let {
                throw IllegalArgumentException("'$it' isn't a part: parts are library, songbooks or indexes, by commas.")
            }
            return Scope.PARTS.filter { it in parts }
        }

        /** The report of a sync (the sync redesign's §3.5): with whom, of which kind and at which address (null for a
         * file), when, its parts, each index taken or given. */
        fun report(name: String, kind: String, address: String?, at: String, parts: List<String>,
                   indexes: List<JsonObject>): JsonObject = JsonObject(linkedMapOf(
            "with" to JsonObject(linkedMapOf("name" to JsonPrimitive(name), "kind" to JsonPrimitive(kind),
                                             "address" to JsonPrimitive(address))),
            "at" to JsonPrimitive(at),
            "parts" to JsonArray(parts.map(::JsonPrimitive)),
            "indexes" to JsonArray(indexes),
        ))

        /** One index of a report: its site, its title, taken or given, its first table's rows before and after, and
         * its newest read. */
        fun entry(site: String, direction: String, before: Long, after: Long, read: String?): JsonObject =
            JsonObject(linkedMapOf(
                "site" to JsonPrimitive(site), "title" to JsonPrimitive(Sites.named(site)?.title ?: site),
                "direction" to JsonPrimitive(direction), "before" to JsonPrimitive(before),
                "after" to JsonPrimitive(after), "read" to JsonPrimitive(read),
            ))

        /** A report's entries of the sites a merge changed (its rows, or its first table's count), in caracole's
         * order, each counted [before] and [after] the merge, [read] the site's newest read merged. */
        internal fun taken(merged: Merged, before: Map<String, Long>, after: Map<String, Long>, sites: List<String>,
                           read: (String) -> String?): List<JsonObject> =
            Sites.ALL.map { it.name }.filter { it in sites }.mapNotNull { site ->
                val was = before[site] ?: 0L
                val now = after[site] ?: 0L
                val changed = merged.changed && (merged.sites[site]?.values?.any { it != 0 } == true || was != now)
                if (changed) entry(site, TAKEN, was, now, read(site)) else null
            }

        const val TAKEN = "taken"
        const val GIVEN = "given"
        private const val HERE_SIDE = "here"
        private const val THERE_SIDE = "there"
        private const val SONGBOOK = "songbook/"

        /** Whether stamp [a] is a later time than [b], for the newest of a computer's indexes. */
        private fun newer(a: String, b: String): Int = when {
            IndexStamps.newer(a, b) -> 1
            IndexStamps.newer(b, a) -> -1
            else -> Py.CODE_POINT_ORDER.compare(a, b)
        }

        /** The stages an import of a file shows, in order, as (name, label): `caracole peer import --progress`'s
         * (jobs.PEER_IMPORT_STAGES), the phone's mirror of the file's pages in place of its render. */
        val FILE_STAGES = listOf(
            CHECK to "Reading the file", TAKE to "Taking what changed there", MIRROR to "Keeping the file's pages",
            AGREE to "What the two agree on", INDEX to "Merging the indexes",
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
