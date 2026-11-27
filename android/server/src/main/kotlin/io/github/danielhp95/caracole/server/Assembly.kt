package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.catalogues.CatalogueSource
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.ModelsSource
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.MergeProgress
import io.github.danielhp95.caracole.core.index.MergedIndexes
import io.github.danielhp95.caracole.core.index.Paced
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverrideChecks
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.LibraryFiles
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobHistory
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.ktor.LocalServer
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeRunners
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeVideoRunner
import io.github.danielhp95.caracole.server.lookups.ModelsRunner
import io.github.danielhp95.caracole.server.lookups.GetRunner
import io.github.danielhp95.caracole.server.lookups.HarmonicaRunner
import io.github.danielhp95.caracole.server.lookups.HarpTabsRunner
import io.github.danielhp95.caracole.server.lookups.InboxRetry
import io.github.danielhp95.caracole.server.lookups.InboxRunner
import io.github.danielhp95.caracole.server.lookups.LaCuerdaRunner
import io.github.danielhp95.caracole.server.lookups.RenderRunner
import io.github.danielhp95.caracole.server.lookups.ReviewRunner
import io.github.danielhp95.caracole.server.lookups.UgLinkRunner
import io.github.danielhp95.caracole.server.lookups.VersionsRunner
import io.github.danielhp95.caracole.server.page.LibraryAssets
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PageRoutes
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.page.ServerControls
import io.github.danielhp95.caracole.server.page.SongbookSection
import io.github.danielhp95.caracole.server.routes.ExportRoutes
import io.github.danielhp95.caracole.server.routes.YouTubeRoutes
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
import io.github.danielhp95.caracole.server.routes.UgLinkRoutes
import io.github.danielhp95.caracole.server.routes.sync.Exports
import io.github.danielhp95.caracole.server.routes.sync.Imports
import io.github.danielhp95.caracole.server.routes.sync.MirrorPages
import io.github.danielhp95.caracole.server.routes.VersionsRoutes
import io.github.danielhp95.caracole.server.songbooks.SongbookPagesImpl
import io.github.danielhp95.caracole.server.songbooks.SongbookRunner
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import java.io.File
import java.time.Instant
import java.time.temporal.ChronoUnit
import io.github.danielhp95.caracole.mirror.SyncEngine as MirrorSync

/**
 * What the phone's caracole is made of: the app's files and folders, its scope, the computer's address it
 * remembers, the launch's secret and form token, and [transport]: how a request reaches a site, by provider, read on
 * every request (the app's `RealTransport`; a test's refusing or fake transport: it has no default, so no test ever
 * reaches a site by accident). [searchesLacuerda] false: `/api/search`'s `lacuerda_search` null, as the computer's
 * `WebApp(searches_lacuerda=False)` (CaracoleTestRunner's). [catalogues]: where the site catalogues' job lists
 * GitHub's release (GitHub's API; a device test's GitHub on loopback), and [metered]: whether the network is metered
 * now, read as the job runs (the app's ConnectivityManager; none metered by default). [youtube]: the app's yt-dlp (the
 * debug build's :youtube, `ProcessYtDlp` through `YtDlpClient`, one gate a run opened in the main process), null in a
 * build without it. [models]: where the chord
 * models' job downloads them from, with this build's pins (ModelFiles.carried(): the debug build's `:ml` puts them on
 * the classpath; a device test's GitHub on loopback and pins of its own), null for a build that carries none (the
 * release's), whose job and Settings say so. [chords]: the chord models that hear a song's audio (the debug app's
 * `:ml`, E22's), null where nothing can hear (the release, a test's): the audio job then refuses in its words.
 * [examiner]: the reader of an audio file's length and tags the audio store needs (the app's, E24's); by default one
 * that reads none ([NO_EXAMINER]: every file refused as audio caracole doesn't read here).
 */
