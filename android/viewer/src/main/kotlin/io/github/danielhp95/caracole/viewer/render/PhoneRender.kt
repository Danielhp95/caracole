package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.viewer.render.internal.RenderError
import io.github.danielhp95.caracole.viewer.render.internal.SongPass
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/**
 * The phone renders its own pages: render.py's page path with no PDF (tests/helpers/phone_render.py, its reference),
 * for the songs no mirror page serves at their unit's digest, and every song's progressions recorded.
 *
 * A song's pass ([render], [renderStale]) is render_all's for it, after the auto sheets took the lyrics that came after
 * them ([PlainLyrics]) and the own versions are as they play now ([OwnVersions]): the pages of the versions kept beside
 * its sheet (`version-<tab>.html`), each sheet's .cho and page (`sheet.cho`, `sheet.html`; an auto sheet's beside it,
 * which offers no export and takes the song's version but its shapes and swaps; or alone), the pages of its harmonica
 * tabs (`harmonica-N.html`), each written only when its bytes change and recorded in kv `render:files:<song id>` with
 * the song unit's digest it was made at (WrittenPages: an entry the pass didn't write or find as written keeps the
 * digest it was made at), a page that leaves deleted while it is as written; its progressions (kv
 * `render:progressions:<song id>`); its info.json (InfoJson); and kv `render:<song id>:phone`, the unit's digest and
 * this [build] it was made at, and its sheet's script, which the library page's cards read ([chineseSongs]). No PDF is
 * made, so no page links one, and no PDF's record is written. A song whose pages the mirror serves at its unit's
 * digest (the computer made them of the song as the phone holds it) gets its progressions, its script and its
 * info.json alone, the phone's own pages of it forgotten.
 *
 * A song's pass that fails is the song's alone: its why (render.py's log line, "<song>: <why>", or "no viewer for
 * <song>: …" for a page; "<song>: a bug in caracole: …" for anything else, a StackOverflowError too) is counted in
 * [RenderStats.failed], the pages it made are kept, and the song is stamped all the same, so the next start doesn't
 * fail at it again: a new build, or a change to the song, makes it again. That why is the lookup's pdf stage's
 * failed detail on the phone, as get.py's "chordpro couldn't make the PDF" is the computer's.
 *
 * It is the lookup's pdf stage ([seam]), what follows a sync's take ([afterSync]: the pages the take superseded
 * forgotten, those owed made by the render job), and the render job (PhoneKinds' render kind, keyed by [build]),
 * which the phone queues itself, never this class: at its start when [stale] (Phone.start, once the app has wired
 * the queue), and after a take that owes pages; the job runs [renderStale], which yields between two songs (its
 * `between`, JobContext.yieldToQueued: the lookups queued meanwhile run first), holding no write. [version] is the
 * app's, part of [build] (RenderBuild: the APK's code and data too). Open, so a test of the phone's wiring can stand
 * a stale one in its place.
 */
