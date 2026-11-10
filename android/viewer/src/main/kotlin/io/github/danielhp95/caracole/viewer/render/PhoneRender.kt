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
 * the song unit's digest it was made at (WrittenPages), a page that leaves deleted while it is as written; its
 * progressions (kv `render:progressions:<song id>`); its info.json (InfoJson); and kv `render:<song id>:phone`, the
 * unit's digest and this [build] it was made at, and its sheet's script, which the library page's cards read
 * ([chineseSongs]). No PDF is made, so no page links one, and no PDF's record is written. A song whose pages the
 * mirror serves at its unit's digest (the computer made them of the song as the phone holds it) gets its
 * progressions and its script alone, the phone's own pages of it forgotten.
 *
 * It is the lookup's pdf stage ([seam]), what follows a sync's take ([afterSync]), and the render job (PhoneKinds'
 * render kind, keyed by [build]), which the phone queues itself, never this class: at its start when [stale]
 * (Phone.start, once the app has wired the queue), and after a take that owes pages; the job runs [renderStale],
 * which yields between two songs (its `between`, JobContext.yieldToQueued: the lookups queued meanwhile run first),
 * holding no write. [version] is the app's, part of [build]. Open, so a test of the phone's wiring can stand a stale
 * one in its place.
 */
open class PhoneRender(val database: Database, val libraryDir: File, val mirror: Mirror?, val version: String) :
    SongPages {
    private val store = LibraryStore(libraryDir)
    private val stamp: String by lazy { RenderBuild.of(version) }

    /** Phase A (waiting on lanes pages, harmonica-page and version-progressions): the lookup's seam, [stale] and
     * [afterSync] stay neutral until the page builders they call have landed, so no lookup, start or take reaches a
     * builder that isn't there; [render] and [renderStale] are whole. */
    private val landed = false

    /** The songs' pages made, each in the caller's write (the lookup's: render_all(song_ids=…) for its song), newest
     * added first; [between] runs between two songs, after which the overrides and each song are read again. */
    override fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats {
        store.ensureCurrentKeys(db)
        PlainLyrics.onto(db, libraryDir, Overrides.read(db), only = songIds.toSet())
        var overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
        val served = served()
        val tally = Tally()
        for ((n, listed) in songsOf(db, songIds).withIndex()) {
            var song = listed
            if (n > 0 && between != null) {
                between()
                overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
                song = Songs.byId(db, listed.id) ?: continue // merged into another song meanwhile
            }
            if (ignored(song, overrides)) continue
            tally.count(song.id, renderSong(db, song, overrides, served))
        }
        return tally.stats()
    }

    /** What the lookup's pdf stage calls (Assembly gives it as PhoneParts.pages): this, once the page builders have
     * landed; [SongPages.NONE] before, so the stage says get.py's no-PDF words. */
    open val seam: SongPages get() = if (landed) this else SongPages.NONE

    /** Whether the phone owes pages ([owed]): a song made by another build than this one, changed since (its unit
     * moved: a take, a change on the phone), or never made. */
    open fun stale(): Boolean = landed && database.read { db -> owed(db).isNotEmpty() }

    /** The phone's build stamp: the viewer's assets and data hashed, and the app's [version] (RenderBuild). */
    open fun build(): String = stamp

    /** The pages owed made ([owed]'s songs, as listed when it starts; one a lookup made meanwhile passed over), each
     * in a write of its own, [between] two songs holding none, [progress] told how far (done, total); then kv
     * `phone:render-build`, the build the phone's pages were last made by. */
    open fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit = { _, _ -> }): RenderStats {
        database.writeBlocking { db ->
            store.ensureCurrentKeys(db)
            PlainLyrics.onto(db, libraryDir, Overrides.read(db))
            OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
        }
        val owed = database.read { db -> owed(db).map { it.id } }
        val served = served()
        val tally = Tally()
        progress(0, owed.size)
        for ((n, id) in owed.withIndex()) {
            if (n > 0) between()
            database.writeBlocking { db ->
                val song = Songs.byId(db, id) ?: return@writeBlocking
                val overrides = OwnVersions.upgraded(db, libraryDir, Overrides.read(db))
                if (!ignored(song, overrides) && owes(db, song)) tally.count(id, renderSong(db, song, overrides, served))
            }
            progress(n + 1, owed.size)
        }
        database.writeBlocking { db -> db.kvSet(RenderNames.BUILD_KEY, build()) }
        return tally.stats()
    }

    /** After a sync's take, inside the sync's job (lane written-pages forgets there the phone's pages of the units
     * it moved): whether pages are owed now. It makes none itself: the phone queues the render job for them after the
     * sync, so the sync ends when its stages do and a lookup goes first. */
    open fun afterSync(): Boolean = stale()

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

    /** One song's pass ([SongPass]), its records then: its pages' unit, the phone's record, its info.json. */
    private fun renderSong(db: Db, song: SongRow, overrides: Overrides, served: Map<String, Set<String>>): Done {
        val unit = RenderNames.unitOf(song.key)
        val digest = Units.digestOf(db, unit) ?: ""
        val mirrored = digest in served[unit].orEmpty()
        val pass = SongPass(db, libraryDir, overrides, PhoneConfig.read(db).rank, ::youtubeMark, song, digest)
        var why: String? = null
        try {
            if (mirrored) {
                pass.facts()
                WrittenPages.forget(db, song.id, WrittenPages.record(db, song.id).keys, store.folderOf(song))
            } else {
                pass.pages()
            }
        } catch (e: RenderError) {
            why = "${song.display}: ${e.message}"
        } catch (e: IOException) {
            why = "${song.display}: ${e.message}"
        }
        WrittenPages.restamp(db, song.id, digest)
        WrittenPages.noteRendered(db, song.id, Rendered(digest, build(), pass.script))
        if (!mirrored) {
            try {
                InfoJson.write(db, libraryDir, Songs.byId(db, song.id) ?: song)
            } catch (e: IOException) {
                if (why == null) why = "${song.display}: ${e.message}"
            }
        }
        return Done(pass.wrote, why ?: pass.failures.firstOrNull())
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

    /** Each song unit the mirror holds a page of, with the digests it was made at (each entry's). */
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