data class PhoneDeps(val database: Database, val libraryDir: File, val stateDir: File, val mirror: Mirror?,
                     val scope: CoroutineScope, val settings: SyncSettings, val secret: String, val csrf: String,
                     val transport: (provider: String) -> Transport, val version: String = "0.1.0",
                     val alerts: Alerts = Alerts.NONE, val pacing: Pacing = Pacing.REAL,
                     val searchesLacuerda: Boolean = true,
                     val catalogues: (Http) -> CatalogueSource = { CatalogueSource.Api(it) },
                     val metered: () -> Boolean = { false },
                     val youtube: YouTubeEngine? = null,
                     val models: ModelsSource? = ModelFiles.carried()?.let { pins -> ModelsSource(pins = { pins }) },
                     val chords: ChordModels? = null, val examiner: AudioStore.Examiner = NO_EXAMINER) {
    companion object {
        /** An examiner that reads no audio: what it is handed is refused (AudioStore's NOT_AUDIO), as a phone whose app
         * gave none reads no file. */
        val NO_EXAMINER = AudioStore.Examiner { _, _ -> throw IllegalStateException("not audio caracole reads here") }
    }
}

/**
 * The phone's caracole, assembled: its route modules in this order, PageRoutes, SearchRoutes, JobsRoutes,
 * RequestsRoutes, SyncRoutes ([sync], public for the app's unattended sync), SyncFileRoutes (Export and Import a file,
 * whose Sync SyncRoutes hands it; an import's pages a layer of the mirror, the engine's `pagesFromFile`; the export's
 * pages MirrorPages over the mirror), LibraryRoutes, LookupRoutes, UgLinkRoutes (a UG link pasted into the search
 * box), then milestone 6's, SongbookRoutes, VersionsRoutes,
 * HarmonicaRoutes, ReviewRoutes, ExportRoutes and GuitarRoutes, then YouTubeRoutes ([youtubeRoutes]: a sheet from a
 * YouTube video, a pasted video's panel), then the phone's own ShareRoutes (a song shared to
 * the app, a link alone read by asking its service once: ShareReader), then Stubs for every route no module answers; the
 * library's files behind them; one job queue for every write, its requests kept in `stateDir/requests.jsonl`
 * (JobHistory.at) across the app's restarts, its command runners (`get`, `versions`, `lacuerda`,
 * `harptabs`, `ug`, `review`, `harmonica`, `render`, `songbook`, `inbox`, `backup`, `catalogues`: [catalogues],
 * `models`: [models], `audio`: AudioRunner over [audio] and [PhoneDeps.chords], `youtube`: YouTubeSheetRunner over
 * [PhoneDeps.youtube] and the same, and its `--video` YouTubeVideoRunner's), and
 * after each job [afterJob]; the
 * phone's own pages ([render]: through its seam the lookup's pdf stage, what follows a sync's take, and the render job
 * queued by [start] when pages are owed), its songbooks' ([songbookPages]: through its seam the songbooks stage); and
 * the local server. Its page has the Sync tab (ServerControls.sync). Building it queues nothing: the app calls
 * [start] once it has wired the queue's listeners. [render] null: the phone's own PhoneRender (a test gives another).
 * The skeletons write it; a lane that must change it is named in its brief.
 */
class Phone(private val deps: PhoneDeps, render: PhoneRender? = null) {
    val queue: JobQueue
    private val store = LibraryStore(deps.libraryDir, File(deps.stateDir, AudioStore.FOLDER),
                                     YouTubeAudio.folder(File(deps.stateDir, "cache")))
    private val cards = PhonePageData(MirrorPageData(deps.mirror), store)

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

    /** The app's yt-dlp ([PhoneDeps.youtube]): null in a build that carries none (the release, until stage Y5). */
    val youtube: YouTubeEngine? = deps.youtube

    /** The site catalogues' job (`catalogues`), which the app queues ([CataloguesRunner.spec]): GitHub's release read
     * through its API (the owner's choice S1; [PhoneDeps.catalogues], a test's GitHub), asked with caracole's user
     * agent as the settings say it when it runs, stopping for the owner's go-ahead on a network the app says is
     * metered ([PhoneDeps.metered]). */
    val catalogues: CataloguesRunner

    /** The chord models' job (`models`), which the app queues ([ModelsRunner.spec]) and removes ([ModelsRunner.remove]),
     * and the one answer to whether they are here ([ModelsRunner.ready]): [PhoneDeps.models] (null, a build that
     * carries none: the job refuses in its words), stopping for the owner's go-ahead on a metered network as the
     * catalogues do ([PhoneDeps.metered]). */
    val models: ModelsRunner

