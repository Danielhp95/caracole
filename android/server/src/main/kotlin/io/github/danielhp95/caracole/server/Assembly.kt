package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.LibraryFiles
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.server.ktor.LocalServer
import io.github.danielhp95.caracole.server.lookups.GetRunner
import io.github.danielhp95.caracole.server.lookups.HarpTabsRunner
import io.github.danielhp95.caracole.server.lookups.LaCuerdaRunner
import io.github.danielhp95.caracole.server.lookups.VersionsRunner
import io.github.danielhp95.caracole.server.page.LibraryAssets
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PageRoutes
import io.github.danielhp95.caracole.server.page.ServerControls
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.LookupRoutes
import io.github.danielhp95.caracole.server.routes.RequestsRoutes
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant
import java.time.temporal.ChronoUnit
import io.github.danielhp95.caracole.mirror.SyncEngine as MirrorSync

/**
 * What the phone's caracole is made of: the app's files and folders, its scope, the computer's address it
 * remembers, the launch's secret and form token, and [transport]: how a request reaches a site, by provider, read on
 * every request (the app's `RealTransport`; a test's refusing or fake transport: it has no default, so no test ever
 * reaches a site by accident). [searchesLacuerda] false: `/api/search`'s `lacuerda_search` null, as the computer's
 * `WebApp(searches_lacuerda=False)` (CaracoleTestRunner's).
 */
data class PhoneDeps(val database: Database, val libraryDir: File, val stateDir: File, val mirror: Mirror?,
                     val scope: CoroutineScope, val settings: SyncSettings, val secret: String, val csrf: String,
                     val transport: (provider: String) -> Transport, val version: String = "0.1.0",
                     val alerts: Alerts = Alerts.NONE, val pacing: Pacing = Pacing.REAL,
                     val searchesLacuerda: Boolean = true)

/**
 * The phone's caracole, assembled: its route modules in this order, PageRoutes, SearchRoutes, JobsRoutes,
 * RequestsRoutes, SyncRoutes, LibraryRoutes, LookupRoutes (milestone 6's after them, skeleton-m5m6's), then Stubs for
 * every route no module answers; the library's files behind them; one job queue for every write, its command runners
 * (`get`, `versions`, `lacuerda`, `harptabs`), and after each job [afterJob]; and the local server. Its page has the
 * Sync tab (ServerControls.sync). The skeletons write it; a lane that must change it is named in its brief.
 */
class Phone(private val deps: PhoneDeps) {
    val queue: JobQueue
    private val cards = MirrorPageData(deps.mirror)
    private val store = LibraryStore(deps.libraryDir)

    /** The phone's settings now: config.py's defaults with what the computer gave at the last sync. */
    private fun config(): PhoneConfig = deps.database.read { db -> PhoneConfig.read(db) }

    /** A lookup's clients, each request sent through the transport the deps give now. */
    private fun clients(): Clients = Clients(config(), File(deps.stateDir, "cache"),
                                             { provider -> Transport { request -> deps.transport(provider).send(request) } },
                                             deps.pacing)

    val parts: PhoneParts

    init {
        val commands = HashMap<String, io.github.danielhp95.caracole.server.jobs.CommandRunner>()
        queue = JobQueue(deps.scope, commands = Commands(commands))
        parts = PhoneParts(deps.database, store, deps.stateDir, ::config, queue, cards, ::clients, SongPages.NONE,
                           SongbookPages.NONE, deps.alerts, deps.pacing, deps.searchesLacuerda)
        commands["get"] = GetRunner(parts)
        commands["versions"] = VersionsRunner(parts)
        commands["lacuerda"] = LaCuerdaRunner(parts)
        commands["harptabs"] = HarpTabsRunner(parts)
    }

    val search: SearchRoutes = SearchRoutes(deps.database, cards)

    private val engine = SyncEngine(
        deps.database, store, deps.stateDir,
        client = { address -> PeerClient(ServerAddress.parse(address)) },
        mirrorRefresh = deps.mirror?.let { mirror ->
            { address: String ->
                withContext(Dispatchers.IO) { MirrorSync(mirror).sync(ServerAddress.parse(address)) }
                Unit
            }
        },
    )

    /** The route modules, in their order. */
    val modules: List<RouteModule> = listOf(
        PageRoutes(deps.database, LibraryPage(LibraryAssets.load()), cards, ::controls,
                   libraryName = { config().libraryName.orEmpty() }),
        search,
        JobsRoutes(queue, cards, deps.database),
        RequestsRoutes(parts),
        SyncRoutes(engine, queue, deps.settings, deps.database, afterSync = {
            search.invalidate()
            deps.mirror?.reload()
        }),
        LibraryRoutes(store, queue, cards, deps.database),
        LookupRoutes(parts),
    )

    val app: App = App(
        AppConfig(csrf = deps.csrf, secret = deps.secret, libraryName = { config().libraryName.orEmpty() }),
        modules = modules,
        stubs = Stubs(),
        files = LibraryFiles(deps.libraryDir, deps.mirror, PhoneGate(deps.database), deps.database),
    )

    val server: LocalServer = LocalServer(app)

    init {
        queue.onEnd = ::afterJob
        deps.scope.launch(Dispatchers.IO) { runCatching { deps.database.warmUp() } }
    }

    /** After each job: the search's answers forgotten (a lookup, a sync or an import may have changed what it
     * finds), and a job that failed told ([Alerts.failed]: the app decides whether its owner was looking). */
    private fun afterJob(job: Job) {
        search.invalidate()
        if (job.state == Job.FAILED) {
            deps.alerts.failed(job.display, JobViews.line(job).text)
        }
    }

    /** What the served page carries of the queue: the songs with a job that waits or runs, and those jobs. */
    private fun controls(): ServerControls {
        val active = queue.snapshot().filter { it.state == "queued" || it.state == "running" }
        val removing = active.filter { it.spec.kind == "remove" }.mapNotNull { it.spec.songId }.toSet()
        val busy = active.filter { it.spec.kind != "remove" }.mapNotNull { it.spec.songId }.toSet()
        return ServerControls(
            csrf = deps.csrf, busy = busy, active = active.size, removing = removing,
            jobs = active.map { JobViews.view(it, queue) }, sync = true, guitar = false,
        )
    }

    /** The computer's index in [file] merged, as a job of kind "index" (key "index"), so it never writes beside a
     * sync; the file is deleted after, and the WAL the merge grew given back (Database.checkpoint). */
    fun importIndex(file: File): Job = queue.submit(
        JobSpec(
            title = "Import the index", key = "index", kind = "index", display = "The computer's index",
            stages = listOf("merge" to "Merging the index"),
            run = { job ->
                job.stage("merge", "running")
                try {
                    val merged = deps.database.write { db -> IndexTransfer.merge(db, file, now()) }
                    deps.database.checkpoint()
                    search.invalidate()
                    job.stage("merge", "done", if (merged.changed) "merged" else "nothing newer")
                    job.outcome(JsonObject(mapOf(
                        "changed" to JsonPrimitive(merged.changed),
                        "sites" to JsonArray(merged.sites.keys.sorted().map { JsonPrimitive(it) }),
                    )))
                } finally {
                    file.delete()
                }
            },
        ),
    ).first

    private fun now(): String = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()
}
