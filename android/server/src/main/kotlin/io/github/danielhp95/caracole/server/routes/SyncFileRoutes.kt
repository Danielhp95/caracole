package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TabCounts
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Conflicts
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.sync.file.FileError
import io.github.danielhp95.caracole.core.sync.file.FileSource
import io.github.danielhp95.caracole.core.sync.file.PageSource
import io.github.danielhp95.caracole.core.sync.file.SyncFile
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.DocumentAnswer
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.SyncJson
import io.github.danielhp95.caracole.server.routes.sync.Exports
import io.github.danielhp95.caracole.server.routes.sync.Imports
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.time.Instant
import java.time.ZoneId

/** How Sync on a file's comparison is queued, which SyncRoutes' `POST /sync/apply` asks of a comparison of kind
 * `"file"` (sync_routes._apply_import): [SyncFileRoutes]'. */
fun interface FileSyncs {
    fun apply(made: String, kept: Comparison, choices: Map<String, Side>, prefer: Side?, parts: List<String>?): Response
}

/**
 * The phone's Export and Import a file, answering as caracole serve's web/sync_file_routes.py answers, in its words and
 * with its shapes (library_assets/sync.js reads them on both sides; the sync redesign's §3.4.2;
 * tests/conformance/vectors/web/sync_file_routes.jsonl):
 *
 *     GET  /api/sync/sizes      what an export of this library would hold: its name ([name]), its songs and songbooks,
 *                               when (`made`: now), the bytes of its library (its kept files, and the pages its
 *                               export holds, [pages]), of its site indexes (SyncFiles.indexesSize; null where SQLite
 *                               has no dbstat) and the tabs they track
 *     POST /sync/export         this library's parts (JSON `{"parts": [...]}`: the library or the songbooks, or both,
 *                               and the indexes or not) written to a new file of `stateDir/cache/peer/` ([exports]),
 *                               one at a time: `{"export", "name", "size"}`, its id, the name it downloads under
 *                               (SyncFiles.fileName: the library's and the day's, in [zone]) and its size
 *     GET  /api/sync/export?export=   that file, an attachment by that name, streamed, its name deleted as it is
 *                               opened to be sent (Body.FromFile's `once`): 404 after, and for one made more than an
 *                               hour before; a HEAD, which would spend its one GET, 405
 *     POST /sync/import/open    a file to import opened (JSON `{"size", "name"}`), once the imports no request names
 *                               that are whole or stopped are let go ([Imports.letGo]): its id and how big a part may
 *                               be, `{"import", "part"}` (413 past 8 GiB, 409 with one open already)
 *     POST /sync/import/part?import=&at=   a part of that file, its bytes (8 MiB at most), written where what it has
 *                               ends: `{"have"}`; 400 for a part that isn't the next one or would pass its size
 *     POST /sync/import/compare this library and that file compared (form: `import`; SyncEngine.compareFile: read whole
 *                               first, and refused in the owner's words, 400 NOT_A_FILE, OTHER_FORMAT, UNREADABLE, 409
 *                               OWN_EXPORT, OLDER, and deleted), as `POST /sync/compare` answers a comparison with the
 *                               computer, kept for its Sync: the other side the file (`peer.kind` "file", its
 *                               `made`, no address), `holds` the parts it holds, the indexes it read more recently
 *     POST /sync/import/drop    that file deleted now (JSON `{"import"}`: the page's Cancel, an upload that failed):
 *                               `{"dropped"}`; 409 while its request waits or its import takes it
 *
 * Sync on a file's comparison is SyncRoutes' `POST /sync/apply`, which hands it to [apply] (sync_routes._apply_import):
 * the staged file compared again, sending no request (409 STALE once this library moved since, 409 GONE once the file
 * is gone), then the import queued, a job of kind `sync` under `import:<file id>`, displayed "Sync with a file from
 * <its library's name>", in SyncEngine.FILE_STAGES: SyncEngine.apply of the comparison, within its parts, while
 * [Imports.held] holds the file; its outcome the sync's (SyncJson.outcome, its report); the file's folder deleted once
 * it ends, whatever came of it; then [afterSync]. Its pages are kept as a layer of the mirror by the engine's
 * `pagesFromFile` ([pagesFromFile]).
 *
 * Nothing of an export or an import is sent to a site: an export is a read of the database (its writer, for its
 * indexes' attached file) made here, an import's file staged in `stateDir/peer/import-<id>/` and nothing of it reaches
 * the library but through the import's job. Times are [now]'s, a day in [zone]'s.
 */
