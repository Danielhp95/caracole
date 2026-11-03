package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.mirror.ServerAddress
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
import io.github.danielhp95.caracole.server.routes.library.SyncJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** The computer's address the Sync tab syncs with, kept by the app. */
interface SyncSettings {
    val address: String?
    fun remember(address: String)
}

/**
 * The Sync tab's routes on the phone, answering the shapes caracole serve's sync_routes.py answers (the plan's §5.3;
 * library_assets/sync.js reads them on both sides):
 *
 *     GET  /api/sync       this phone's id, its library's name, the address it synced with last ([settings]), and the
 *                          computers it synced with before (kv sync:peer:<id>), the last first
 *     POST /sync/compare   the phone and the computer at `address` compared (SyncEngine.compare), the address
 *                          remembered: the comparison's id, the other side, whether the two synced before, and each
 *                          difference, its kind, proposal, why and each side's digest; the comparison kept 10 minutes
 *     POST /sync/apply     a comparison kept applied as a job (kind `sync`, key `sync:<address>`; its stages compare,
 *                          take, give, mirror, agree, index): `prefer` ("", here or there) and `choices`, a line each,
 *                          `<here|there|skip>\t<unit id>`, for the conflicts and the proposals flipped
 *
 * Refused, 409, for a comparison over (older than 10 minutes, or never made here), a conflict with neither a choice
 * nor `prefer`, and a computer that can't be compared with; 400 for an address or a choice that can't be read. The
 * job runs SyncEngine.apply, sets its view's outcome (what was taken, given and left, what the two agree on, the
 * indexes merged; on a failure, what it did until then), then [afterSync] (the search cache, the page's data).
 */
class SyncRoutes(val engine: SyncEngine, val queue: JobQueue, val settings: SyncSettings, val database: Database,
                 val afterSync: () -> Unit) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/sync", "this phone's sync and the computers it synced with", get = GetAnswer { state() }),
        Route("POST", "/sync/compare", "compare with the computer", post = PostAnswer { _, form -> compare(form) }),
        Route("POST", "/sync/apply", "take and give what a comparison found", limit = APPLY_LIMIT,
              post = PostAnswer { _, form -> apply(form) }),
    )

    private fun state(): Response {
        val (server, peers) = database.read { db -> Compare.ownId(db) to SyncJson.peers(db) }
        return Answers.json(JsonObject(linkedMapOf(
            "server" to JsonPrimitive(server), "name" to JsonPrimitive(AppConfig.PHONE),
            "address" to (settings.address?.let(::JsonPrimitive) ?: kotlinx.serialization.json.JsonNull),
            "peers" to peers,
        )))
    }

    private fun compare(form: Map<String, String>): Response {
        val address = try {
            ServerAddress.parse(form["address"].orEmpty()).toString()
        } catch (e: SyncError) {
            throw Refused(400, "Not an address", e.message ?: "That isn't an address the phone can ask.")
        }
        settings.remember(address)
        val comparison = try {
            engine.compare(address)
        } catch (e: PeerError) {
            throw Refused(409, "Not compared", e.message ?: "The computer couldn't be compared with.")
        } catch (e: SyncError) {
            throw Refused(409, "Not compared", e.message ?: "The computer couldn't be compared with.")
        }
        return Answers.json(SyncJson.comparison(comparison))
    }

    private fun apply(form: Map<String, String>): Response {
        val comparison = engine.comparison(form["comparison"].orEmpty())
            ?: throw Refused(409, "Compare again", "That comparison is over (one lasts 10 minutes): compare again.")
        val prefer = when (form["prefer"].orEmpty()) {
            "" -> null
            "here" -> Side.HERE
            "there" -> Side.THERE
            else -> throw Refused(400, "Not a side", "Which side? prefer is here, there, or nothing.")
        }
        val choices = choices(form["choices"].orEmpty(), comparison)
        val unsettled = comparison.differences.count { it.proposal == CONFLICT && choices[it.id] == null && prefer == null }
        if (unsettled > 0) {
            throw Refused(409, "Choose first", "Choose a side for every conflict first: " +
                                               "$unsettled ${if (unsettled == 1) "conflict has" else "conflicts have"} none.")
        }
        val name = comparison.peer.name.ifEmpty { comparison.address }
        val (job, _) = queue.submit(JobSpec(
            title = "Sync with $name", key = SYNC_KEY + comparison.address, kind = "sync", stages = SyncEngine.STAGES,
            display = "Sync with $name",
            run = { context ->
                try {
                    val outcome = engine.apply(comparison, choices, prefer) { stage, state, detail ->
                        context.stage(stage, state, detail)
                    }
                    context.outcome(SyncJson.outcome(outcome))
                } catch (e: SyncFailed) {
                    e.outcome?.let { context.outcome(SyncJson.outcome(it)) }
                    throw e
                } finally {
                    afterSync()
                }
            },
        ))
        return Answers.queued(JobViews.view(job, queue))
    }

    /** The choices posted, a line each, `<here|there|skip>\t<unit id>`, each of a difference of [c]. */
    private fun choices(text: String, c: Comparison): Map<String, Side> {
        val ids = c.differences.map { it.id }.toSet()
        val chosen = LinkedHashMap<String, Side>()
        for (line in text.split('\n').map { it.removeSuffix("\r") }.filter { it.isNotEmpty() }) {
            val side = SIDES[line.substringBefore('\t', "")]
            val id = line.substringAfter('\t', "")
            if (side == null || id !in ids) {
                throw Refused(400, "Not a choice", "A choice is here, there or skip, then a tab and a unit the " +
                                                   "comparison found: '${line.take(200)}' isn't one.")
            }
            chosen[id] = side
        }
        return chosen
    }

    companion object {
        /** POST /sync/apply's form at most: a line a difference, for a library's every unit. */
        const val APPLY_LIMIT = 1_048_576

        /** A sync's job key: the address after it, so a second sync with the computer joins one that waits. */
        const val SYNC_KEY = "sync:"

        private const val CONFLICT = "conflict"
        private val SIDES = mapOf("here" to Side.HERE, "there" to Side.THERE, "skip" to Side.SKIP)
    }
}
