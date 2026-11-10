package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TabCounts
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.Conflicts
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.PeerState
import io.github.danielhp95.caracole.core.sync.SameCaracole
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import io.github.danielhp95.caracole.mirror.SyncError
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.SyncJson
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** The computer's address the Sync tab syncs with, kept by the app. */
interface SyncSettings {
    val address: String?
    fun remember(address: String)
}

/**
 * The Sync tab's routes on the phone, answering as caracole serve's sync_routes.py answers, in its words and with its
 * shapes (library_assets/sync.js reads them on both sides; the sync redesign's §3.4.1;
 * tests/conformance/vectors/web/sync_routes.jsonl):
 *
 *     GET  /api/sync          this phone's id, its library's name ([name]), its device ("phone": the computer's says
 *                             "computer"), the address it compared with last ([settings], else the computer it synced
 *                             with last), the computers it synced with before (kv sync:peer:<id>), the last first,
 *                             and its songs and songbooks counted
 *     POST /sync/test         the computer at `address` asked what it holds, changing nothing ([tested]): its songs,
 *                             songbooks, the newest read of its indexes, when the phone last synced with it, and that
 *                             in words (`said`); refused as a comparison is
 *     POST /sync/compare      the phone and the caracole at `address` (peer_sync.peer_address's reading) compared
 *                             (SyncEngine.compare, with the answers an import remembered), the address remembered:
 *                             the comparison's id, the other side (`kind` "computer"), when the two last agreed
 *                             (`synced_before`, null: never), the parts it holds, each difference (its kind, proposal,
 *                             why, each side's digest, a song's names, each side's change since the two agreed, its
 *                             part and the songbooks that list it), each songbook difference's two documents, and the
 *                             indexes newer on either side; the comparison kept 10 minutes
 *     GET  /api/sync/unit?comparison=&id=   a unit of a comparison kept, its two documents (`here`, the phone's now;
 *                             `there`, the computer's, asked of it now; null where a side hasn't got it): the page's
 *                             script alone asks it
 *     GET  /api/sync/indexes  each site's index here: its newest read and the tabs it tracks (IndexTransfer.newest,
 *                             TabCounts)
 *     POST /sync/apply        a comparison kept, synced as the owner chose (`choices`, a line each,
 *                             `<here|there|skip>\t<unit id>`; `prefer`: here, there, or "" for none) within its parts
 *                             (`parts`: library, songbooks, indexes by commas; none sent, all three): a job (kind
 *                             `sync`, key `sync:<address>`; its stages compare, take, give, mirror, agree, index), its
 *                             view the answer
 *
 * Refused as sync_routes.py refuses: an address that isn't one, 400; a computer that can't be asked, 502; this very
 * phone's database copied, 409; a comparison more than 10 minutes old or never made here, 409; a unit it didn't find,
 * 404; a `prefer`, a part or a choice that can't be read, 400; a conflict of the parts synced with neither a choice nor
 * `prefer`, 409; the two changed since the comparison, which Sync compares afresh to tell before anything is queued,
 * 409; a sync with that computer that waits or runs already, 409. The job runs SyncEngine.apply, sets its view's
 * outcome (what was taken, given and left, what the two agree on, the indexes merged, the sync's report; on a failure,
 * what it did until then), then [afterSync] (the search cache, the page's data).
 *
 * [alone] queues the unattended sync (Sync on Wi-Fi by itself): the three parts, each one-sided change taken or
 * given, each conflict left (Conflicts.LEAVE). A day is said in [zone]'s (the phone's; the corpus's replay, UTC's).
 */
