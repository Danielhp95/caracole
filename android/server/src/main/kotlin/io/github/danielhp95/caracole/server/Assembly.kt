package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
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
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.ktor.LocalServer
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import io.github.danielhp95.caracole.server.lookups.GetRunner
import io.github.danielhp95.caracole.server.lookups.HarmonicaRunner
import io.github.danielhp95.caracole.server.lookups.HarpTabsRunner
import io.github.danielhp95.caracole.server.lookups.InboxRetry
import io.github.danielhp95.caracole.server.lookups.InboxRunner
import io.github.danielhp95.caracole.server.lookups.LaCuerdaRunner
import io.github.danielhp95.caracole.server.lookups.RenderRunner
import io.github.danielhp95.caracole.server.lookups.ReviewRunner
import io.github.danielhp95.caracole.server.lookups.VersionsRunner
import io.github.danielhp95.caracole.server.page.LibraryAssets
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PageRoutes
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.page.ServerControls
import io.github.danielhp95.caracole.server.page.SongbookSection
import io.github.danielhp95.caracole.server.routes.ExportRoutes
import io.github.danielhp95.caracole.server.routes.GuitarRoutes
import io.github.danielhp95.caracole.server.routes.HarmonicaRoutes
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.LookupRoutes
import io.github.danielhp95.caracole.server.routes.RequestsRoutes
import io.github.danielhp95.caracole.server.routes.ReviewRoutes
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.routes.ShareRoutes
import io.github.danielhp95.caracole.server.routes.share.ShareReader
import io.github.danielhp95.caracole.server.routes.SongbookRoutes
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncFileRoutes
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.routes.sync.Exports
import io.github.danielhp95.caracole.server.routes.sync.Imports
import io.github.danielhp95.caracole.server.routes.sync.MirrorPages
import io.github.danielhp95.caracole.server.routes.VersionsRoutes
import io.github.danielhp95.caracole.server.songbooks.SongbookPagesImpl
import io.github.danielhp95.caracole.server.songbooks.SongbookRunner
import io.github.danielhp95.caracole.viewer.render.PhoneRender
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
 * RequestsRoutes, SyncRoutes ([sync], public for the app's unattended sync), SyncFileRoutes (Export and Import a file,
 * whose Sync SyncRoutes hands it; an import's pages a layer of the mirror, the engine's `pagesFromFile`; the export's
 * pages MirrorPages over the mirror), LibraryRoutes, LookupRoutes, then milestone 6's, SongbookRoutes, VersionsRoutes,
 * HarmonicaRoutes, ReviewRoutes, ExportRoutes and GuitarRoutes, then the phone's own ShareRoutes (a song shared to
 * the app, a link alone read by asking its service once: ShareReader), then Stubs for every route no module answers; the
 * library's files behind them; one job queue for every write, its command runners (`get`, `versions`, `lacuerda`,
 * `harptabs`, `review`, `harmonica`, `render`, `songbook`, `inbox`, `backup`), and after each job [afterJob]; the
 * phone's own pages ([render]: through its seam the lookup's pdf stage, what follows a sync's take, and the render job
 * queued by [start] when pages are owed), its songbooks' ([songbookPages]: through its seam the songbooks stage); and
 * the local server. Its page has the Sync tab (ServerControls.sync). Building it queues nothing: the app calls
 * [start] once it has wired the queue's listeners. [render] null: the phone's own PhoneRender (a test gives another).
 * The skeletons write it; a lane that must change it is named in its brief.
 */
class Phone(private val deps: PhoneDeps, render: PhoneRender? = null) {
    val queue: JobQueue
    private val store = LibraryStore(deps.libraryDir)
    private val cards = PhonePageData(MirrorPageData(deps.mirror), store, ::config)

    /** The pages the phone makes itself (milestone 5). */
    val render: PhoneRender = render ?: PhoneRender(deps.database, deps.libraryDir, deps.mirror, deps.version)

