package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Have
import io.github.danielhp95.caracole.core.index.IndexExport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Merged
import io.github.danielhp95.caracole.core.index.MergedIndexes
import io.github.danielhp95.caracole.core.index.MergeProgress
import io.github.danielhp95.caracole.core.index.Paced
import io.github.danielhp95.caracole.core.index.Sizes
import io.github.danielhp95.caracole.core.index.TabCounts
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Sites
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TransferError
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideChecks
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
import kotlinx.coroutines.NonCancellable
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

/** A site of a comparison's `indexes`: each side's newest read (null: never read), and [newer], `"there"` or
 * `"here"`. With the computer, a site the sync's index stage takes from it ("there") or whose pages the phone's
 * lookups read it gives ("here"), a site of both twice; with a file, a site whose newest read differs on the two
 * sides, the later's side. */
data class IndexWaiting(val site: String, val title: String, val here: String?, val there: String?, val newer: String)

/**
 * A comparison with the computer (or, [kind] `"file"`, with a file: [file]), kept by [id] for 10 minutes:
 * [syncedBefore], when the two last agreed (the latest time either side's base records; null: never), as
 * sync_routes.py's `synced_before`; [differences], every one the two hold (within [holds], the parts the other side
 * holds: all three for a computer), and [hash] (Compare.comparedHash) of those; [base] and [kept], the merged base and
 * the kept answers they were compared against (Compare.mergedBase, mergedKept); [listed], the songs either side's
 * songbooks list (Scope.listedSongs); [songbooks], each songbook difference's two documents; [indexes], the sites the
 * index stage will take and give (IndexWaiting), none with a computer of another schema, whose [indexesSkipped] says
 * why (SyncEngine.indexesSkipped; null else).
 */
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: String?,
                      val differences: List<Difference>, val hash: String,
                      val kind: String = SyncEngine.COMPUTER, val file: SyncFile? = null,
                      val holds: List<String> = Scope.PARTS, val listed: Map<String, List<String>> = emptyMap(),
                      val songbooks: Map<String, Pair<JsonObject?, JsonObject?>> = emptyMap(),
                      val indexes: List<IndexWaiting> = emptyList(), val base: Map<String, String?>? = null,
                      val kept: Map<String, KeptPair> = emptyMap(), val indexesSkipped: String? = null)

/** What a sync did: the units taken here, given there, and left (with why), how many the two agree on after, the
 * sites merged; and [report], the sync's report (the sync redesign's §3.5: with whom, when, its parts, each index
 * taken or given counted before and after), null for a sync that stopped; [labels], each unit left's label as
 * compared ("Radiohead - Creep", "songbook Campfire"), the name its line says it by (SyncRoutes.said); [compared],
 * the differences as compared of the units taken and given, which its lines of what it took and gave say them by
 * (SyncSaid: a label, a removal, a conflict). */