class SyncRoutes(val engine: SyncEngine, val queue: JobQueue, val settings: SyncSettings, val database: Database,
                 val afterSync: () -> Unit, val name: String = AppConfig.PHONE,
                 val zone: () -> ZoneId = { ZoneId.systemDefault() }) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/sync", "this phone's sync and the computers it synced with", get = GetAnswer { state() }),
        Route("POST", "/sync/test", "ask the computer what it holds, changing nothing",
              post = PostAnswer { _, form -> Answers.json(tested(address(form))) }),
        Route("POST", "/sync/compare", "compare with the computer", post = PostAnswer { _, form -> compare(form) }),
        Route("GET", "/api/sync/unit", "a compared unit's two documents", scriptOnly = true,
              get = GetAnswer { request -> unit(PyUrl.query(request.target)) }),
        Route("GET", "/api/sync/indexes", "each site's index here: its newest read and its tabs",
              get = GetAnswer { indexes() }),
        Route("POST", "/sync/apply", "take and give what a comparison found", limit = APPLY_LIMIT,
              post = PostAnswer { _, form -> apply(form) }),
    )

    private fun state(): Response {
        val read = database.read { db ->
            State(Compare.ownId(db), SyncJson.peers(db), db.one("SELECT COUNT(*) FROM songs") { it.long(0)!! }!!,
                  db.one("SELECT COUNT(*) FROM phone_songbooks") { it.long(0)!! }!!)
        }
        val last = (read.peers.firstOrNull() as? JsonObject)?.get("address")
        return Answers.json(JsonObject(linkedMapOf(
            "server" to JsonPrimitive(read.server), "name" to JsonPrimitive(name), "device" to JsonPrimitive(DEVICE),
            "address" to (settings.address?.let(::JsonPrimitive) ?: last ?: JsonNull),
            "peers" to read.peers, "songs" to JsonPrimitive(read.songs), "songbooks" to JsonPrimitive(read.songbooks),
        )))
    }

    private class State(val server: String, val peers: kotlinx.serialization.json.JsonArray, val songs: Long,
                        val songbooks: Long)

    /** sync_routes._address: the computer's address the form names, as peer_sync.peer_address reads it; 400 else. */
    private fun address(form: Map<String, String>): String = try {
        SyncEngine.peerAddress(form["address"].orEmpty())
    } catch (e: PeerError) {
        throw Refused(400, "Not an address", e.message ?: "That isn't an address.")
    }

    /**
     * What `POST /sync/test` answers of the computer at [address] (a peerAddress), for Settings' Test too
     * (sync_routes.test): its state asked once and nothing written, `{peer: {address, server, caracole, name}, songs,
     * songbooks, indexes, synced_at, said}`, its song and songbook units counted, `indexes` the newest read of its
     * indexes that is a time (null: none), `synced_at` when the phone last synced with it (null: never), and `said`
     * all that in words ([testedWords]). Refused (a [Refused]) as a comparison is: 502 for nothing answering, 409 for
     * this very phone.
     */
    fun tested(address: String): JsonObject {
        val me = database.read { Compare.ownId(it) }
        val state = asking { engine.client(address).state(me) }
        notThisOne(address, me, state)
        val syncedAt = state.server?.let { server -> database.read { db -> SyncJson.syncedAt(db, server) } }
        val songs = state.units.keys.count { it.startsWith("song/") }
        val songbooks = state.units.keys.count { it.startsWith("songbook/") }
        val newest = newestRead(state.indexes)
        return JsonObject(linkedMapOf(
            "peer" to JsonObject(linkedMapOf(
                "address" to JsonPrimitive(address), "server" to JsonPrimitive(state.server),
                "caracole" to JsonPrimitive(state.caracole), "name" to JsonPrimitive(state.name),
            )),
            "songs" to JsonPrimitive(songs), "songbooks" to JsonPrimitive(songbooks),
            "indexes" to JsonPrimitive(newest), "synced_at" to JsonPrimitive(syncedAt),
            "said" to JsonPrimitive(testedWords(Py.strip(state.name).ifEmpty { address }, songs, songbooks, newest)),
        ))
    }

    /** sync_routes.tested_words: "Studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26" (the day in
     * [zone]'s), or ", no indexes" for a computer that read none. */
    fun testedWords(name: String, songs: Int, songbooks: Int, indexesAt: String?): String {
        val read = indexesAt?.let(::time)?.let { ", its indexes read ${DAY.format(Stamps.instant(it).atZone(zone()))}" }
            ?: ", no indexes"
        return "$name answered: ${counted(songs, "song")}, ${counted(songbooks, "songbook")}$read"
    }

    private fun compare(form: Map<String, String>): Response {
        val address = address(form)
        settings.remember(address)
        return Answers.json(SyncJson.comparison(asking { engine.compare(address) }))
    }

    /** `GET /api/sync/unit` (sync_routes.unit_documents): a unit of a comparison kept, its two documents; 409 for a
     * comparison past, 404 for a unit it didn't find, 502 for the computer not answering. */
    private fun unit(params: Map<String, String>): Response {
        val made = Py.strip(params["comparison"].orEmpty())
        val kept = (if (made.isNotEmpty()) engine.comparison(made) else null) ?: throw Refused(409, "Compare again", GONE)
        val unitId = params["id"].orEmpty()
        if (kept.differences.none { it.id == unitId }) {
            throw Refused(404, "Not compared", "${PyStr.repr(Py.slice(unitId, null, 200))} isn't one that comparison " +
                                               "found: it is no unit the two hold differently.")
        }
        val (here, there) = asking { engine.documents(kept, unitId) }
        return Answers.json(JsonObject(linkedMapOf(
            "id" to JsonPrimitive(unitId), "here" to (here ?: JsonNull), "there" to (there ?: JsonNull),
        )))
    }

    /** `GET /api/sync/indexes` (sync_routes.indexes): every site, its newest read (null: never) and its tabs. */
    private fun indexes(): Response {
        val (newest, counts) = database.read { db -> IndexTransfer.newest(db) to TabCounts.of(db) }
        return Answers.json(JsonObject(mapOf("indexes" to JsonObject(counts.entries.associateTo(LinkedHashMap()) { (site, tabs) ->
            site to JsonObject(linkedMapOf("read" to JsonPrimitive(newest[site]), "tabs" to JsonPrimitive(tabs)))
        }))))
    }

    private fun apply(form: Map<String, String>): Response {
        val made = Py.strip(form["comparison"].orEmpty())
        val kept = (if (made.isNotEmpty()) engine.comparison(made) else null) ?: throw Refused(409, "Compare again", GONE)
        val prefer = when (Py.strip(form["prefer"].orEmpty())) {
            "" -> null
            "here" -> Side.HERE
            "there" -> Side.THERE
            else -> throw Refused(400, "Not a side", "prefer is here, there, or nothing.")
        }
        val parts = partsOf(form)
        val choices = choicesOf(form["choices"].orEmpty(), kept)
        val open = Scope.inScope(kept.differences, parts ?: Scope.PARTS, kept.listed)
            .count { it.proposal == CONFLICT && it.id !in choices }
        if (open > 0 && prefer == null) throw Refused(409, "Choose first", SyncEngine.unsettled(open))
        // Afresh: refused now, before anything is queued, once the two are past the comparison.
        if (!asking { engine.stillAsCompared(kept) }) {
            engine.forget(made)
            throw Refused(409, "Compare again", SyncEngine.STALE)
        }
        val shown = "Sync with ${Py.slice(Py.strip(kept.peer.name).ifEmpty { kept.address }, null, 120)}"
        val (job, new) = queue.submitOrRefuse(syncJob(shown, kept.address) { stage ->
            engine.apply(kept, choices, prefer, parts ?: Scope.PARTS, Conflicts.ASK, stage)
        })
        if (!new) {
            throw Refused(409, "Syncing already", "A sync with ${kept.address} is on its way already (request " +
                                                  "${job.id}): compare again once it is over.")
        }
        engine.forget(made)
        return Answers.queued(JobViews.view(job, queue), "/#tab=sync")
    }

    /**
     * The unattended sync with the computer at [address] (a peerAddress), queued: compared within its job, then
     * applied over the three parts with no choice and no preference, so each one-sided change is taken or given and
     * each conflict left as it is on both sides (Conflicts.LEAVE: never refused, never settled); its outcome's
     * `left` names each conflict left ([SyncEngine.UNSETTLED]). Null, queueing nothing, when a sync with that
     * address waits or runs already. A computer that can't be asked fails the job's compare stage, in its words.
     */
    fun alone(address: String): Job? {
        val known = database.read { db -> SyncJson.peers(db) }.mapNotNull { it as? JsonObject }
            .firstOrNull { (it["address"] as? JsonPrimitive)?.contentOrNull == address }
        val named = (known?.get("name") as? JsonPrimitive)?.contentOrNull?.let(Py::strip).orEmpty()
        val shown = "Sync with ${Py.slice(named.ifEmpty { address }, null, 120)}"
        val (job, new) = queue.submitOrRefuse(syncJob(shown, address) { stage ->
            val c = try {
                engine.compare(address)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                val why = e.message ?: e.javaClass.simpleName
                stage(SyncEngine.COMPARE, FAILED, why)
                throw SyncFailed(why, null, e)
            }
            try {
                engine.apply(c, emptyMap(), null, Scope.PARTS, Conflicts.LEAVE, stage)
            } finally {
                engine.forget(c.id)
            }
        })
        return if (new) job else null
    }

    /** A sync's job (kind `sync`, under `sync:<address>`, SyncEngine's stages): [sync] run with the stages told to
     * the job; its outcome the view's, or on a failure what it did until then, the stages after the one that failed
     * skipped, as the computer's queue ends them; [afterSync] whatever came of it. */
    private fun syncJob(shown: String, address: String,
                        sync: suspend (stage: (String, String, String) -> Unit) -> SyncOutcome): JobSpec = JobSpec(
        title = shown, key = SYNCING + address, kind = "sync", stages = SyncEngine.STAGES, display = shown,
        run = { context: JobContext ->
            val told = HashSet<String>()
            try {
                val outcome = sync { stage, state, detail ->
                    told.add(stage)
                    context.stage(stage, state, detail)
                }
                context.outcome(SyncJson.outcome(outcome))
            } catch (e: SyncFailed) {
                e.outcome?.let { context.outcome(SyncJson.outcome(it)) }
                for ((stage, _) in SyncEngine.STAGES) if (stage !in told) context.stage(stage, "skipped")
                throw e
            } finally {
                afterSync()
            }
        },
    )

    /** [ask], the computer asked: refused as sync_routes._compared refuses (502 when it can't be asked, 409 when it is
     * this very phone). */
    private fun <T> asking(ask: () -> T): T = try {
        ask()
    } catch (e: SameCaracole) {
        throw Refused(409, "The same caracole", e.message ?: "")
    } catch (e: SyncError.BadAddress) {
        throw Refused(400, "Not an address", e.message ?: "")
    } catch (e: PeerError) {
        throw Refused(502, "Not reached", e.message ?: "")
    } catch (e: SyncError) {
        throw Refused(502, "Not reached", e.message ?: "")
    }

    /** sync_routes._not_this_one: refused (409) when the caracole at [address] is this very phone, its database a
     * copy of the phone's. */
    private fun notThisOne(address: String, me: String, state: PeerState) {
        if (me == state.server) {
            throw Refused(409, "The same caracole", "The caracole at $address is this one (the same id, $me): its " +
                                                    "database is a copy of this one's. Give one of them another: " +
                                                    "caracole peer new-id.")
        }
    }

    /** sync_routes.choices_of: the owner's choices, a line each (`<here|there|skip>\t<unit id>`, a blank line left
     * out), each unit's side; refused (400) for a line that isn't one, a unit the comparison didn't find, or one
     * chosen two ways. */
    private fun choicesOf(text: String, c: Comparison): Map<String, Side> {
        val ids = c.differences.map { it.id }.toSet()
        val found = LinkedHashMap<String, Side>()
        for (line in PyStr.splitlines(text)) {
            if (Py.strip(line).isEmpty()) continue
            val tab = line.indexOf('\t')
            val side = if (tab < 0) null else SIDES[line.substring(0, tab)]
            val unit = if (tab < 0) "" else line.substring(tab + 1)
            if (side == null || unit !in ids) {
                throw Refused(400, "Not a choice", "${PyStr.repr(Py.slice(line, null, 200))} isn't a choice of this " +
                                                   "comparison's: here, there or skip, a tab, then one of its units.")
            }
            if ((found[unit] ?: side) != side) {
                throw Refused(400, "Not a choice", "${Py.slice(unit, null, 200)} is chosen two ways.")
            }
            found[unit] = side
        }
        return found
    }

    companion object {
        /** POST /sync/apply's form at most: a line a difference, for a library's every unit. */
        const val APPLY_LIMIT = 1_048_576

        /** A sync's job key: the address after it, so a second sync with the computer is refused while one waits or
         * runs (sync_routes.SYNCING). */
        const val SYNCING = "sync:"

        /** What this caracole is, as GET /api/sync says it (sync_routes.DEVICE: the computer's says "computer"). */
        const val DEVICE = "phone"

        /** sync_routes.GONE: a comparison no longer kept. */
        const val GONE = "That comparison is more than 10 minutes old, or caracole serve has restarted since: " +
            "compare the two again."

        /** sync_routes.NOT_A_PART: `parts` that isn't the parts' names (caracole peer sync --parts' words). */
        const val NOT_A_PART = "parts are library, songbooks or indexes, by commas."

        /** sync_routes.parts_of: the parts a Sync is of (`parts`: library, songbooks, indexes by commas), in
         * Scope.PARTS' order; null when the form sends none (all three). Refused (400) for none named, or one that
         * isn't a part. */
        fun partsOf(form: Map<String, String>): List<String>? {
            val text = form["parts"] ?: return null
            val named = text.split(",").map(Py::strip).filter { it.isNotEmpty() }
            if (named.isEmpty() || named.any { it !in Scope.PARTS }) throw Refused(400, "Not a part", NOT_A_PART)
            return Scope.PARTS.filter { it in named }
        }

        /** sync_routes.newest_read: the newest of a state's index reads, as it gives it; one that isn't a time left
         * out, null for none. */
        fun newestRead(indexes: Map<String, String>): String? =
            indexes.values.mapNotNull { text -> time(text)?.let { it to text } }
                .maxWithOrNull(compareBy<Pair<Long, String>> { it.first }.then { a, b -> Py.CODE_POINT_ORDER.compare(a.second, b.second) })
                ?.second

        /** stamps.parse: [text]'s instant, null for none (or one outside the years a time can be in). */
        private fun time(text: String): Long? = try {
            Stamps.parse(text)
        } catch (_: ArithmeticException) {
            null
        }

        private fun counted(n: Int, noun: String) = if (n == 1) "$n $noun" else "$n ${noun}s"

        private val DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("dd/MM/yy")
        private const val CONFLICT = "conflict"
        private const val FAILED = "failed"
        private val SIDES = mapOf("here" to Side.HERE, "there" to Side.THERE, "skip" to Side.SKIP)
    }
}