class SyncFileRoutes(
    val engine: SyncEngine, val queue: JobQueue, val database: Database, val libraryDir: File, val imports: Imports,
    val exports: Exports, val pages: () -> PageSource?, val afterSync: () -> Unit,
    val name: () -> String = { AppConfig.PHONE }, val version: String = SyncEngine.CARACOLE,
    val now: () -> Instant = { Instant.now() }, val zone: () -> ZoneId = { ZoneId.systemDefault() },
) : RouteModule, FileSyncs {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/sync/sizes", "what an export of this library would hold", get = GetAnswer { sizes() }),
        Route("POST", "/sync/export", "this library written to a file, for its one download", body = Route.JSON,
              document = DocumentAnswer { _, doc -> export(doc) }),
        Route("GET", "/api/sync/export", "an export, sent once", get = GetAnswer { request -> download(request) }),
        Route("POST", "/sync/import/open", "a file to import opened for its parts", body = Route.JSON,
              document = DocumentAnswer { _, doc -> open(doc) }),
        Route("POST", "/sync/import/part", "a part of a file to import", body = Route.BYTES, limit = Imports.PART_MAX,
              document = DocumentAnswer { request, data -> part(params(request.target), data as ByteArray) }),
        Route("POST", "/sync/import/compare", "this library and a file compared",
              post = PostAnswer { _, form -> compare(form) }),
        Route("POST", "/sync/import/drop", "a file to import deleted now", body = Route.JSON,
              document = DocumentAnswer { _, doc -> drop(doc) }),
    )

    // --- what an export would hold --------------------------------------------------------------------------------

    private fun sizes(): Response {
        val source = pages()
        val read = database.read { db ->
            val songs = db.one("SELECT COUNT(*) FROM songs") { it.long(0)!! }!!
            val songbooks = db.one("SELECT COUNT(*) FROM phone_songbooks") { it.long(0)!! }!!
            Sized(songs, songbooks, libraryBytes(db, source), SyncFiles.indexesSize(db), TabCounts.of(db).values.sum())
        }
        exports.sweep()
        return Answers.json(JsonObject(linkedMapOf(
            "name" to JsonPrimitive(name()), "songs" to JsonPrimitive(read.songs),
            "songbooks" to JsonPrimitive(read.songbooks), "made" to JsonPrimitive(Stamps.of(now())),
            "library" to JsonPrimitive(read.library), "indexes" to JsonPrimitive(read.indexes),
            "tabs" to JsonPrimitive(read.tabs),
        )))
    }

    private class Sized(val songs: Long, val songbooks: Long, val library: Long, val indexes: Long?, val tabs: Long)

    /** sync_file_routes._library_bytes: about what an export's library takes, each path once: the bytes on disk of
     * each kept file (a regular file under the library, reached by its path), and of each page its export would hold
     * ([source]'s list of the units as the phone holds them now), as listed. */
    private fun libraryBytes(db: Db, source: PageSource?): Long {
        val sized = LinkedHashMap<String, Long>()
        for (path in db.query("SELECT path FROM files") { it.text(0)!! }) {
            if (path in sized) continue
            regularSize(path)?.let { sized[path] = it }
        }
        val listed = source?.manifest(Units.libraryState(db).mapValues { it.value.digest })
        for (entry in (listed?.get("files") as? JsonArray).orEmpty()) {
            val e = entry as? JsonObject ?: continue
            val path = (e["path"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: continue
            val size = (e["size"] as? JsonPrimitive)?.content?.toLongOrNull() ?: continue
            sized.putIfAbsent(path, size)
        }
        return sized.values.sum()
    }

    /** The size of the regular file at the library's [path] (no `..`, no backslash, no absolute path); null for none. */
    private fun regularSize(path: String): Long? {
        val parts = path.split('/')
        if (path.isEmpty() || path.startsWith("/") || '\\' in path || parts.any { it == ".." || it.isEmpty() }) return null
        val file = File(libraryDir, parts.joinToString(File.separator))
        return try {
            if (Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) Files.size(file.toPath()) else null
        } catch (e: IOException) {
            null
        } catch (e: java.nio.file.InvalidPathException) {
            null
        }
    }

    // --- the export -----------------------------------------------------------------------------------------------

    /** `POST /sync/export`: the parts [doc] names written to a new file, kept for its one GET; 400 for parts that
     * aren't the library or the songbooks (with the indexes or not), 503 while another export is made or for one that
     * can't be made. */
    private fun export(doc: Any): Response {
        val named = ((doc as? JsonObject)?.get("parts") as? JsonArray)
            ?.takeIf { it.isNotEmpty() && it.all { p -> p is JsonPrimitive && p.isString } }
            ?.map { (it as JsonPrimitive).content }
            ?: throw Refused(400, NOT_EXPORTED, NO_PARTS)
        val parts = try {
            SyncFiles.checkedParts(named)
        } catch (e: FileError) {
            throw Refused(400, NOT_EXPORTED, NO_PARTS)
        }
        if (Scope.LIBRARY !in parts && Scope.SONGBOOKS !in parts) throw Refused(400, NOT_EXPORTED, NOT_ALONE)
        val at = now()
        val fileName = SyncFiles.fileName(name(), at, zone())
        val source = if (Scope.LIBRARY in parts) pages() else null
        val made = try {
            exports.make(fileName) { file ->
                database.writeBlocking { db ->
                    SyncFiles.export(db, libraryDir, source, file, parts, Stamps.of(at), Compare.ownId(db), name(), version)
                }
            }
        } catch (e: Exports.Busy) {
            throw Refused(503, NOT_EXPORTED, Exports.BUSY)
        } catch (e: FileError) {
            throw Refused(503, NOT_EXPORTED, "The file couldn't be made: ${e.message}.")
        } catch (e: IOException) {
            throw Refused(503, NOT_EXPORTED, "The file couldn't be made: ${e.message ?: e.javaClass.simpleName}.")
        }
        return Answers.json(JsonObject(linkedMapOf(
            "export" to JsonPrimitive(made.id), "name" to JsonPrimitive(made.name), "size" to JsonPrimitive(made.size),
        )))
    }

    /** `GET /api/sync/export`: the export `export` names, streamed, sent once; 404 for one sent, swept or never made;
     * 405 for a HEAD. */
    private fun download(request: Request): Response {
        if (request.method == "HEAD") return Response(405, Body.Empty, mutableListOf("Allow" to "GET"))
        val (file, named) = exports.take(params(request.target)["export"].orEmpty())
            ?: return Answers.json(JsonObject(mapOf("error" to JsonPrimitive(GONE))), 404)
        return Response(200, Body.FromFile(file, file.length(), once = true), mutableListOf(
            "Content-Type" to SyncFiles.MEDIA_TYPE, "Content-Disposition" to DownloadNames.contentDisposition(named),
        ))
    }

    // --- a file to import, sent in parts --------------------------------------------------------------------------

    /** `POST /sync/import/open`: a file of `size` bytes (a JSON integer) named `name` (text) opened for its parts. */
    private fun open(doc: Any): Response {
        val given = doc as? JsonObject ?: JsonObject(emptyMap())
        val id = staging {
            imports.letGo(named())
            imports.open(size(given["size"]), (given["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content)
        }
        return Answers.json(JsonObject(linkedMapOf("import" to JsonPrimitive(id), "part" to JsonPrimitive(Imports.PART_MAX))))
    }

    /** `POST /sync/import/part`: a part of the import `import` names, written at `at`. */
    private fun part(params: Map<String, String>, data: ByteArray): Response {
        val at = params["at"].orEmpty()
        if (!AT.matches(at)) {
            throw Refused(400, NOT_TAKEN, "Where does that part go? at is the number of bytes sent before it.")
        }
        val have = staging("That part couldn't be kept") { imports.addPart(params["import"].orEmpty(), at.toLong(), data) }
        return Answers.json(JsonObject(mapOf("have" to JsonPrimitive(have))))
    }

    /** `POST /sync/import/drop`: the import `import` names deleted now; 409 while its request waits or its import
     * takes it, 404 for none. */
    private fun drop(doc: Any): Response {
        val id = ((doc as? JsonObject)?.get("import") as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: throw Refused(400, NOT_DROPPED, NOT_NAMED)
        if (id in named()) throw Refused(409, NOT_DROPPED, WAITS)
        try {
            imports.drop(id)
        } catch (e: Imports.StagingError) {
            throw Refused(e.status, NOT_DROPPED, e.message ?: "")
        }
        return Answers.json(JsonObject(mapOf("dropped" to JsonPrimitive(id))))
    }

    /** The imports a waiting or running request names (`import:<id>`). */
    private fun named(): Set<String> = queue.snapshot()
        .filter { it.active && it.spec.key.startsWith(IMPORTING) }
        .mapTo(HashSet()) { it.spec.key.removePrefix(IMPORTING) }

    /** [block], its StagingError the route's refusal (its status, "Not taken"), a storage failure 503. */
    private fun <T> staging(failed: String = "The file couldn't be kept", block: () -> T): T = try {
        block()
    } catch (e: Imports.StagingError) {
        throw Refused(e.status, NOT_TAKEN, e.message ?: "")
    } catch (e: IOException) {
        throw Refused(503, "Not kept", "$failed: ${e.message ?: e.javaClass.simpleName}.")
    }

    // --- an import's comparison -----------------------------------------------------------------------------------

    /**
     * `POST /sync/import/compare`: this library and the file staged as `import` compared (SyncEngine.compareFile, its
     * whole read first), as `POST /sync/compare` answers (SyncJson.comparison), the comparison kept for its Sync, with
     * the other side the file's: `peer` `{address: null, server: the file's caracole's id, caracole, name, kind:
     * "file", made}`, `holds` the parts it holds, and `indexes` the sites it read more recently than this library (a
     * file takes nothing back: none newer here). The file refused: its words (400, 409), and it is deleted.
     */
    private fun compare(form: Map<String, String>): Response {
        val id = Py.strip(form["import"].orEmpty())
        val c = staged(id) { file -> engine.compareFile(file, imports.openedName(id)) }
        return Answers.json(fileComparison(c))
    }

    /** [compare]'s answer of [c]. */
    private fun fileComparison(c: Comparison): JsonObject {
        val file = c.file!!
        val answer = SyncJson.comparison(c)
        val indexes = if (Scope.INDEXES in c.holds) {
            (answer.getValue("indexes") as JsonArray).filter { (it as JsonObject)["newer"] == JsonPrimitive("there") }
        } else emptyList()
        return JsonObject(answer + mapOf(
            "peer" to JsonObject(linkedMapOf(
                "address" to JsonNull, "server" to (file.id?.let(::JsonPrimitive) ?: JsonNull),
                "caracole" to (file.manifest["caracole"] ?: JsonNull), "name" to JsonPrimitive(file.name),
                "kind" to JsonPrimitive(SyncEngine.FILE), "made" to (file.made?.let(::JsonPrimitive) ?: JsonNull),
            )),
            "indexes" to JsonArray(indexes),
        ))
    }

    /**
     * sync_file_routes._compare_staged: [read] of the file staged as [id], once whole, held meanwhile (never waiting
     * for another hold: 409); a file refused (a [FileError]) is deleted and refused in its words (409 for this
     * library's own export or one no newer than the last sync with its caracole, 400 else); one gone, 404 ([GONE_FILE]).
     */
    private fun <T> staged(id: String, read: (File) -> T): T = try {
        imports.held(id, wait = false) {
            val file = imports.whole(id)
            try {
                read(file)
            } catch (e: FileError) {
                imports.remove(id)
                val said = e.message ?: ""
                throw Refused(if (said == FileError.OWN_EXPORT || said.startsWith(OLDER)) 409 else 400, NOT_TAKEN, said)
            } catch (e: PeerError) {
                imports.remove(id)
                throw Refused(400, NOT_TAKEN, e.message ?: "")
            }
        }
    } catch (e: Imports.StagingError) {
        throw Refused(e.status, "Not compared", if (e.status == 404) GONE_FILE else e.message ?: "")
    }

    /**
     * Sync on a file's comparison (sync_routes._apply_import, which SyncRoutes' apply hands it to once its choices
     * are read): the staged file compared again, sending no request (409 STALE once this library moved since, the
     * comparison forgotten; 409 GONE once the file is gone), then its import queued (the class's), its view the answer;
     * one of that file waiting or running already is refused (409).
     */
    override fun apply(made: String, kept: Comparison, choices: Map<String, Side>, prefer: Side?,
                       parts: List<String>?): Response {
        val file = kept.file ?: throw Refused(409, "Compare again", GONE_FILE)
        val id = imports.idOf(file.file) ?: throw Refused(409, "Compare again", GONE_FILE)
        val same = try {
            staged(id) { engine.stillAsCompared(kept) }
        } catch (e: Refused) {
            if (e.status == 404) throw Refused(409, "Compare again", GONE_FILE)
            throw e
        }
        if (!same) {
            engine.forget(made)
            throw Refused(409, "Compare again", SyncEngine.STALE)
        }
        val shown = "Sync with a file from ${Py.slice(Py.strip(file.name).ifEmpty { "a library" }, null, 120)}"
        val (job, new) = queue.submitOrRefuse(importJob(shown, id, kept, choices, prefer, parts ?: Scope.PARTS))
        if (!new) {
            throw Refused(409, "Importing already", "That file is being imported already (request ${job.id}): choose " +
                                                    "it again once that is over.")
        }
        engine.forget(made)
        return Answers.queued(JobViews.view(job, queue), "/#tab=sync")
    }

    /** The import's job (the class's): kind `sync` under `import:<id>`, SyncEngine.FILE_STAGES. */
    private fun importJob(shown: String, id: String, c: Comparison, choices: Map<String, Side>, prefer: Side?,
                          parts: List<String>): JobSpec = JobSpec(
        title = shown, key = IMPORTING + id, kind = "sync", stages = SyncEngine.FILE_STAGES, display = shown,
        join = false,
        run = { context: JobContext ->
            val told = HashSet<String>()
            val stage = { name: String, state: String, detail: String ->
                told.add(name)
                context.stage(name, state, detail)
            }
            try {
                try {
                    imports.hold(id)
                } catch (e: Imports.StagingError) {
                    stage(SyncEngine.CHECK, "failed", e.message ?: "")
                    throw SyncFailed(e.message ?: "", null, e)
                }
                try {
                    context.outcome(SyncJson.outcome(engine.apply(c, choices, prefer, parts, Conflicts.ASK, stage)))
                } finally {
                    imports.release(id)
                }
            } catch (e: SyncFailed) {
                e.outcome?.let { context.outcome(SyncJson.outcome(it)) }
                for ((name, _) in SyncEngine.FILE_STAGES) if (name !in told) context.stage(name, "skipped")
                throw e
            } finally {
                imports.remove(id)
                imports.sweep()
                afterSync()
            }
        },
    )

    companion object {
        /** sync_routes.IMPORTING: an import's job key, the staged file's id after it. */
        const val IMPORTING = "import:"

        const val NOT_ALONE = "An export holds the library or the songbooks, or both: the site indexes alone are " +
            "caracole index export's."
        const val NO_PARTS = "Which parts? {\"parts\": [\"library\", \"songbooks\", \"indexes\"]}, the library or the " +
            "songbooks among them."
        const val GONE = "No such export here: it was sent once already, or made more than an hour ago, or another " +
            "made since, or caracole serve has restarted since. Export again."
        const val WAITS = "That file waits to be imported: cancel its request in the Requests tab first."
        const val NOT_NAMED = "Which file? {\"import\": \"<its id>\"}, as POST /sync/import/open named it."

        /** peer_import.GONE: a staged file gone (left over an hour, or another chosen since). */
        const val GONE_FILE = Imports.GONE

        private const val NOT_EXPORTED = "Not exported"
        private const val NOT_TAKEN = "Not taken"
        private const val NOT_DROPPED = "Not dropped"
        private val OLDER = FileError.older("\u0000", "").substringBefore('\u0000')
        private val AT = Regex("[0-9]{1,15}")
        private val INT = Regex("-?[0-9]+")

        /** peer_import.open_import's `size`: a JSON integer alone (never a bool, a float or a text, which are none),
         * one past a Long past every size (refused as too big), as `type(size) is int` reads it. */
        private fun size(given: JsonElement?): Long? {
            val p = given as? JsonPrimitive ?: return null
            if (p.isString || !INT.matches(p.content)) return null
            return p.content.toLongOrNull() ?: if (p.content.startsWith("-")) null else Long.MAX_VALUE
        }

        /** sync_file_routes._params: a request's query, each name's first value, blank ones kept; none for a query
         * that can't be read. */
        private fun params(target: String): Map<String, String> = try {
            PyUrl.parseQs(PyUrl.urlsplit(target).query, keepBlank = true, maxFields = 10).mapValues { it.value.first() }
        } catch (e: PyUrl.Invalid) {
            emptyMap()
        }

        /**
         * The engine's `pagesFromFile`: the pages a file held of the units an import took from it ([taken]), kept as
         * a layer of [mirror] (Mirror.takeLayer: under the file's caracole's id, each page checked by its SHA-256,
         * as the phone serves it), the layers then cut to what [gate] still serves. Nothing for a file of no id (an
         * index export) or no pages.
         */
        fun pagesFromFile(mirror: Mirror, libraryDir: File, gate: UnitGate): (SyncFile, List<String>) -> Unit = { file, taken ->
            val id = file.id
            if (id != null) {
                FileSource(file, null, libraryDir).use { source ->
                    val listed = source.pages()
                    if (listed != null) {
                        mirror.takeLayer(id, listed.toString().toByteArray(Charsets.UTF_8), taken.toSet(), gate) { sha ->
                            try {
                                source.page(sha)
                            } catch (e: PeerError) {
                                null
                            }
                        }
                    }
                }
            }
        }
    }
}