data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>,
                       val agreed: Int, val indexed: List<String>, val report: JsonObject? = null,
                       val labels: Map<String, String> = emptyMap(), val compared: List<Difference> = emptyList()) {
    /** What it left as it was that is a change left ([Take.isChangeLeft]): the job's outcome (SyncJson.outcome) and
     * its "Left as it was:" lines (SyncRoutes.said) say these, the sync's own outcome as it ends. */
    val changesLeft: List<Pair<String, String>> get() = left.filter { Take.isChangeLeft(it.second) }
}

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
 *    left that changed on either side since the comparison; then, in the same write, what was taken recorded as
 *    agreed at the computer's clock as compared (Compare.recordTaken, peer_sync.record_taken: those the phone now
 *    holds so), so that whatever stops the sync after its take leaves it agreed, never a conflict once the computer
 *    changes it.
 * 3. **give**: the units the computer takes, as documents of the phone's state after its take, as peer_push.push_units
 *    gives them (`POST /peer/push/new`, each file it needs, `POST /peer/push`), in as many pushes as the computer's
 *    limits ask ([pushLimits], Give.cut), one at a time: a unit the phone changed since the comparison is left out
 *    ([CHANGED_HERE]), and so is a song whose file the phone can no longer read as kept ([FILE_CHANGED]), one with a
 *    kept file past 64 MiB (FileError.TOO_BIG) and a unit that alone passes what a push carries (Give.TOO_LONG,
 *    Give.TOO_HEAVY). Each push's request is followed every second, 10 minutes at most, with no lock held, before the
 *    next is opened, and each unit is given or left as its request says it (its `units`). A request that can't be
 *    sent or followed stops the sync there, saying how far the give got: the pushes before it taken and agreed there,
 *    the phone no more than its take did; a push that fails, or is cancelled, before its document is taken is let go
 *    of there at once (`POST /peer/push/drop`, PeerClient.pushDrop), so that it holds none of the computer's two slots
 *    for the hour (a drop that fails is said nowhere: the phone's next push lets go of it there).
 * 4. **mirror**: the mirror of the computer's pages brought up to date ([mirrorRefresh], told what to say as it goes:
 *    "120 of 640 pages"; skipped without one); its failure stops nothing.
 * 5. **agree**: the computer's state read again; what the two hold alike now recorded as agreed at its clock, inside
 *    Database.write (Compare.recordAgreement), with kv `sync:peer:<computer id>` = {address, name, synced_at}, which
 *    GET /api/sync lists, and the computer's settings that state gives taken ([takeSettings], PhoneConfig.take: kv
 *    `phone:settings`, which the phone's lookups read; a computer that gives none leaves them as they were).
 *    Nothing of either side's politeness crosses (docs/superpowers/specs/2026-11-03-politeness-crossing.md): the
 *    phone's cooldowns, request counts, pace and the records that gate its requests stay its own, and so do the
 *    computer's.
 * 6. **index**, both ways:
 *    - the computer's site indexes the phone knows (IndexTransfer's sites) whose stamp is later than both kv
 *      `sync:index:<computer id>`'s (what the phone took of it last) and MergedIndexes' (the newest read of the whole
 *      exports the phone merged: the site catalogues, a file's indexes, an index imported, a sync's own), never the
 *      phone's own newest, which its lookups' reads move ([newerThere], the comparison's rule too), fetched into
 *      `stateDir/cache/`, only the part of them the phone doesn't hold (`POST /peer/index/newer`, [merge]: the
 *      sitemaps whose record differs from the phone's, each whole, and the pages read since the last export of the
 *      computer's it merged, kv `sync:cut:<computer id>`; the whole, `GET /api/peer/index`, from a computer older than
 *      the route), and merged (IndexTransfer.merge) inside Database.write, the records brought up to date once the
 *      file is the part asked for, then the WAL checkpointed; the stage says each step as it goes
 *      ("The computer is copying its indexes…" until the answer begins, "Downloading the computer's indexes · 120 of
 *      274 MB", the merge's MergeProgress.words, "Tidying the database…"), a count at most once a second ([ticks]),
 *      each step's words the stage's detail with one "…" at their end left off ([detail]: its line adds its own);
 *    - then, merged or not (whatever came of that, a failure too), the pages the phone's lookups stored since the
 *      last push to that computer (Reads.since: what they read, never a time window, since UG's stamp moves with the
 *      computer's nightly refresh and LaCuerda's rows hold no time) exported (IndexExport.export) into
 *      `stateDir/cache/` within the same write, so that the notes are those of the file, and pushed
 *      (PeerClient.pushIndex, `POST /peer/index`); once the computer's request that merges them (its `caracole index
 *      merge`) ends done, those notes are forgotten (Reads.forget, up to the newest of them), which the stage's
 *      detail says, and each site's stamp there that those pages alone moved (no later than the newest of them, and
 *      the computer's stamp before the push one the phone held) is kept as what the phone holds of it (kv
 *      `sync:index:<computer id>`): the next sync downloads no whole index for the phone's own pages. A push
 *      refused or lost, a merge there that ends otherwise than done, or one still going at the wait's end (10
 *      minutes) keeps them for the next sync, which sends them again. Nothing is sent when none is noted.
 *    Skipped when no index is newer there and no page was read here; and, before anything is asked for either way,
 *    when the computer's database is of another schema (its state's `schema`, [indexesSkipped]'s words: its index
 *    export would be downloaded whole to be refused by the merge here, the pages read here refused by its), the
 *    pages read here kept for once the two agree. A merge's refusal is said with its file named, never by the path
 *    of its copy here ([namingFileAs]). Either part's failure is said on the stage and stops nothing: the
 *    agreement stays as it is. The reads go to the computer the phone syncs with next: a second computer gets those
 *    read after (Reads keeps one record of what was pushed, its notes forgotten once).
 *
 * Any stage that stops the sync is a [SyncFailed], with the outcome so far; a refusal before any change has none.
 * The push names the phone's library [name] and its caracole's [version] (the app's own, which it may pass).
 * [checks] are the viewer's checks of a song's `[version]` and `[harmonica]` entries, which a take runs as
 * overrides.put_song_entries reads its entries back (Assembly gives Versions.keyVersion and HarpTabs.checkSpec).
 */
class SyncEngine(val database: Database, val store: LibraryStore, val stateDir: File,
                 val client: (String) -> PeerClient, val mirrorRefresh: (suspend (String, (String) -> Unit) -> Unit)?,
                 val name: String = PHONE_NAME, val version: String = CARACOLE,
                 val pagesFromFile: ((SyncFile, List<String>, (String) -> Unit) -> Unit)? = null,
                 val checks: OverrideChecks = OverrideChecks.NONE) {
    /** The clock comparisons are kept by and the phone's own stamps are made of; a test's own. */
    internal var clock: () -> Instant = { Instant.now() }

    /** The clock a stage's counts are paced by (Paced: at most one a second within a step); a test's own. */
    internal var ticks: () -> Long = System::nanoTime

    /** A stage's running words, paced (Paced): each step's first at once, a count at most once a second; each its
     * [detail], one "…" at its end left off. */
    private fun paced(stage: (String, String, String) -> Unit, name: String): Paced =
        Paced({ words -> stage(name, RUNNING, detail(words)) }, ticks = ticks)

    /** The latest time an index merged here may say it was read at (IndexTransfer.merge's `notAfter`): the clock and
     * a day more, for another device's clock ahead of the phone's. */
    private fun notAfter(): Long = Stamps.micros(clock().plus(java.time.Duration.ofDays(1)))

    /** The zone a refusal says a day in (an older file's "on 03/11/26"): the phone's; a test's own. */
    internal var zone: ZoneId = ZoneId.systemDefault()

    /** How often give asks the computer how its request goes, and how many times at most (10 minutes). */
    internal var pollEveryMs: Long = POLL_EVERY_MS
    internal var polls: Int = POLLS

    /** What the computer takes of a push at most (its routes' limits, Give.Limits'); a test's own, smaller. */
    internal var pushLimits: Give.Limits = Give.Limits()

    private val kept = KeptById<Comparison>(KEPT_SECONDS)

    /** The phone and the computer at [address] (a [peerAddress]), compared; kept by its id for 10 minutes. A
     * [PeerError] (or mirror's SyncError) when the computer can't be asked, an [OtherKeys] when it keys its songs by
     * other rules than the phone (PeerClient.state); [SameCaracole] when it is this phone. */
    fun compare(address: String): Comparison {
        val compared = compared(client(address), address)
        val comparison = Comparison(KeptById.newId(), address, compared.peer, compared.syncedBefore, compared.differences,
                                    compared.hash, COMPUTER, null, Scope.PARTS, compared.listed, compared.songbooks,
                                    compared.indexes, compared.base, compared.kept,
                                    indexesSkipped(compared.peer.schema))
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
     * now; a file's, from it); null for a side that hasn't got it, and for a file's unit it names but left out as it
     * was exported, or of a part it doesn't hold (the PeerError a take leaves such a unit by: nothing of it to show). */
    fun documents(c: Comparison, unitId: String): Pair<JsonObject?, JsonObject?> {
        val here = database.read { db -> Units.document(db, store.libraryDir, unitId) }
        val there = if (c.kind == FILE) {
            FileSource(c.file!!, database, store.libraryDir).use { if (it.says(unitId)) it.unit(unitId) else null }
        } else client(c.address).unit(unitId)
        return here to there
    }

    /** What the computer at [address] holds (`POST /sync/test`): its songs, songbooks, its indexes' newest read and
     * when the phone last synced with it, its state read once; it changes nothing. What [compare] throws else. */
    fun tested(address: String): Tested {
        val me = database.read { Compare.ownId(it) }
        val peer = client(address).state(me)
        val server = peer.server
            ?: throw PeerError("$address has no id to share logs by: it may be older than the app.")
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
        val done = Done(c.differences)

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
        // The song given: its removal on the computer answered with it, neither taken nor left.
        toTake.removeAll(Compare.answeredByItsSong(toTake, toGive).toSet())

        // 2. take
        var took: Applied? = null
        if (toTake.isEmpty()) stage(TAKE, SKIPPED_STATE, "")
        else {
            val at = fresh.peer.now ?: Stamps.of(clock())
            took = take(client, stage, done, toTake) { db, mine, taken -> Compare.recordTaken(db, computer, mine, taken, at) }
        }

        // 3. give
        if (toGive.isEmpty()) stage(GIVE, SKIPPED_STATE, "")
        else give(client, stage, done, me, fresh, toGive, took?.respelledDigests.orEmpty())

        // 4. mirror
        val refresh = mirrorRefresh
        if (Scope.LIBRARY !in asked) {
            stage(MIRROR, SKIPPED_STATE, LIBRARY_LEFT_OUT)
        } else if (refresh == null) {
            stage(MIRROR, SKIPPED_STATE, "no copy of the computer's pages here")
        } else {
            stage(MIRROR, RUNNING, "")
            val pacer = paced(stage, MIRROR)
            try {
                refresh(c.address) { words -> pacer.say(words, MIRROR) }
                pacer.flush()  // its last count, before the stage's end
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
        stage(AGREE, DONE, "${plural(done.agreed, "unit")} the books agree on")

        // 6. index
        val skipped = indexesSkipped(after.schema)
        when {
            Scope.INDEXES !in asked -> stage(INDEX, SKIPPED_STATE, INDEXES_LEFT_OUT)
            skipped != null -> stage(INDEX, SKIPPED_STATE, skipped)  // nothing asked either way: a merge refuses both
            else -> index(client, stage, done, computer, after.indexes, after.token)
        }
        return done.outcome(report(after.name, COMPUTER, c.address, done.at ?: Stamps.of(clock()), asked, done.reported,
                                   skipped.takeIf { Scope.INDEXES in asked }))
    }

    // --- an import: a sync with a file ---------------------------------------------------------------------------

    /**
     * This library and the `.caracole` file at [file] (or an index export; [name], its own name when [file] is a
     * staged copy) compared, as a sync compares two sides (peer_file.compare_file): against this side's base for the
     * file's caracole merged with the one the file keeps for this side, with the answers both remembered, within the
     * parts the file holds (Scope.inScope with its `holds`: a part it lacks is never read as removed); kept by its id
     * for 10 minutes. A [FileError] in the owner's words for a file refused (SyncFiles.read, checkImportable,
     * newerThan and checkWhole: another format, this library's own export, one with nothing left to take since the
     * last sync with its caracole, one that can't be read whole), before anything is changed; an index export compares as no difference.
     */
    fun compareFile(file: File, name: String? = null): Comparison {
        val read = SyncFiles.read(file, name)
        val c = compareFile(read)
        kept.put(c.id, c, clock())
        return c
    }

    private fun compareFile(sf: SyncFile): Comparison {
        val me = database.read { Compare.ownId(it) }
        SyncFiles.checkImportable(sf, me)
        SyncFiles.checkWhole(sf)
        val state = sf.state ?: PeerState(Units.FORMAT, null, Documents.text(sf.manifest["caracole"]) ?: "?", sf.name,
                                          sf.made, emptyMap(), null, "")
        val compared = try {
            FileSource(sf, database, store.libraryDir).use { source ->
                database.read { db -> SyncFiles.compareFile(db, sf, source, me, zone) to source.documents() }
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
                          FILE, sf, sf.holds, found.listed, songbooks, differing(newest, state.indexes), found.base,
                          found.kept)
    }

    /**
     * An import of [c]'s file, as `caracole peer import` makes one (commands/peer.py), in [FILE_STAGES]:
     * 1. **check**: the file read and compared again; a hash other than the comparison's refuses it before any
     *    change ([STALE]), as does a refusal of the file's (its words); then each difference within [parts] decided.
     * 2. **take**: a backup first (none: nothing taken), then each unit the file gives, from it (FileSource), as a
     *    pull takes one; then, in the same write, what was taken recorded as agreed with the file's caracole at its
     *    `made` (SyncFiles.recordTaken), so that an import stopped before its agree (the mirror stage cancelled, the
     *    app killed) leaves it agreed.
     * 3. **mirror**: the units taken handed to the pages hook ([pagesFromFile]), which keeps the file's pages of them,
     *    told what to say as it goes ("12 of 40 pages kept"); skipped with no hook or nothing taken; its failure stops
     *    nothing.
     * 4. **agree**: what the two now agree on recorded as agreed with the file's caracole at its `made`, of the units
     *    the file speaks for, and each conflict answered "keep mine" remembered (SyncFiles.recordImport); skipped for
     *    an index export, or a file of neither the library nor the songbooks.
     * 5. **index**: its indexes merged (IndexTransfer.merge), each site counted before and after, a `.caracole` file's
     *    copied out first ("Copying the file's indexes out…"), the merge's steps said as the computer's are.
     * A file takes nothing back: nothing is given. The report's `with` is the file's library, of kind `"file"`.
     */
    private suspend fun applyFile(c: Comparison, choices: Map<String, Side>, prefer: Side?, parts: List<String>,
                                  conflicts: Conflicts, stage: (String, String, String) -> Unit): SyncOutcome {
        val done = Done(c.differences)
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
        // A song kept here: the file's removal of it answered with it, remembered beside it.
        val answered = Compare.answeredByItsSong(toTake, toKeep)
        toTake.removeAll(answered.toSet())
        toKeep.addAll(answered)
        val keptHere = SyncFiles.keptAnswers(scoped, toKeep)
        stage(CHECK, DONE, "${plural(scoped.size, "difference")} with ${Py.strip(sf.name).ifEmpty { "a file" }}'s file")

        // 2. take
        val taken = if (toTake.isEmpty()) {
            stage(TAKE, SKIPPED_STATE, "")
            emptyList()
        } else {
            FileSource(sf, database, store.libraryDir).use { source ->
                take(source, stage, done, toTake) { db, mine, taken ->
                    SyncFiles.recordTaken(db, sf, mine, taken)
                }.taken
            }
        }

        // 3. mirror
        val hook = pagesFromFile
        when {
            hook == null -> stage(MIRROR, SKIPPED_STATE, "no copy of the file's pages on this phone")
            taken.isEmpty() -> stage(MIRROR, SKIPPED_STATE, "nothing taken")
            else -> {
                stage(MIRROR, RUNNING, "")
                val pacer = paced(stage, MIRROR)
                try {
                    io { hook(sf, taken) { words -> pacer.say(words, MIRROR) } }
                    pacer.flush()
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
            val pacer = paced(stage, INDEX)
            try {
                val entries = io { mergeFile(sf, pacer) }
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
     * `stateDir/cache/` first and deleted after; what it read recorded (MergedIndexes), so that a sync with the
     * computer that made it asks it for none of them again. The report's entries of the sites it changed. */
    private fun mergeFile(sf: SyncFile, pacer: Paced): List<JsonObject> {
        val copy = if (sf.indexOnly) null else File(cache(), "import-indexes-${KeptById.newId()}.sqlite")
        try {
            if (copy != null) {
                pacer.say(COPYING_OUT)
                FileSource(sf, database, store.libraryDir).use { it.indexes(copy) }
            }
            val from = copy ?: sf.file
            val sites = (sf.manifest["indexes"] as? JsonArray)?.mapNotNull { Documents.text(it) } ?: emptyList()
            val counted = database.writeBlocking { db ->
                val before = TabCounts.of(db)
                // A site the phone holds rows of is updated: what is newer in the file, and the rows checked.
                val words = MergeProgress.Updating(before.filterValues { it > 0 }.keys, MergeProgress.IN_THE_FILE)
                val merged = namingFileAs(from, THE_FILE) {
                    IndexTransfer.merge(db, from, Stamps.of(clock()), notAfter = notAfter(),
                                        progress = { pacer.say(words.words(it), it.step) })
                }
                MergedIndexes.record(db, merged)
                val newest = IndexTransfer.newest(db)
                taken(merged, before, TabCounts.of(db), merged.sites.keys.toList().ifEmpty { sites }) { newest[it] }
            }
            pacer.say(MergeProgress.TIDYING)
            database.checkpoint()
            return counted
        } finally {
            copy?.delete()
        }
    }

    // --- the stages' parts ------------------------------------------------------------------------------------------

    /** What the sync did so far, of the [compared] differences (the labels its leftovers, and what it took and gave,
     * are said by). */
    private class Done(private val compared: List<Difference>) {
        val taken = ArrayList<String>()
        val given = ArrayList<String>()
        val left = ArrayList<Pair<String, String>>()
        var agreed = 0
        val indexed = ArrayList<String>()
        val reported = ArrayList<JsonObject>()  // the report's indexes, each taken or given
        var at: String? = null

        fun outcome(report: JsonObject? = null): SyncOutcome {
            val ids = left.map { it.first }.toSet()
            val went = (taken + given).toSet()
            return SyncOutcome(taken.toList(), given.toList(), left.toList(), agreed, indexed.toList(), report,
                               compared.filter { it.id in ids }.associate { it.id to it.label },
                               compared.filter { it.id in went })
        }
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
            ?: throw PeerError("$address has no id to share logs by: it may be older than the app.")
        if (server == me) throw sameCaracole(address, me)
        val read = database.read { db ->
            val ours = Compare.baseOf(db, server)
            val mine = Units.libraryState(db)
            val books = mine.keys.filter { it.startsWith(SONGBOOK) }.associateWith { Units.value(db, it) }
            Read(mine, ours, Compare.keptOf(db, server), books, IndexTransfer.newest(db),
                 IndexStamps.sites(db.kvGetJson(INDEX_KEY + server)), MergedIndexes.of(db),
                 sendable(Reads.since(db, server)).keys)
        }
        val base = Compare.mergedBase(read.base, peer.base)
        val keptAnswers = Compare.mergedKept(read.base, read.keptHere, peer.base, peer.kept)
        val found = Compare.order(Compare.compare(read.mine, peer.units, base, keptAnswers))
        val songbooks = found.filter { it.id.startsWith(SONGBOOK) }.associateTo(LinkedHashMap()) { d ->
            d.id to (database.read { db -> Units.document(db, store.libraryDir, d.id) } to client.unit(d.id))
        }
        val listed = listed(read.books, songbooks.mapValues { it.value.second }, read.mine.keys + peer.units.keys)
        val agreed = listOfNotNull(read.base, peer.base).flatMap { b -> b.values.map { it.second } }
        val taken = newerThere(peer.indexes, read.had, read.merged)
        val indexes = if (indexesSkipped(peer.schema) != null) emptyList()
                      else waiting(read.newest, peer.indexes, taken, read.noted)
        return Compared(peer, found, agreed.maxWithOrNull(Py.CODE_POINT_ORDER), Compare.comparedHash(found), base,
                        keptAnswers, listed, songbooks, indexes)
    }

    /** What [compared] reads of the phone, in one read: with its indexes' newest reads, the records the index stage
     * asks by ([had], kv `sync:index:<computer id>`; [merged], MergedIndexes) and the sites of the pages its lookups
     * read since the last push ([noted]). */
    private class Read(val mine: Map<String, SyncUnit>, val base: Base?, val keptHere: Kept,
                       val books: Map<String, kotlinx.serialization.json.JsonElement?>, val newest: Map<String, String>,
                       val had: Map<String, String>, val merged: Map<String, String>, val noted: Set<String>)

    /** The songs songbooks list (Scope.listedOn), of this side's songbooks and of the other's [theirs] (those the
     * two hold differently: of the others, the two hold the same). */
    private fun listed(mine: Map<String, kotlinx.serialization.json.JsonElement?>, theirs: Map<String, JsonObject?>,
                       units: Set<String>): Map<String, List<String>> =
        Scope.listedOn(listOf(mine, theirs.filterValues { it != null }), units)

    /** The sites a sync's index stage will work on, in caracole's order, as the Sync sheet lists them: each it takes
     * from the computer ([taken], newer "there") and each whose pages the phone's lookups read it gives ([noted],
     * newer "here"), a site of both twice, "there" first; each with the phone's newest read and the computer's. */
    private fun waiting(here: Map<String, String>, there: Map<String, String>, taken: List<String>,
                        noted: Set<String>): List<IndexWaiting> =
        Sites.ALL.flatMap { site ->
            val sides = listOfNotNull(THERE_SIDE.takeIf { site.name in taken }, HERE_SIDE.takeIf { site.name in noted })
            sides.map { side -> IndexWaiting(site.name, site.title, here[site.name], there[site.name], side) }
        }

    /** A file's comparison's indexes: each site whose newest read differs on the two sides, in caracole's order
     * (IndexTransfer's sites), with which is newer (sync_routes._waiting's rule; the import merges what the file read
     * more recently, record by record). */
    private fun differing(here: Map<String, String>, there: Map<String, String>): List<IndexWaiting> =
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
        SameCaracole("The scribe at $address is this one (same id, $me): its database is a copy of ours. " +
                     "Give one a new id: caracole peer new-id.")

    /** The take stage: a backup of the phone's database, then each unit of [toTake] taken from [source], each left
     * that changed on either side since the comparison; then, in the take's own write, what was taken recorded as
     * agreed by [agree] (the phone's units now, and each unit taken with its digest there: Compare.recordTaken with the
     * computer, SyncFiles.recordTaken with a file's caracole), [agreeTaken]. */
    private suspend fun take(source: UnitSource, stage: (String, String, String) -> Unit, done: Done,
                             toTake: List<Difference>,
                             agree: (Db, Map<String, SyncUnit>, Map<String, String?>) -> Unit): Applied {
        stage(TAKE, RUNNING, plural(toTake.size, "change"))
        val now = Stamps.of(clock())
        val wanted = toTake.map { it.id to it.theirs?.digest }
        val expectedHere = toTake.associate { it.id to it.mine?.digest }
        var seen = 0
        val applied = step(stage, TAKE, done) {
            io {
                database.write { db ->
                    Take.backupBeforeSync(db, stateDir, now, store)
                        ?: throw SyncFailed(NO_BACKUP, done.outcome())
                    // Each unit taken is the phone's as it is done (a savepoint of its own): recorded then, so that
                    // a take the database stops says what it took before.
                    val took = Take.applyUnits(db, store, source, wanted, expectedHere, now, checks) { id, what ->
                        if (what == "taken") done.taken.add(id)
                        seen++
                        stage(TAKE, RUNNING, "$seen of ${plural(toTake.size, "change")}")
                    }
                    agreeTaken(db, took, wanted, agree)
                    took
                }
            }
        }
        done.left.addAll(applied.left)
        stage(TAKE, DONE, "took ${applied.taken.size}" + if (applied.left.isEmpty()) "" else ", left ${applied.left.size}")
        return applied
    }

    /** What [applied] took (of [wanted]: each unit and its digest there as compared) recorded as agreed by [agree]
     * (of those the phone now holds so), as the take ends, so that whatever stops the sync or the import after it (the
     * give refused or cut off, the mirror stage or the job cancelled, the agree stage's own read) leaves it agreed
     * rather than a conflict once the other side changes it. A library that can't be read records nothing here, and
     * says nothing: the agree stage reads it again, and its failure is said there, failing the stage; the database's
     * own failure stops the take, as Take.applyUnits' does. */
    private fun agreeTaken(db: Db, applied: Applied, wanted: List<Pair<String, String?>>,
                           agree: (Db, Map<String, SyncUnit>, Map<String, String?>) -> Unit) {
        if (applied.taken.isEmpty()) return
        val mine = try {
            Units.libraryState(db)
        } catch (e: Exception) {
            if (Take.databaseFailed(e)) throw e
            return
        }
        val digests = wanted.toMap()
        agree(db, mine, applied.taken.associateWith { digests[it] })
    }

    /** The units the computer takes pushed (peer_push.push_units), in as many pushes as its limits ask
     * ([pushLimits], Give.cut), one at a time, each followed to its take's end before the next is opened: each unit
     * given, or left with why. A song with a kept file past 64 MiB is left out ([FileError.TOO_BIG], the export's
     * words for it), and so is a unit that alone passes what a push carries (Give.TOO_LONG, Give.TOO_HEAVY). A push
     * that fails stops the give there, its pushes before it taken (and agreed there as their takes ended), saying how
     * far it got; one that fails, or is cancelled, before its document is taken is let go of there first. A unit
     * whose digest here differs from the one compared is left ([CHANGED_HERE]), but for a song this sync's take
     * respelled ([respelled]: its digest as the take ended, in the take's own write), which is given as the take left
     * it: that change is the sync's own, and any other since still leaves it. */
    private suspend fun give(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, me: String,
                             fresh: Compared, toGive: List<Difference>, respelled: Map<String, String?>) {
        stage(GIVE, RUNNING, plural(toGive.size, "change"))
        val (state, documents) = database.read { db ->
            Units.libraryState(db) to toGive.associate { d -> d.id to Units.document(db, store.libraryDir, d.id) }
        }
        val before = done.left.size
        val givenBefore = done.given.size
        val entries = ArrayList<Give.Entry>()
        val sizes = HashMap<String, Long>()
        for (d in toGive) {
            val now = state[d.id]?.digest
            if (now != (if (d.id in respelled) respelled[d.id] else d.mine?.digest)) {
                done.left.add(d.id to CHANGED_HERE)
                continue
            }
            val entry = Give.Entry(d.id, expected = d.theirs?.digest, digest = now, unit = documents[d.id])
            val kept = Give.files(listOf(entry)).associateWith { sha -> io { Give.size(database, store.libraryDir, sha) } }
            if (kept.values.any { it > SyncFiles.FILE_MAX }) {
                done.left.add(d.id to FileError.TOO_BIG)
                continue
            }
            sizes.putAll(kept)
            entries.add(entry)
        }
        val at = fresh.peer.now ?: Stamps.of(clock())
        val token = fresh.peer.token
        val (pushes, tooMuch) = Give.cut(entries, sizes, pushLimits, me) { Give.document(me, name, version, at, state, it) }
        done.left.addAll(tooMuch)
        pushes.forEachIndexed { n, batch ->
            val which = if (pushes.size == 1) "" else "push ${n + 1} of ${pushes.size}: "
            val sent: List<Give.Entry>
            val ended: JsonObject
            var job: Int? = null
            var opened: String? = null  // the push opened there, until its document is taken
            try {
                val (push, need) = io { client.pushNew(token, me, Give.files(batch)) }
                opened = push
                val unreadable = HashSet<String>()
                need.forEachIndexed { i, sha ->
                    stage(GIVE, RUNNING, "$which${i + 1} of ${plural(need.size, "file")}")  // a count the bar fills by
                    val bytes = io { Give.read(database, store.libraryDir, sha) }
                    if (bytes == null) unreadable.add(sha) else io { client.pushFile(token, push, sha, bytes) }
                }
                sent = batch.filter { entry -> Give.files(listOf(entry)).none { it in unreadable } }
                for (entry in batch) if (entry !in sent) done.left.add(entry.id to FILE_CHANGED)
                job = io { client.push(token, push, Give.document(me, name, version, at, state, sent)) }
                stage(GIVE, RUNNING, "${which}the computer's Journal entry $job takes ${plural(sent.size, "change")}")
                ended = awaitJob(client, job)
            } catch (e: CancellationException) {
                // A push cancelled before its document was taken lets go of its slot there all the same.
                val dropping = opened
                if (dropping != null && job == null) withContext(NonCancellable) { io { client.pushDrop(token, dropping, me) } }
                throw e
            } catch (e: Exception) {
                // A push that failed before its document was taken lets go of its slot there at once
                // (peer_push.push_units); a drop that fails too says nothing over why the push failed.
                val dropping = opened
                if (dropping != null && job == null) io { client.pushDrop(token, dropping, me) }
                val far = if (n == 0) "" else "${done.given.size - givenBefore} given in the first " +
                    (if (n == 1) "push" else "$n pushes") + " of ${pushes.size}; then "
                // commands/peer.py's words (given_so_far, which Outcomes.GIVEN_SO_FAR reads to say the count once):
                // the whole give counted, and once a push was taken, that it stays so.
                val why = far + which + said(e) + (if (n == 0) "" else " $TAKEN_STAY")
                stage(GIVE, FAILED, why)
                throw SyncFailed("Couldn't give them ${toGive.size}: $why", done.outcome(), e)
            }
            val units = Give.units(ended)
            val jobState = Give.text(ended["state"])
            for (entry in sent) {
                val (outcome, why) = units[entry.id] ?: (null to "")
                if (outcome == "taken") {
                    done.given.add(entry.id)
                } else {
                    done.left.add(entry.id to why.ifEmpty {
                        if (jobState != "done") "their Journal entry $job: $jobState" else "not taken there"
                    })
                }
            }
        }
        val left = done.left.size - before
        stage(GIVE, DONE, "gave ${done.given.size - givenBefore}" + if (left == 0) "" else ", left $left")
    }

    /** The computer's request [id] followed, every [pollEveryMs], until it is over (peer_push.wait_for): how it ended.
     * A PeerError when it isn't over within [polls] asks (it goes on there all the same), saying what it hasn't
     * [done] yet. */
    private suspend fun awaitJob(client: PeerClient, id: Int, done: String = "taken the push"): JsonObject {
        repeat(polls) { asked ->
            val job = io { client.job(id) }
            when (Give.text(job["state"])) {
                "queued", "running" -> if (asked < polls - 1) delay(pollEveryMs)
                else -> return job
            }
        }
        throw PeerError("${client.address} hasn't $done yet: its Journal entry $id goes on.")
    }

    /** The computer's newer indexes merged, then the pages the phone's lookups read pushed, merged or not; each
     * part's failure said on the stage, leaving the rest as it is. Each site merged or given is counted for the
     * report, before and after. */
    private suspend fun index(client: PeerClient, stage: (String, String, String) -> Unit, done: Done, computer: String,
                              indexes: Map<String, String>, token: String) {
        val (had, merged, noted) = database.read { db ->
            Triple(IndexStamps.sites(db.kvGetJson(INDEX_KEY + computer)), MergedIndexes.of(db),
                   sendable(Reads.since(db, computer)))
        }
        val newer = newerThere(indexes, had, merged)
        if (newer.isEmpty() && noted.isEmpty()) {
            stage(INDEX, SKIPPED_STATE, NOTHING_TO_INDEX)
            return
        }
        stage(INDEX, RUNNING, if (newer.isEmpty()) sending(noted) else newer.joinToString(", "))
        val pacer = paced(stage, INDEX)
        val parts = ArrayList<String>()
        var failed = false
        if (newer.isNotEmpty()) {
            try {
                done.reported.addAll(merge(client, computer, had, newer, indexes, pacer, token))
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
                parts.add("${pagesRead(noted)} kept for the next share · ${said(e)}")
            }
        }
        stage(INDEX, if (failed) FAILED else DONE, parts.joinToString("; "))
    }

    /**
     * The computer's indexes of [newer] fetched into `stateDir/cache/` and merged, the kv's stamps and what the file
     * read (MergedIndexes) brought up to date, the WAL checkpointed; the file gone after, whatever came of it. The
     * report's entries of the sites the merge changed, each site's tabs counted before and after (TabCounts).
     *
     * Only the part the phone doesn't hold is asked for (`POST /peer/index/newer`, Have's document of [newer]: its
     * records of each sitemap, and kv [Have.CUT_KEY]'s time of the last export it merged from this computer); a
     * computer older than the route (404, 405), or one that refuses the document as too large (413), is asked for the
     * whole (`GET /api/peer/index`), any other refusal the stage's failure (a 400 is a bug, which must show). A partial
     * export is checked to be the part asked for once merged (its META's `partial`: Have.mismatch; no sitemap it left
     * out held otherwise, Merged.unheld), else a TransferError: its merge lost no row (a sitemap it left out is never
     * read as gone), and nothing is recorded as held, so the next sync asks again. Once it is (or the export is whole),
     * the phone holds every row the computer held as of the export, as a whole export's merge leaves it: kv
     * `sync:index:` and MergedIndexes move on.
     *
     * kv [Have.CUT_KEY] (the file's META `exported_at`, the computer's own clock) moves on only for a partial export of
     * the cut asked, and only when that time is no later than the merge's `notAfter`:
     * - a whole export comes from a computer older than the route, which notes no arrivals (`index:arrived`): rows it
     *   merges with old times before it is updated would fall below a cut taken from it, and never come; so the first
     *   partial export after its update is uncut, once;
     * - a row the merge passed over for being dated after `notAfter` is later than every time the file holds no later
     *   than it: with `exported_at` no later than `notAfter`, such a row is later than the cut too, and the next part
     *   sends it again; with `exported_at` past it (a computer's clock a day ahead), nothing is recorded.
     */
    private suspend fun merge(client: PeerClient, computer: String, had: Map<String, String>, newer: List<String>,
                              indexes: Map<String, String>, pacer: Paced, token: String): List<JsonObject> {
        val file = File(cache(), "index-${KeptById.newId()}.sqlite")
        try {
            pacer.say(COPYING_THERE)  // the computer exports them before it sends a byte
            val asked = database.read { Have.document(it, computer, newer) }
            val partial = io {
                val said = { got: Long, total: Long -> pacer.say(downloading(got, total), DOWNLOADING) }
                client.indexNewer(token, file, asked, said) || run { client.index(file, newer, said); false }
            }
            return io {
                val counted = database.write { db ->
                    val before = TabCounts.of(db)
                    // A site the phone holds rows of is updated: its words what is newer there and the rows checked.
                    val words = MergeProgress.Updating(before.filterValues { it > 0 }.keys)
                    val bound = notAfter()
                    val merged = namingFileAs(file, THE_COMPUTERS) {
                        IndexTransfer.merge(db, file, Stamps.of(clock()), newer, notAfter = bound,
                                            progress = { pacer.say(words.words(it), it.step) })
                    }
                    if (partial) {
                        val cut = merged.partial
                        val why = if (cut == null) "it says nothing of a part" else Have.mismatch(cut, asked)
                        val unheld = merged.unheld.entries.firstOrNull()?.let { (site, names) ->
                            "it left out $site's ${names.first()}, which the phone holds otherwise"
                        }
                        if (why != null || unheld != null) {
                            throw TransferError("$THE_COMPUTERS isn't the part asked for: ${why ?: unheld}. Nothing " +
                                                    "is noted as taken: the next sync asks again.")
                        }
                    }
                    db.kvSetJson(INDEX_KEY + computer, IndexStamps.json(had + newer.associateWith { indexes.getValue(it) }))
                    MergedIndexes.record(db, merged)
                    val exported = merged.exported
                    val cutAt = exported?.let {
                        try { Stamps.parse(it) } catch (_: ArithmeticException) { null }
                    }
                    if (partial && merged.partial != null && exported != null && cutAt != null && cutAt <= bound) {
                        Have.record(db, computer, newer, exported)
                    }
                    taken(merged, before, TabCounts.of(db), newer) { indexes[it] }
                }
                pacer.say(MergeProgress.TIDYING)
                database.checkpoint()  // the WAL a big merge grew, given back (lane prep-db)
                counted
            }
        } finally {
            file.delete()
        }
    }

    /**
     * The pages Reads noted since the last push to [computer], exported (IndexExport) in the write that reads them, so
     * that the file holds every page noted and those alone, and pushed (`POST /peer/index`), then the computer's
     * request that merges them (its `caracole index merge`) followed to its end; once it ends done, the notes forgotten
     * up to the newest of them, and what the phone holds of the computer's indexes moved on where those pages alone
     * moved the computer's stamp ([explained]: kv `sync:index:<computer id>`), so that the next sync never downloads a
     * site's whole index for the phone's own pages. What it did, in the stage's words; null when nothing is noted by
     * then. A PeerError (or mirror's SyncError) when the push fails, its request ends otherwise than done, or goes on
     * past the wait (the next push sends them again, a merge there taking the same rows), the notes kept; the file gone
     * after either way. Each site given is counted on the computer (`GET /api/sync/indexes`) before the push and after
     * its merge, for the report and the stamps; a computer that can't count them (one older than the app) gives no
     * count, the report none, and no stamp is moved.
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
            val them = if (pages.values.sumOf { it.size } == 1) "it" else "them"
            val before = io { counts(client) }
            val job = io { client.pushIndex(token, file) }
            val ended = Give.text(awaitJob(client, job, "merged $them")["state"])
            if (ended != "done") {
                throw PeerError("${client.address} didn't merge $them: its Journal entry $job ended $ended.")
            }
            val after = if (before == null) null else io { counts(client) }
            io {
                database.write { db ->
                    Reads.forget(db, computer, upTo)
                    if (before != null && after != null) {
                        val had = IndexStamps.sites(db.kvGetJson(INDEX_KEY + computer))
                        val held = explained(read, before, after, had, MergedIndexes.of(db))
                        if (held.isNotEmpty()) db.kvSetJson(INDEX_KEY + computer, IndexStamps.json(had + held))
                    }
                }
            }
            if (before != null && after != null) {
                for (site in Sites.ALL.map { it.name }.filter { it in pages }) {
                    val was = before[site] ?: continue
                    val now = after[site] ?: continue
                    done.reported.add(entry(site, GIVEN, was.tabs, now.tabs, read[site], checked = null))
                }
            }
            return "sent ${pagesRead(pages)} · its request $job merged $them"
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

    /**
     * The index files a sync works with in `stateDir/cache/` (a computer's index, a file's indexes copied out, the
     * phone's reads for a push, each deleted in its sync's `finally`), every one an earlier process left, killed in
     * its middle, deleted, with SQLite's journals beside them: called as the phone starts, while no sync runs. Each
     * is the size of a site's index (hundreds of MB), and nothing else looks for one.
     */
    fun sweep() {
        File(stateDir, "cache").listFiles()?.forEach { if (it.isFile && LEFT.matches(it.name)) it.delete() }
    }

    /** `stateDir/cache/`, made when missing; a PeerError in the phone's words when it can't be. */
    private fun cache(): File {
        val cache = File(stateDir, "cache")
        if (!cache.isDirectory && !cache.mkdirs()) throw PeerError("The phone's storage failed: can't make $cache.")
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

    /** [block], a merge of the index export at [file]; a refusal of it again in the owner's words, [name] ("The
     * computer's index export") where they say the file's path: a copy in the phone's cache, which tells the owner
     * nothing (CataloguesRunner says its catalogue's so). */
    private inline fun <T> namingFileAs(file: File, name: String, block: () -> T): T = try {
        block()
    } catch (e: TransferError) {
        throw TransferError(e.message.orEmpty().replace(file.path, name))
    }

    /** A failure in a stage's words: a refusal's own (a merge's among them, never its class's name), else what it
     * is and its message. */
    private fun said(e: Throwable): String = when (e) {
        is SyncError, is PeerError, is SyncFailed, is SameCaracole, is TransferError ->
            e.message ?: e.javaClass.simpleName
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
            COMPARE to "Comparing", TAKE to "Taking what they wrote", GIVE to "Giving what we wrote",
            MIRROR to "Copying the computer's pages", AGREE to "Noting where the books agree",
            INDEX to "Updating the indexes",
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
         * file), when, its parts, each index taken or given; and [skipped], why none went either way (the computer's
         * database of another schema, [indexesSkipped]'s words), `indexes_skipped`, only where it says one, as
         * commands/peer.py's report does. */
        fun report(name: String, kind: String, address: String?, at: String, parts: List<String>,
                   indexes: List<JsonObject>, skipped: String? = null): JsonObject = JsonObject(linkedMapOf(
            "with" to JsonObject(linkedMapOf("name" to JsonPrimitive(name), "kind" to JsonPrimitive(kind),
                                             "address" to JsonPrimitive(address))),
            "at" to JsonPrimitive(at),
            "parts" to JsonArray(parts.map(::JsonPrimitive)),
            "indexes" to JsonArray(indexes),
        ).apply { if (skipped != null) put("indexes_skipped", JsonPrimitive(skipped)) })

        /** One index of a report, commands/peer.py's alike: its site, its title, taken or given, its first table's rows
         * before and after, `new` the rows that side hadn't (after − before: a UG merge never deletes one; a site
         * whose sitemaps no longer list some, negative), `checked` the rows of the sitemaps and listing pages its merge
         * took, which it read (Merged.checked; null for a site given, which the computer's count doesn't say), and its
         * newest read. */
        fun entry(site: String, direction: String, before: Long, after: Long, read: String?, checked: Long?): JsonObject =
            JsonObject(linkedMapOf(
                "site" to JsonPrimitive(site), "title" to JsonPrimitive(Sites.named(site)?.title ?: site),
                "direction" to JsonPrimitive(direction), "before" to JsonPrimitive(before),
                "after" to JsonPrimitive(after), "new" to JsonPrimitive(after - before),
                "checked" to JsonPrimitive(checked), "read" to JsonPrimitive(read),
            ))

        /** A report's entries of the sites a merge changed (its rows, or its first table's count), in caracole's
         * order, each counted [before] and [after] the merge, [read] the site's newest read merged; a site whose
         * progress alone moved (no page taken, its count the same: a sitemap found unchanged) has none, as Python's
         * `_taken_entries`. */
        internal fun taken(merged: Merged, before: Map<String, Long>, after: Map<String, Long>, sites: List<String>,
                           read: (String) -> String?): List<JsonObject> =
            Sites.ALL.map { it.name }.filter { it in sites }.mapNotNull { site ->
                val was = before[site] ?: 0L
                val now = after[site] ?: 0L
                val changed = merged.changed && (merged.sites[site]?.values?.any { it != 0 } == true || was != now)
                if (changed) entry(site, TAKEN, was, now, read(site), merged.checked[site] ?: 0L) else null
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
            CHECK to "Reading the file", TAKE to "Taking what they wrote", MIRROR to "Keeping the file's pages",
            AGREE to "Noting where the books agree", INDEX to "Merging the indexes",
        )

        /** kv: a computer synced with, by its id: {address, name, synced_at}. */
        const val PEER_KEY = "sync:peer:"

        /** kv: the stamps of the computer's indexes the phone merged last, by its id: {site: stamp}. */
        const val INDEX_KEY = "sync:index:"

        /** The names of a sync's index files in `stateDir/cache/` ([sweep]), and their SQLite journals. */
        private val LEFT = Regex("(index|import-indexes|reads)-[0-9a-f]{16}\\.sqlite(-wal|-shm|-journal)?")

        /** The index stage's words as the computer exports its indexes (no byte sent yet), as they come ([downloading]),
         * and as a file's are copied out of it. */
        const val COPYING_THERE = "The computer is copying its indexes…"
        const val COPYING_OUT = "Copying the file's indexes out…"
        private const val DOWNLOADING = "downloading"

        /** What a merge's refusal calls the file it refused, in place of its copy's path ([namingFileAs]). */
        private const val THE_COMPUTERS = "The computer's index export"
        private const val THE_FILE = "The file"

        /** A step's [words] as a stage's running detail: one "…" at their end left off ("Tidying the database…",
         * the merge's "Making the search index ready…"), since a long stage's line puts its own after its detail
         * (Status.stageLine: "Updating the indexes · Tidying the database…"). The catalogues job's words keep theirs:
         * there the detail is the whole line. */
        fun detail(words: String): String = words.removeSuffix("…")

        /** "Downloading the computer's indexes · 120 of 274 MB"; with no total ([total] -1, an answer of no
         * Content-Length), the bytes so far alone: "· 3.4 MB so far". */
        fun downloading(got: Long, total: Long): String =
            "Downloading the computer's indexes · " + if (total >= 0) Sizes.of(got, total) else Sizes.soFar(got)

        /** The index stage's words with no index newer there and no page read here. */
        const val NOTHING_TO_INDEX = "no newer index there, no page read here to send"

        /** Why the index stage takes and gives none ([indexesSkipped]): the computer's database is of another schema,
         * whose index export the phone's merge refuses once downloaded whole, as the computer's refuses the phone's
         * pages. */
        const val INDEXES_NEWER = "The computer's indexes are of a newer caracole: update the app to take them"
        const val INDEXES_OLDER = "The computer's indexes are of an older caracole: update the computer to share them"

        /** Why a sync with a computer whose database is at [schema] (its state's, PeerState.schema) asks for no index
         * and gives none, before anything is downloaded ([INDEXES_NEWER], [INDEXES_OLDER]); null at the phone's schema,
         * or for a state that says none (a computer older than the member: asked as before, the merge refusing an
         * export of another schema in its words). sync_routes.indexes_skipped's rule, in the phone's words. */
        fun indexesSkipped(schema: Long?): String? = when {
            schema == null || schema == Database.SCHEMA_VERSION.toLong() -> null
            schema > Database.SCHEMA_VERSION -> INDEXES_NEWER
            else -> INDEXES_OLDER
        }

        /** "3 pages read here", of Reads.since's pages. */
        fun pagesRead(pages: Map<String, List<String>>): String = plural(pages.values.sumOf { it.size }, "page") + " read here"

        private fun sending(pages: Map<String, List<String>>) = "sending ${pagesRead(pages)}"

        /** Those of Reads' [pages] an export holds (IndexExport.PAGES' sites): a note of another site's, which no
         * site lane makes, never stops the rest from going. */
        private fun sendable(pages: Map<String, List<String>>) = pages.filterKeys { it in IndexExport.PAGES }

        /**
         * The computer's sites the index stage takes, in caracole's order, and those its comparison says are newer
         * there: each of [indexes] (the computer's newest reads, its state's) that the phone knows whose stamp is later
         * than both what the phone took of that computer last ([had], kv `sync:index:<computer id>`) and the newest
         * read of the whole exports it merged ([merged], MergedIndexes: the catalogues, a file's indexes, an index
         * imported, a sync's own), a record with no stamp for the site no bound. Never the phone's own newest, which
         * its lookups' reads move.
         */
        private fun newerThere(indexes: Map<String, String>, had: Map<String, String>,
                               merged: Map<String, String>): List<String> =
            indexes.filter { (site, stamp) ->
                Sites.named(site) != null && listOfNotNull(had[site], merged[site]).all { IndexStamps.newer(stamp, it) }
            }.keys.sortedBy { site -> Sites.ALL.indexOfFirst { it.name == site } }

        /**
         * The computer's stamps that the pages the phone pushed alone explain, once its merge of them is done: for kv
         * `sync:index:<computer id>`, each site of [read] (the newest page pushed of it) whose stamp there now
         * ([after], `GET /api/sync/indexes`) is a time no later than that page and later than [had]'s, and whose stamp
         * just before the push ([before]) was one the phone held ([newerThere]'s rule, against [had] and [merged];
         * none: it had no index of that site). So the computer read nothing of that site that the phone lacks. A stamp
         * later than the pages, or a site the phone lacked news of before the push (its download failed), is the
         * computer's own, which the next sync takes.
         */
        private fun explained(read: Map<String, String?>, before: Map<String, IndexCount>,
                              after: Map<String, IndexCount>, had: Map<String, String>,
                              merged: Map<String, String>): Map<String, String> =
            read.mapNotNull { (site, pushed) ->
                val now = after[site]?.read ?: return@mapNotNull null
                if (pushed == null || !IndexStamps.noLater(now, pushed)) return@mapNotNull null
                if (had[site]?.let { IndexStamps.newer(now, it) } == false) return@mapNotNull null
                val was = before[site]?.read
                if (was != null && newerThere(mapOf(site to was), had, merged).isNotEmpty()) return@mapNotNull null
                site to now
            }.toMap()

        /** The phone's library's name, and its caracole's version, as its push names them unless it is given others. */
        const val PHONE_NAME = "Phone"
        const val CARACOLE = "0.1.0"

        const val KEPT_SECONDS = 600L
        const val POLL_EVERY_MS = 1_000L
        const val POLLS = 600

        /** Why a unit is left, in commands/peer.py's and peer_sync.py's words. */
        const val SKIPPED = "skipped, as you chose"
        const val UNSETTLED = "both books changed it: choose one"
        const val CHANGED_HERE = "changed here since compared"
        const val FILE_CHANGED = "a file it keeps changed here since we kept it"

        /** A give that stopped after some of its pushes were taken: what the owner may count on (commands/peer.py's
         * TAKEN_STAY). */
        const val TAKEN_STAY = "The pushes taken there stay taken; the next sync gives the rest."

        /** sync_routes.STALE (and commands/peer.py's): the two changed since the comparison. */
        const val STALE = "Both books changed since that comparison. Compare again, then choose again."
        const val NO_BACKUP = "Nothing taken: no backup first (not enough room)."

        /** sync_routes.apply's refusal of a conflict settled neither way. */
        fun unsettled(n: Int) = "Choose a book for every conflict: $n ${if (n == 1) "has" else "have"} none."

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
