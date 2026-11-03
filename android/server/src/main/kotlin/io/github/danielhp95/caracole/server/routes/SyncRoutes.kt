package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.SameCaracole
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.mirror.SyncError
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.PyStr
import io.github.danielhp95.caracole.server.routes.library.SyncJson
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** The computer's address the Sync tab syncs with, kept by the app. */
interface SyncSettings {
    val address: String?
    fun remember(address: String)
}

/**
 * The Sync tab's routes on the phone, answering as caracole serve's sync_routes.py answers, in its words and with its
 * shapes (library_assets/sync.js reads them on both sides; tests/conformance/vectors/web/sync_routes.jsonl):
 *
 *     GET  /api/sync       this phone's id, its library's name ([name]), the address it compared with last
 *                          ([settings], else the computer it synced with last), and the computers it synced with
 *                          before (kv sync:peer:<id>), the last first
 *     POST /sync/compare   the phone and the caracole at `address` (peer_sync.peer_address's reading) compared
 *                          (SyncEngine.compare), the address remembered: the comparison's id, the other side, when the
 *                          two last agreed (`synced_before`, null: never), and each difference, its kind, proposal, why
 *                          and each side's digest; the comparison kept 10 minutes
 *     POST /sync/apply     a comparison kept, synced as the owner chose (`choices`, a line each,
 *                          `<here|there|skip>\t<unit id>`; `prefer`: here, there, or "" for none): a job (kind `sync`,
 *                          key `sync:<address>`; its stages compare, take, give, mirror, agree, index), its view the
 *                          answer
 *
 * Refused as sync_routes.py refuses: an address that isn't one, 400; a computer that can't be asked, 502; this very
 * phone's database copied, 409; a comparison more than 10 minutes old or never made here, 409; a `prefer` or a choice
 * that can't be read, 400; a conflict with neither a choice nor `prefer`, 409; the two changed since the comparison,
 * which Sync compares afresh to tell before anything is queued, 409; a sync with that computer that waits or runs
 * already, 409. The job runs SyncEngine.apply, sets its view's outcome (what was taken, given and left, what the two
 * agree on, the indexes merged; on a failure, what it did until then), then [afterSync] (the search cache, the page's
 * data).
 */
class SyncRoutes(val engine: SyncEngine, val queue: JobQueue, val settings: SyncSettings, val database: Database,
                 val afterSync: () -> Unit, val name: String = AppConfig.PHONE) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/sync", "this phone's sync and the computers it synced with", get = GetAnswer { state() }),
        Route("POST", "/sync/compare", "compare with the computer", post = PostAnswer { _, form -> compare(form) }),
        Route("POST", "/sync/apply", "take and give what a comparison found", limit = APPLY_LIMIT,
              post = PostAnswer { _, form -> apply(form) }),
    )

    private fun state(): Response {
        val (server, peers) = database.read { db -> Compare.ownId(db) to SyncJson.peers(db) }
        val last = (peers.firstOrNull() as? JsonObject)?.get("address")
        return Answers.json(JsonObject(linkedMapOf(
            "server" to JsonPrimitive(server), "name" to JsonPrimitive(name),
            "address" to (settings.address?.let(::JsonPrimitive) ?: last ?: JsonNull),
            "peers" to peers,
        )))
    }

    private fun compare(form: Map<String, String>): Response {
        val address = try {
            SyncEngine.peerAddress(form["address"].orEmpty())
        } catch (e: PeerError) {
            throw Refused(400, "Not an address", e.message ?: "That isn't an address.")
        }
        settings.remember(address)
        return Answers.json(SyncJson.comparison(asking { engine.compare(address) }))
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
        val choices = choicesOf(form["choices"].orEmpty(), kept)
        val open = kept.differences.count { it.proposal == CONFLICT && it.id !in choices }
        if (open > 0 && prefer == null) throw Refused(409, "Choose first", SyncEngine.unsettled(open))
        // Afresh: refused now, before anything is queued, once the two are past the comparison.
        if (!asking { engine.stillAsCompared(kept) }) {
            engine.forget(made)
            throw Refused(409, "Compare again", SyncEngine.STALE)
        }
        val shown = "Sync with ${Py.slice(Py.strip(kept.peer.name).ifEmpty { kept.address }, null, 120)}"
        val (job, new) = queue.submitOrRefuse(JobSpec(
            title = shown, key = SYNCING + kept.address, kind = "sync", stages = SyncEngine.STAGES, display = shown,
            run = { context ->
                val told = HashSet<String>()
                try {
                    val outcome = engine.apply(kept, choices, prefer) { stage, state, detail ->
                        told.add(stage)
                        context.stage(stage, state, detail)
                    }
                    context.outcome(SyncJson.outcome(outcome))
                } catch (e: SyncFailed) {
                    e.outcome?.let { context.outcome(SyncJson.outcome(it)) }
                    // The stages after the one that failed never ran: skipped, as the computer's queue ends them.
                    for ((stage, _) in SyncEngine.STAGES) if (stage !in told) context.stage(stage, "skipped")
                    throw e
                } finally {
                    afterSync()
                }
            },
        ))
        if (!new) {
            throw Refused(409, "Syncing already", "A sync with ${kept.address} is on its way already (request " +
                                                  "${job.id}): compare again once it is over.")
        }
        engine.forget(made)
        return Answers.queued(JobViews.view(job, queue), "/#tab=sync")
    }

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

        /** sync_routes.GONE: a comparison no longer kept. */
        const val GONE = "That comparison is more than 10 minutes old, or caracole serve has restarted since: " +
            "compare the two again."

        private const val CONFLICT = "conflict"
        private val SIDES = mapOf("here" to Side.HERE, "there" to Side.THERE, "skip" to Side.SKIP)
    }
}