    /** The audio the owner gave, `stateDir/audio/` ([AudioStore], the audio job's and the audio routes'). */
    val audio: AudioStore

    init {
        val commands = HashMap<String, io.github.danielhp95.caracole.server.jobs.CommandRunner>()
        queue = JobQueue(deps.scope, commands = Commands(commands), history = JobHistory.at(deps.stateDir))
        // The lookup's seams are the real ones, PhoneRender's and SongbookPagesImpl's (SongPages.NONE and
        // SongbookPages.NONE are the corpus's lookup replays', a caracole that makes no page).
        parts = PhoneParts(deps.database, store, deps.stateDir, ::config, queue, cards, ::clients, this.render.seam,
                           songbookPages.seam, deps.alerts, deps.pacing, deps.searchesLacuerda)
        commands["get"] = GetRunner(parts)
        commands["versions"] = VersionsRunner(parts)
        commands["lacuerda"] = LaCuerdaRunner(parts)
        commands["harptabs"] = HarpTabsRunner(parts)
        commands["ug"] = UgLinkRunner(parts)
        commands["review"] = ReviewRunner(parts)
        commands["harmonica"] = HarmonicaRunner(parts)
        commands["render"] = RenderRunner(parts)
        commands["songbook"] = SongbookRunner(parts)
        commands["inbox"] = InboxRunner(parts)
        commands["backup"] = BackupRunner(parts)
        catalogues = CataloguesRunner(parts, source = deps.catalogues, metered = deps.metered,
                                      forget = { search.invalidate() })
        catalogues.sweep()  // the file an import killed in its middle left (up to the whole unpacked index)
        commands[CataloguesRunner.COMMAND] = catalogues
        models = ModelsRunner(parts, deps.models, metered = deps.metered)
        models.sweep()  // what a download killed in its middle left beside the models' folder
        commands[ModelsRunner.COMMAND] = models
        audio = AudioStore(deps.stateDir, deps.examiner)
        commands[AudioRunner.COMMAND] = AudioRunner(parts, deps.chords, audio, problem = ::audioProblem,
                                                    names = models::names,
                                                    hold = { hearing -> models.holding(hearing) })
        tidyAudio()  // the given audio no song names (a merge's older file, a removal's), as the phone starts
        commands[YouTubeSheetRunner.COMMAND] = YouTubeRunners(
            YouTubeSheetRunner(parts, deps.youtube, deps.chords, audio, problem = ::youtubeProblem, names = models::names,
                               hold = { hearing -> models.holding(hearing) }, chordsProblem = ::audioProblem),
            YouTubeVideoRunner(parts, deps.youtube, routeWhy = ::youtubeProblem),
        )
        sweepYouTube()  // the YouTube audio past its days, and what a stopped download left, as the phone starts
    }

    /** Why this phone makes no sheet from a YouTube video now, or null (YouTubeSheetRunner.problemOf over the
     * settings, [PhoneDeps.chords], [ModelsRunner.ready] and [PhoneDeps.youtube]): the job's refusal. */
    fun youtubeProblem(): String? = YouTubeSheetRunner.problemOf(config(), deps.youtube, deps.chords, models.ready())

    /** Why the library page offers no sheet from a YouTube video now (`server.youtube.why`, the design's §5.6), null
     * where it does: [youtubeProblem]'s reasons, then YouTube cooling down after a block, "YouTube refused caracole;
     * asked again after …" ("Out of date" offers it all the same: its audio stage says so). */
    fun youtubeOffered(): String? {
        val problem = youtubeProblem()  // its config read first: no read nested in the one below
        return deps.database.read { db -> YouTubeRoutes.offered(problem, db, Instant.now()) }
    }

    /** YouTubeAudio.sweep of the phone's YouTube audio, in a write of its own. */
    private fun sweepYouTube() {
        deps.database.writeBlocking { db ->
            YouTubeAudio.sweep(db, YouTubeAudio.folder(File(deps.stateDir, "cache")), Instant.now(), Stamps.now())
        }
    }

