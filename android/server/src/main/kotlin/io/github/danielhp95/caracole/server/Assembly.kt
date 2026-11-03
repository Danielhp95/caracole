package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.LibraryFiles
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.server.ktor.LocalServer
import io.github.danielhp95.caracole.server.page.LibraryAssets
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PageRoutes
import io.github.danielhp95.caracole.server.page.ServerControls
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant
import java.time.temporal.ChronoUnit
import io.github.danielhp95.caracole.mirror.SyncEngine as MirrorSync

/** What the phone's caracole is made of: the app's files and folders (the plan's §5.4), its scope, the computer's
 * address it remembers, and the launch's secret and form token. */
data class PhoneDeps(val database: Database, val libraryDir: File, val stateDir: File, val mirror: Mirror?,
                     val scope: CoroutineScope, val settings: SyncSettings, val secret: String, val csrf: String)

/**
 * The phone's caracole, assembled: its route modules in this order, PageRoutes, SearchRoutes, JobsRoutes,
 * SyncRoutes, LibraryRoutes, then Stubs for every route out of this round; the library's files behind them; one job
 * queue for every write; and the local server. Its page has the Sync tab (ServerControls.sync). The integration step
 * may adjust it; the lanes code against it.
 */
class Phone(private val deps: PhoneDeps) {
    val queue: JobQueue = JobQueue(deps.scope)

    private val cards = MirrorPageData(deps.mirror)
    private val store = LibraryStore(deps.libraryDir)

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

    val app: App = App(
        AppConfig(csrf = deps.csrf, secret = deps.secret),
        modules = listOf(
            PageRoutes(deps.database, LibraryPage(LibraryAssets.load()), cards, ::controls),
            search,
            JobsRoutes(queue, cards, deps.database),
            SyncRoutes(engine, queue, deps.settings, deps.database, afterSync = {
                search.invalidate()
                deps.mirror?.reload()
            }),
            LibraryRoutes(store, queue, cards, deps.database),
        ),
        stubs = Stubs(),
        files = LibraryFiles(deps.libraryDir, deps.mirror, PhoneGate(deps.database), deps.database),
    )

    val server: LocalServer = LocalServer(app)

    /** What the served page carries of the queue: the songs with a job that waits or runs, and those jobs. */
    private fun controls(): ServerControls {
        val active = queue.snapshot().filter { it.state == "queued" || it.state == "running" }
        val removing = active.filter { it.spec.kind == "remove" }.mapNotNull { it.spec.songId }.toSet()
        val busy = active.filter { it.spec.kind != "remove" }.mapNotNull { it.spec.songId }.toSet()
        return ServerControls(
            csrf = deps.csrf, busy = busy, active = active.size, removing = removing,
            jobs = active.map { JobViews.view(it, queue) }, sync = true,
        )
    }

    /** The computer's index in [file] merged, as a job of kind "index" (key "index"), so it never writes beside a
     * sync; the file is deleted after. */
    fun importIndex(file: File): Job = queue.submit(
        JobSpec(
            title = "Import the index", key = "index", kind = "index", display = "The computer's index",
            stages = listOf("merge" to "Merging the index"),
            run = { job ->
                job.stage("merge", "running")
                try {
                    val merged = deps.database.write { db -> IndexTransfer.merge(db, file, now()) }
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