open class PhoneRender(val database: Database, val libraryDir: File, val mirror: Mirror?, val version: String) :
    SongPages {
    private val store = LibraryStore(libraryDir)
    private val stamp: String by lazy { RenderBuild.of(version) }

    /** The songs' pages made, each in the caller's write (the lookup's: render_all(song_ids=…) for its song), newest
     * added first; [between] runs between two songs, after which the overrides and each song are read again. It runs
     * inside the caller's write, so it must never yield to the queue (a lookup it ran would wait for that write):
     * [renderStale] is the render job's, which holds none between two songs. */
    override fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats {
        store.ensureCurrentKeys(db)
        PlainLyrics.onto(db, libraryDir, Overrides.read(db), only = songIds.toSet())
        var overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
        val pass = Pass()
        val tally = Tally()
        for ((n, listed) in songsOf(db, songIds).withIndex()) {
            var song = listed
            if (n > 0 && between != null) {
                between()
                overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
                song = Songs.byId(db, listed.id) ?: continue // merged into another song meanwhile
            }
            if (ignored(song, overrides)) continue
            tally.count(song.id, renderSong(db, song, overrides, pass))
        }
        return tally.stats()
    }

    /** What the lookup's pdf stage calls (Assembly gives it as PhoneParts.pages): this. */
    open val seam: SongPages get() = this

    /**
     * Whether the phone owes pages, as cheaply as it can tell at the app's start (one query, no song's digest): a song
     * not ignored that this [build] never made (none made it, or another build did), or kv `phone:render-build` not
     * this build's while the library has a song (a new build whose pass never ended, or [owe]). A song changed since
     * it was made is the render job's to find ([owed]): a take's are [afterSync]'s, and a change on the phone makes its
     * song's pages again (a lookup's pdf stage) or calls [owe].
     */
    open fun stale(): Boolean = database.read { db ->
        val overrides = Overrides.read(db)
        val songs = db.query(
            "SELECT s.key, CASE WHEN json_valid(kv.value) THEN json_extract(kv.value, '$.build') END " +
                "FROM songs s LEFT JOIN kv ON kv.key = 'render:' || s.id || '${RenderNames.PHONE_KV}' " +
                "WHERE s.status != ?", RenderNames.IGNORED) { it.text(0)!! to it.text(1) }
            .filter { (key, _) -> key !in overrides.ignore }
        songs.isNotEmpty() && (db.kvGet(RenderNames.BUILD_KEY) != build() || songs.any { (_, made) -> made != build() })
    }

    /** The phone's build stamp: the viewer's assets and data hashed, the APK's code, and the app's [version]
     * (RenderBuild). */
    open fun build(): String = stamp

    /** The pages owed made again at the next start (or the next render job): kv `phone:render-build` forgotten, so
     * [stale] is true until a pass ends. A change on the phone that moves a song's pages without making them calls it,
     * in its own write. */
    fun owe(db: Db) {
        db.kvDelete(RenderNames.BUILD_KEY)
    }

    /** The pages owed made ([owed]'s songs, as listed when it starts; one a lookup made meanwhile passed over), each
     * in a write of its own, [between] two songs holding none, [progress] told how far (done, total); then kv
     * `phone:render-build`, the build the phone's pages were last made by. A song whose pass fails costs the others
     * nothing (its why in the stats' `failed`). */
    open fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit = { _, _ -> }): RenderStats {
        database.writeBlocking { db ->
            store.ensureCurrentKeys(db)
            PlainLyrics.onto(db, libraryDir, Overrides.read(db))
            OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
        }
        val owed = database.read { db -> owed(db).map { it.id } }
        val pass = Pass()
        val tally = Tally()
        progress(0, owed.size)
        for ((n, id) in owed.withIndex()) {
            if (n > 0) between()
            database.writeBlocking { db ->
                val song = Songs.byId(db, id) ?: return@writeBlocking
                val overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
                if (!ignored(song, overrides) && owes(db, song)) tally.count(id, renderSong(db, song, overrides, pass))
            }
            progress(n + 1, owed.size)
        }
        database.writeBlocking { db -> db.kvSet(RenderNames.BUILD_KEY, build()) }
        return tally.stats()
    }

    /** After a sync's take, inside the sync's job, holding no write: the phone's pages the take superseded forgotten
     * ([forgetSuperseded]), then whether pages are owed now ([owed], each song's digest read), [owe]d if so, so that
     * an app stopped before the render job ran makes them at its next start. It makes none itself: the phone queues
     * the render job for them after the sync, so the sync ends when its stages do and a lookup goes first. */
    open fun afterSync(): Boolean {
        database.writeBlocking { db -> forgetSuperseded(db) }
        val owed = database.read { db -> owed(db).isNotEmpty() }
        if (owed) database.writeBlocking { db -> owe(db) }
        return owed
    }

    /**
     * The phone's pages a take superseded, forgotten, each deleted while it is still as written (WrittenPages.forget,
     * render._forget_written(folder=)): a song's page made at a digest its unit has moved from, once the mirror serves
     * the song at its digest now (the computer made its pages of the song as the phone holds it); a songbook's the
     * same way by kv `songbook:<folder>`, and every file of a folder no songbook has any more. A song's page that
     * moved where the mirror serves none stays until the render job makes the song's pages again, never served
     * meanwhile (LibraryFiles serves the phone's page only while it is current). A song a take moved to another
     * folder had its pages deleted by the take itself (Removal.phonesWritten), and a song it removed went with them.
     */
    fun forgetSuperseded(db: Db) {
        val served = served()
        val songs = db.query("SELECT key FROM kv WHERE key GLOB '${RenderNames.FILES_KEY}[0-9]*'") { it.text(0)!! }
            .mapNotNull { it.removePrefix(RenderNames.FILES_KEY).toLongOrNull() }
        for (id in songs) {
            val song = Songs.byId(db, id) ?: continue
            val unit = RenderNames.unitOf(song.key)
            val now = Units.digestOf(db, unit) ?: continue
            if (now !in served[unit].orEmpty()) continue
            val moved = WrittenPages.record(db, id).keys.filter { WrittenPages.written(db, id, it)?.unitDigest != now }
            if (moved.isNotEmpty()) WrittenPages.forget(db, id, moved, store.folderOf(song))
        }
        for (folder in WrittenPages.songbookFolders(db)) {
            val names = WrittenPages.songbook(db, folder).keys
            val unit = WrittenPages.songbookUnit(db, folder)
            if (unit == null) {
                WrittenPages.forgetSongbook(db, folder, names, libraryDir, gone = true)
                continue
            }
            val now = WrittenPages.songbookDigest(db, unit) ?: continue
            if (now !in served[unit].orEmpty()) continue
            val moved = names.filter { WrittenPages.songbookWritten(db, folder, it)?.unitDigest != now }
            if (moved.isNotEmpty()) WrittenPages.forgetSongbook(db, folder, moved, libraryDir)
        }
    }

    /** The songs the phone owes a pass over, newest added first: every song not ignored whose record
     * (`render:<song id>:phone`) isn't of its unit's digest now and this [build]. */
    fun owed(db: Db): List<SongRow> {
        val overrides = Overrides.read(db)
        return Songs.list(db).filter { !ignored(it, overrides) && owes(db, it) }
    }

    /** Whether the song's record is of another unit's digest or another build than now's. */
    private fun owes(db: Db, song: SongRow): Boolean {
        val made = WrittenPages.rendered(db, song.id) ?: return true
        return made.build != build() || made.unit != Units.digestOf(db, RenderNames.unitOf(song.key))
    }

    /** What one pass over songs reads once: the units the mirror serves, and YouTube's mark. */
    private inner class Pass {
        val served: Map<String, Set<String>> = served()
        private val youtube: JsonObject by lazy { youtubeMark() }

        fun mark(): JsonObject = youtube
    }

    /** One song's pass ([SongPass]), then the phone's record of it and its info.json; what fails is the song's
     * alone, said as [attempt] says it. */
    private fun renderSong(db: Db, song: SongRow, overrides: Overrides, pass: Pass): Done {
        val unit = RenderNames.unitOf(song.key)
        val digest = Units.digestOf(db, unit) ?: ""
        val mirrored = digest in pass.served[unit].orEmpty()
        val songPass = SongPass(db, libraryDir, overrides, PhoneConfig.read(db).rank, pass::mark, song, digest)
        val why = attempt(song) {
            if (mirrored) {
                songPass.facts()
                WrittenPages.forget(db, song.id, WrittenPages.record(db, song.id).keys, store.folderOf(song))
            } else {
                songPass.pages()
            }
        }
        WrittenPages.noteRendered(db, song.id, Rendered(digest, build(), songPass.script))
        val info = attempt(song) { InfoJson.write(db, libraryDir, Songs.byId(db, song.id) ?: song) }
        return Done(songPass.wrote, why ?: info ?: songPass.failures.firstOrNull())
    }

    /** [block], and null; or why it failed, as render_all logs a song's failure: a sheet that can't be read or a file
     * that can't be written ("<song>: <why>"), else a bug (render.py's would stop the pass; the phone's is the song's
     * alone, StackOverflowError, Python's RecursionError, among them). */
    private inline fun attempt(song: SongRow, block: () -> Unit): String? = try {
        block()
        null
    } catch (e: RenderError) {
        "${song.display}: ${e.message}"
    } catch (e: IOException) {
        "${song.display}: ${e.message}"
    } catch (e: Exception) {
        "${song.display}: ${RenderNames.BUG}: $e"
    } catch (e: StackOverflowError) {
        "${song.display}: ${RenderNames.BUG}: $e"
    }

    /** What a song's pass came to: whether a page was written, and why it failed. */
    private class Done(val wrote: Boolean, val why: String?)

    private class Tally {
        var written = 0
        var unchanged = 0
        val failed = LinkedHashMap<Long, String>()

        fun count(songId: Long, done: Done) {
            when {
                done.why != null -> failed[songId] = done.why
                done.wrote -> written++
                else -> unchanged++
            }
        }

        fun stats() = RenderStats(written, unchanged, failed)
    }

    /** The songs of [ids] the library still has, newest added first as list_songs gives them (render._songs_of). */
    private fun songsOf(db: Db, ids: Collection<Long>): List<SongRow> =
        ids.mapNotNull { Songs.byId(db, it) }.distinctBy { it.id }
            .sortedWith(compareByDescending<SongRow> { it.addedAt }.thenByDescending { it.id })

    private fun ignored(song: SongRow, overrides: Overrides) =
        song.status == RenderNames.IGNORED || song.key in overrides.ignore

    /** Each song unit the mirror holds a page of, with the digests it was made at (each entry's): the computer's
     * manifest's. A page a `.caracole` file's layer holds (lane sync-phone's Mirror.pageFor) isn't read here yet: once
     * that lands, a song such a layer serves at its digest is one the phone needn't make (written-pages' to switch). */
    private fun served(): Map<String, Set<String>> {
        val entries = mirror?.manifest()?.entries ?: return emptyMap()
        val out = HashMap<String, MutableSet<String>>()
        for (e in entries) {
            val unit = e.unit ?: continue
            val digest = e.digest ?: continue
            if (e.isPage) out.getOrPut(unit) { HashSet() }.add(digest)
        }
        return out
    }

    /** icons.page_icon(…, YOUTUBE), as the computer's library page carries it in the mirror (its data's `icons`),
     * else as a library with no icon kept has it (caracole/page/empty_library.json). */
    private fun youtubeMark(): JsonObject =
        (mirroredIcons() ?: EMPTY_ICONS)[RenderNames.YOUTUBE] as? JsonObject ?: JsonObject(emptyMap())

    private fun mirroredIcons(): JsonObject? {
        val mirror = mirror ?: return null
        val start = mirror.manifest()?.start ?: return null
        val page = mirror.lookup(start) ?: return null
        val bytes = try {
            page.file.readBytes()
        } catch (_: IOException) {
            return null
        }
        return dataBlock(bytes)?.get("icons") as? JsonObject
    }

    companion object {
        /** kv render:<song id>:phone's songs whose sheet is Chinese (render.chinese_songs, the phone's): the
         * library page shows their names in the characters the viewer shows Chinese in. */
        fun chineseSongs(db: Db): Set<Long> =
            db.query("SELECT key FROM kv WHERE key GLOB 'render:[0-9]*:phone' AND json_valid(value) " +
                         "AND json_type(value, '$.script') = 'text'") { it.text(0)!! }
                .mapNotNull { it.removePrefix("render:").removeSuffix(RenderNames.PHONE_KV).toLongOrNull() }.toSet()

        private const val OPEN = "<script type=\"application/json\" id=\"songs\">"
        private const val CLOSE = "</script>"

        private val EMPTY_ICONS: JsonObject by lazy {
            val path = "caracole/page/empty_library.json"
            val stream = PhoneRender::class.java.classLoader?.getResourceAsStream(path)
                ?: throw IllegalStateException("$path isn't on the classpath")
            (Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }) as JsonObject)["icons"]
                as? JsonObject ?: JsonObject(emptyMap())
        }

        /** The library page's data block (library_page._DATA's), or null for a page that holds none it can read. */
        private fun dataBlock(page: ByteArray): JsonObject? {
            val text = try {
                Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(page)).toString()
            } catch (_: CharacterCodingException) {
                return null
            }
            val start = text.indexOf(OPEN).takeIf { it >= 0 }?.plus(OPEN.length) ?: return null
            val end = text.indexOf(CLOSE, start).takeIf { it >= 0 } ?: return null
            return try {
                Json.parseToJsonElement(text.substring(start, end)) as? JsonObject
            } catch (_: IllegalArgumentException) {
                null
            }
        }
    }
}