    /** Why this phone makes no sheet from an audio file now, or null (AudioRunner.problemOf over [PhoneDeps.chords]
     * and [ModelsRunner.ready]): the audio job's refusal, and the one answer E24's routes and `server.audio` give. */
    fun audioProblem(): String? = AudioRunner.problemOf(deps.chords, models.ready())

    /** The kept audio files no song names deleted (audio_store.tidy, the computer's scan step's): at the phone's start
     * and after a sync's take, in a write of their own, never under the store's lock. */
    private fun tidyAudio() {
        deps.database.writeBlocking { db -> audio.tidy(db) }
    }

    /** The files shared to the app that wait for a song, tried again after each job. */
    private val inbox = InboxRetry(parts)

    val search: SearchRoutes = SearchRoutes(deps.database, cards, searchesLacuerda = deps.searchesLacuerda,
                                            cacheDir = File(deps.stateDir, "cache"))

    private val engine = SyncEngine(
        deps.database, store, deps.stateDir,
        client = { address -> PeerClient(ServerAddress.parse(address)) },
        mirrorRefresh = deps.mirror?.let { mirror ->
            { address: String, say: (String) -> Unit ->
                withContext(Dispatchers.IO) {
                    // How many of the pages the phone lacks are copied, as they come ("120 of 640 pages").
                    MirrorSync(mirror).sync(ServerAddress.parse(address), progress = { at ->
                        if (at.total > 0) say("${at.done} of ${at.total} pages")
                    })
                }
                Unit
            }
        },
        // An import's pages kept as a layer of the mirror, the layers then cut to what the phone still serves.
        pagesFromFile = deps.mirror?.let { SyncFileRoutes.pagesFromFile(it, deps.libraryDir, PhoneGate(deps.database)) },
        // A song's [version] and [harmonica] entries checked as overrides.put_song_entries reads them back.
        checks = OVERRIDE_CHECKS,
    ).also { it.sweep() }  // the index files a sync killed in its middle left

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

    /** A sheet from a YouTube video and a pasted video's panel (POST /youtube, GET /api/youtube/video, POST
     * /youtube/video, GET /youtube/thumb/), refused where [youtubeProblem] says why; POST /request with `youtube` is
     * handed to it by LibraryRoutes. */
    val youtubeRoutes: YouTubeRoutes = YouTubeRoutes(parts, audio, ::youtubeProblem)