    /** The songbooks' pages the phone makes itself (milestone 6), of the mirror's sheets where the songs' pages are
     * the computer's, at the phone's build. */
    val songbookPages = SongbookPagesImpl(deps.database, store, deps.mirror, this.render::build)

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
        // Each seam is NONE until its lane makes it the real one (PhoneRender's, SongbookPagesImpl's), so the lookup
        // never calls a milestone's code before it lands.
        parts = PhoneParts(deps.database, store, deps.stateDir, ::config, queue, cards, ::clients, this.render.seam,
                           songbookPages.seam, deps.alerts, deps.pacing, deps.searchesLacuerda)
        commands["get"] = GetRunner(parts)
        commands["versions"] = VersionsRunner(parts)
        commands["lacuerda"] = LaCuerdaRunner(parts)
        commands["harptabs"] = HarpTabsRunner(parts)
        commands["review"] = ReviewRunner(parts)
        commands["harmonica"] = HarmonicaRunner(parts)
        commands["render"] = RenderRunner(parts)
        commands["songbook"] = SongbookRunner(parts)
        commands["inbox"] = InboxRunner(parts)
        commands["backup"] = BackupRunner(parts)
    }

    /** The files shared to the app that wait for a song, tried again after each job. */
    private val inbox = InboxRetry(parts)

    val search: SearchRoutes = SearchRoutes(deps.database, cards, searchesLacuerda = deps.searchesLacuerda)

    private val engine = SyncEngine(
        deps.database, store, deps.stateDir,
        client = { address -> PeerClient(ServerAddress.parse(address)) },
        mirrorRefresh = deps.mirror?.let { mirror ->
            { address: String ->
                withContext(Dispatchers.IO) { MirrorSync(mirror).sync(ServerAddress.parse(address)) }
                Unit
            }
        },
        // An import's pages kept as a layer of the mirror, the layers then cut to what the phone still serves.
        pagesFromFile = deps.mirror?.let { SyncFileRoutes.pagesFromFile(it, deps.libraryDir, PhoneGate(deps.database)) },
    )

    /** The Sync tab's routes, which the app's unattended sync (`alone`) and Settings' Test (`tested`) ask too. */
    val sync: SyncRoutes = SyncRoutes(engine, queue, deps.settings, deps.database, afterSync = ::afterSync)

    /** The exports made for their one download (`stateDir/cache/peer/`), every one an earlier start left cleared. */
    private val exports = Exports(File(deps.stateDir, "cache")).also { it.clear() }

    /** Export and Import a file: a file staged in `stateDir/peer/import-<id>/`, its import the engine's; the export's
     * pages the mirror's and its layers' (MirrorPages), its start page the phone's own library page's data. */
    private val files = SyncFileRoutes(
        engine, queue, deps.database, deps.libraryDir, Imports(deps.stateDir), exports,
        pages = { MirrorPages(deps.mirror, deps.database.read { db -> MirrorPages.startPage(cards.data(db, now())) }) },
        afterSync = ::afterSync, version = deps.version,
    ).also { sync.files = it }

    /** The route modules, in their order. */
    val modules: List<RouteModule> = listOf(
        PageRoutes(deps.database, LibraryPage(LibraryAssets.load()), cards, ::controls,
                   libraryName = { config().libraryName.orEmpty() }),
        search,
        JobsRoutes(queue, cards, deps.database, songbooks = { db -> SongbookSection.data(db, store, deps.mirror, cards) }),
        RequestsRoutes(parts),
        sync,
        files,
        LibraryRoutes(store, queue, cards, deps.database),
        LookupRoutes(parts),
        SongbookRoutes(parts),
        VersionsRoutes(parts, deps.csrf),
        HarmonicaRoutes(parts, deps.csrf),
        ReviewRoutes(parts),
        ExportRoutes(parts),
        GuitarRoutes(parts),
        ShareRoutes(deps.database, search, deps.csrf, libraryName = { config().libraryName.orEmpty() },
                    links = ShareReader(parts)),
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

    /**
     * What the phone queues at its start, called by the app once it has wired the queue's listeners (Caracole.start:
     * `queue.onBusy`, so the foreground service hears every job, this one too): the render job when the phone owes
     * pages ([PhoneRender.stale]: a new build's, say). Nothing while the render is neutral.
     */
    fun start() {
        if (render.stale()) renderAgain()
    }

    /** After a sync's take, inside the sync's job (SyncRoutes' `afterSync`, its stages over): the copy reloaded, the
     * phone's pages of what the take moved forgotten, the search's answers forgotten, and the pages owed then made by
     * the render job, queued after the sync, never inside it, which makes the phone's songbook pages again after them;
     * with none owed, those songbook pages made again now (SongbookPagesImpl.renderOwn: a song the take moved, its
     * sheet the mirror's now). A full queue leaves them owed, for the next start's or take's render job. */
    internal fun afterSync() {
        deps.mirror?.reload()
        val owed = render.afterSync()
        if (!owed) deps.database.writeBlocking { db -> songbookPages.renderOwn(db) }
        search.invalidate()
        if (owed) {
            try {
                renderAgain()
            } catch (_: QueueFull) {
            }
        }
    }

    /** After each job: the search's answers forgotten (a lookup, a sync or an import may have changed what it
     * finds), a job that failed told ([Alerts.failed]: the app decides whether its owner was looking), and the files
     * shared to the app that wait for a song tried again ([InboxRetry]). */
    private fun afterJob(job: Job) {
        search.invalidate()
        if (job.state == Job.FAILED) {
            deps.alerts.failed(job.display, JobViews.line(job).text)
        }
        inbox.afterJob(job)
    }

    /**
     * The render job (PhoneKinds' render kind, keyed by the phone's build, its words PhoneKinds'): the pages the phone
     * owes made by this build, the lookups queued meanwhile run first between two songs (JobContext.yieldToQueued), its
     * stage saying how far, then the songbook pages the phone made made again where their songs or the build moved
     * (SongbookPagesImpl.renderOwn); a song whose pages couldn't be made fails the job, with why. One waiting already
     * is joined.
     */
    fun renderAgain(): Job {
        val kind = PhoneKinds.RENDER
        val stage = kind.stage.first
        return queue.submit(
            JobSpec(
                title = kind.title, key = kind.key + render.build(), kind = kind.kind,
                display = kind.display, stages = listOf(kind.stage),
                run = { job ->
                    job.stage(stage, "running")
                    val made = render.renderStale(between = { job.yieldToQueued() }) { done, total ->
                        job.stage(stage, "running", PhoneKinds.fill(kind.running, "done" to done, "total" to total))
                    }
                    deps.database.writeBlocking { db -> songbookPages.renderOwn(db) }
                    search.invalidate()
                    val failed = made.failed.values.firstOrNull()
                    if (failed != null) {
                        val line = PhoneKinds.fill(kind.failed, "why" to failed)
                        job.stage(stage, "failed", line)
                        throw IllegalStateException(line)
                    }
                    job.stage(stage, "done", PhoneKinds.fill(kind.done, "n" to made.written))
                },
            ),
        ).first
    }

    /** What the served page carries of the queue: the songs with a job that waits or runs, and those jobs. */
    private fun controls(): ServerControls {
        val active = queue.snapshot().filter { it.state == "queued" || it.state == "running" }
        val removing = active.filter { it.spec.kind == "remove" }.mapNotNull { it.spec.songId }.toSet()
        val busy = active.filter { it.spec.kind != "remove" }.mapNotNull { it.spec.songId }.toSet()
        return ServerControls(
            csrf = deps.csrf, busy = busy, active = active.size, removing = removing,
            jobs = active.map { JobViews.view(it, queue) }, sync = true, guitar = GuitarRoutes.available(),
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