    /** The route modules, in their order. */
    val modules: List<RouteModule> = listOf(
        PageRoutes(deps.database, LibraryPage(LibraryAssets.load()), cards, ::controls,
                   libraryName = { config().libraryName.orEmpty() }),
        search,
        JobsRoutes(queue, cards, deps.database, songbooks = { db -> SongbookSection.data(db, store, deps.mirror, cards) }),
        RequestsRoutes(parts),
        sync,
        files,
        LibraryRoutes(store, queue, cards, deps.database, youtube = youtubeRoutes::sheetFromYoutube),
        LookupRoutes(parts),
        UgLinkRoutes(parts),
        SongbookRoutes(parts),
        VersionsRoutes(parts, deps.csrf),
        HarmonicaRoutes(parts, deps.csrf),
        ReviewRoutes(parts, deps.csrf),
        ExportRoutes(parts),
        GuitarRoutes(parts),
        youtubeRoutes,
        ShareRoutes(deps.database, search, deps.csrf, libraryName = { config().libraryName.orEmpty() },
                    links = ShareReader(parts), youtube = youtubeRoutes),
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
     * pages ([PhoneRender.stale]: a new build's, say). Nothing while the render is neutral, nor while the overrides
     * can't be read (OverridesError): the phone starts all the same, so that its Backups can restore a library.
     */
    fun start() {
        val stale = try {
            render.stale()
        } catch (_: OverridesError) {
            false
        }
        if (stale) renderAgain()
    }

    /** After a sync's take, inside the sync's job (SyncRoutes' `afterSync`, its stages over): the copy reloaded, the
     * phone's pages of what the take moved forgotten, the search's answers forgotten, and the pages owed then made by
     * the render job, queued after the sync, never inside it, which makes the phone's songbook pages again after them;
     * with none owed, those songbook pages made again now (SongbookPagesImpl.renderOwn: a song the take moved, its
     * sheet the mirror's now). A full queue leaves them owed, for the next start's or take's render job. */
    internal fun afterSync() {
        tidyAudio()  // a song the take removed, or merged into another, leaves its given audio to go
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
     * finds), a job that failed told ([Alerts.failed]: the app decides whether its owner was looking), the pages of
     * its song owed and the render job queued when it moved the song and made no page of it ([PhoneRender.moved]: a
     * review's answer, a LaCuerda pick noted; a full queue leaves them owed, for the next start), and the files
     * shared to the app that wait for a song tried again ([InboxRetry]). */
    private fun afterJob(job: Job) {
        search.invalidate()
        if (job.state == Job.FAILED) {
            deps.alerts.failed(job.display, JobViews.line(job).text)
        }
        if (job.state == Job.DONE && job.spec.kind != PhoneKinds.RENDER.kind && deps.database.read { db ->
                // its song: the one it named, else the song of its key (a review's, keyed by its song alone)
                val song = job.songId ?: Songs.byKey(db, job.key)?.id
                song != null && render.moved(db, song)
            }) {
            deps.database.writeBlocking { db -> render.owe(db) }
            try {
                renderAgain()
            } catch (_: QueueFull) {
            }
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

    /** What the served page carries of the queue: the songs with a job that waits or runs, and those jobs; and the
     * songs a review must come first for (library_routes.library's `held`: LookupForms.reviewFirst, as POST /fetch
     * refuses them), which the page offers no Fetch for. */
    private fun controls(): ServerControls {
        val active = queue.snapshot().filter { it.state == "queued" || it.state == "running" }
        val removing = active.filter { it.spec.kind == "remove" }.mapNotNull { it.spec.songId }.toSet()
        val busy = active.filter { it.spec.kind != "remove" }.mapNotNull { it.spec.songId }.toSet()
        val held = deps.database.read { db ->
            val overrides = try {
                Overrides.read(db)
            } catch (_: OverridesError) {
                null  // the page says what is wrong with them; POST /fetch refuses as it can
            }
            if (overrides == null) emptySet()
            else Songs.list(db).filter { LookupForms.reviewFirst(it, overrides) }.mapTo(HashSet()) { it.id }
        }
        return ServerControls(
            csrf = deps.csrf, busy = busy, active = active.size, held = held, removing = removing,
            jobs = active.map { JobViews.view(it, queue) }, sync = true, guitar = GuitarRoutes.available(),
            inApp = true, youtube = youtubeOffered(), youtubeOff = !config().provider("youtube").enabled,
        )
    }

    /** The computer's index in [file] merged, as a job of kind "index" (key "index"), so it never writes beside a
     * sync, and what it read recorded (MergedIndexes: the next sync asks the computer for none of it again); the file
     * is deleted after, and the WAL the merge grew given back (Database.checkpoint). The device tests' and the e2e's
     * way to give the phone an index (the app queues none). */
    fun importIndex(file: File): Job = queue.submit(importSpec(file)).first

    /** [importIndex]'s job: its stage says each step of the merge as a sync's index stage says them (Paced, each
     * step's words its detail with one "…" left off, SyncEngine.detail: "Importing · gtptabs.com", "Tidying the
     * database"), its line "Merging the computer's index · …" (JobViews). */
    internal fun importSpec(file: File): JobSpec =
        JobSpec(
            title = "Import the computer's index", key = "index", kind = "index", display = "The computer's index",
            stages = listOf("merge" to "Merging the index"),
            run = { job ->
                job.stage("merge", "running")
                val paced = Paced({ words -> job.stage("merge", "running", SyncEngine.detail(words)) })
                try {
                    val merged = deps.database.write { db ->
                        IndexTransfer.merge(db, file, now(), progress = { paced.say(it.words(), it.step) })
                            .also { MergedIndexes.record(db, it) }
                    }
                    paced.say(MergeProgress.TIDYING)
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
        )

    private fun now(): String = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()
}

/** The viewer's checks of an overrides entry, which core's take reaches through OverrideChecks: viewer/version.py's
 * `key_version` and viewer/harptab.py's `check_spec`, as Python's reader runs them on every load. */
internal val OVERRIDE_CHECKS = OverrideChecks(Versions::keyVersion, HarpTabs::checkSpec)
