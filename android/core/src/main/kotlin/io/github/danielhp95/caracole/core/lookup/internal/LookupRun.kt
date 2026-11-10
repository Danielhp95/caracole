package io.github.danielhp95.caracole.core.lookup.internal

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupResult
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.NotYet
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.concurrent.CancellationException

/** A lookup that can't go on (an ignored song, a pick that isn't one), said in the song's stage: get.py's `_Stop`. */
internal class Stop(message: String) : Exception(message)

/** One run of a [Lookup]: get.py's `_Lookup`, its stages over the lookup's [db] (Lookup's KDoc). */
internal class LookupRun(private val lookup: Lookup, private val db: Db) {
    private val request: LookupRequest = lookup.request
    private val pacing = lookup.pacing
    private val started = pacing.monotonic()
    private val now: Instant = pacing.clock().truncatedTo(ChronoUnit.SECONDS)
    private val runId = Pace.lookupRunId(now)
    private val ask = InteractiveAsk(lookup.clients, db, runId, now, lookup.alerts, lookup.cfg)
    private val plain: Asking = SheetFrom(ask)

    private val states = LinkedHashMap<String, String>()
    private val details = LinkedHashMap<String, String>()
    private var files: Map<String, String> = emptyMap()
    private var secondsToSheet: Double? = null
    private var requests: Map<String, Int> = emptyMap()
    private var bug: String? = null
    private var refused: String? = null
    private var songId: Long? = null
    private var display: String = request.display

    private var running: String? = null  // the stage running
    private var sheetFrom: String? = null  // the site the sheet stage said it asks, if it said one
    private var lacuerdaAsked = false
    private var lacuerdaSaid = StageEnd("done", "")  // what LaCuerda's first ask came to
    private var sheetVersion: Long? = null
    private lateinit var overrides: Overrides
    private var found: SongRow? = null
    private val song: SongRow get() = found ?: error("no song yet")

    fun run(): LookupResult {
        report("song", "running")
        overrides = try {
            lookup.readOverrides(db)
        } catch (e: OverridesError) {
            return refuse("Can't read overrides.toml: ${e.message}")
        }
        try {
            lookup.store.ensureCurrentKeys(db)
            try {
                report("song", "done", findSong())
            } catch (e: Stop) {
                return refuse(e.message.orEmpty())
            }
            stage("match") { site(lookup.stages.match) }
            stage("sheet", ::sheet)
            stage("pdf", ::pdf)
            stage("lyrics", ::lyrics)
            stage("ug") { site(lookup.stages.ug, ask.afterTheSheet) }
            stage("lacuerda") { lacuerda(lookup.stages.lacuerda) }
            stage("gtptabs") { site(lookup.stages.gtptabs) }
            stage("harptabs") { site(lookup.stages.harptabs) }
            stage("gametabs") { site(lookup.stages.gametabs) }
            stage("pages", ::pages)
            stage("songbooks", ::songbooks)
            noteLookedUp(song.id)
            ask.recordAnswers()  // a site that answered: a good run
        } finally {
            requests = LinkedHashMap(ask.requests)
            ask.close()
        }
        return result()
    }

    private fun result(): LookupResult =
        LookupResult(songId, display, LinkedHashMap(states), LinkedHashMap(details), files, secondsToSheet,
                     pacing.monotonic() - started, requests, bug, refused)

    // --- reporting ----------------------------------------------------------------------------------------------

    private fun report(name: String, state: String, detail: String = "") {
        states[name] = state
        if (state != "running") details[name] = detail
        lookup.progress.stage(name, state, detail)
    }

    /** One stage: what [work] returns is its end; anything it throws but a stop is a bug, said, and the rest go
     * on. */
    private fun stage(name: String, work: () -> StageEnd) {
        report(name, "running")
        running = name
        val out = try {
            work()
        } catch (e: Throwable) {
            if (e is Stop || e is CancellationException || e is InterruptedException || e is VirtualMachineError) throw e
            val said = "${e::class.simpleName}: ${e.message.orEmpty()}"
            bug = bug ?: "$name: $said"
            report(name, "failed", "a bug in caracole: $said")
            return
        } finally {
            running = null
        }
        val end = done(out)
        report(name, end.state, end.detail)
        checkReadable()
    }

    /** A stage's end as get.py reads one: its None ([LookupWords.NOTHING_TO_ASK]) `done` with no words. */
    private fun done(end: StageEnd): StageEnd = if (end == LookupWords.NOTHING_TO_ASK) StageEnd("done", "") else end

    private fun refuse(why: String): LookupResult {
        refused = why
        report("song", "failed", why)
        for ((name, _) in LookupWords.STAGES.drop(1)) report(name, "skipped", "")
        return result()
    }

    /** The plain envelope, which says in the running sheet stage which site it asks once it asks one, and again when
     * it turns to the other (get.py's `_sheet_from`), for the Requests tab's line and its Sheet step. */
    private inner class SheetFrom(private val inner: Asking) : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> =
            inner.ask(provider, policy) { client ->
                sheetFrom(provider)
                work(client)
            }

        override val requests: Map<String, Int> get() = inner.requests
    }

    private fun sheetFrom(provider: String) {
        if (running != "sheet" || sheetFrom == provider) return
        val said = LookupWords.SHEET_FROM[provider] ?: return
        sheetFrom = provider
        report("sheet", "running", said)
    }

    // --- what can be read ---------------------------------------------------------------------------------------

    /** get.kept_sheet: the song's kept sheet, the human one, else the auto-chords one. */
    private fun keptSheet(): KeptFile? {
        val s = found ?: return null
        val kept = Kept.keptFiles(db, s.id).associateBy { it.name }
        return Versions.SHEET_FILE_NAMES.firstNotNullOfOrNull { kept[it] }
    }

    /** get.readable_files: the sheet's text, and its PDF and viewer page where they are. */
    private fun readableFiles(kept: KeptFile): Map<String, String> {
        val folder = lookup.store.folderOf(song)
        val base = kept.path.substringBeforeLast('/', "")
        val stem = kept.name.removeSuffix(PyPath.suffix(kept.name))
        val out = linkedMapOf("sheet" to kept.path)
        for ((name, file) in listOf("pdf" to "$stem.pdf", "viewer" to "$stem.html")) {
            if (Files.isRegularFile(File(folder, file).toPath())) out[name] = if (base.isEmpty()) file else "$base/$file"
        }
        return out
    }

    /** Say the sheet is readable when one is kept, and again when it, its PDF or its viewer page changes. */
    private fun checkReadable() {
        val kept = keptSheet() ?: return
        val readable = readableFiles(kept)
        if (readable == files && kept.versionId == sheetVersion) return
        val first = secondsToSheet == null
        sheetVersion = kept.versionId
        files = readable
        if (first) secondsToSheet = pacing.monotonic() - started
        lookup.progress.readable(readable, pacing.monotonic() - started)
    }

    // --- the song -----------------------------------------------------------------------------------------------

    private fun findSong(): String {
        val key = Normalize.identityKey(request.artist, request.title)
        if (key in overrides.ignore) {
            throw Stop("${request.display} is ignored (overrides.toml [ignore]). Take it out to fetch it")
        }
        if (!request.tab.isNullOrEmpty()) refuseAnUnusedKind(request.tab)
        var song = Songs.byKey(db, key)
        var said = "in the book"
        if (song == null) {
            song = try {
                lookup.store.add(db, request.artist, request.title, request.album, request.durationMs,
                                 now = Stamps.of(now))
            } catch (e: IllegalArgumentException) {  // a song the phone can't hold, as wanted.txt can't
                throw Stop("Can't add this song: ${e.message}")
            }
            said = LookupWords.ADDED
        }
        if (song.status == "ignored") {
            throw Stop("${song.display} is ignored (overrides.toml [ignore]). Take it out to fetch it")
        }
        val picked = mutableListOf<String>()
        try {
            request.ug?.takeIf { it.isNotEmpty() }?.let { ug ->
                OverrideWriters.addMatch(db, song.display, ug)
                picked += "[match] $ug"
            }
            request.tab?.takeIf { it.isNotEmpty() }?.let { tab ->
                val tabId = OverrideUrls.tabIdFromUrl(tab)
                OverrideWriters.addPin(db, song.display, listOf(tab) + otherPins(song, tabId))
                picked += "[pin] tab $tabId"
            }
            request.lacuerda?.takeIf { it.isNotEmpty() }?.let { url ->
                val pick = OverrideUrls.lacuerdaPickFromUrl(url).url
                OverrideWriters.addLacuerda(db, song.display, pick)
                Versions.updateSong(db, song.id, mapOf("lacuerda_checked_at" to null), Stamps.of(pacing.clock()))
                picked += "[lacuerda] $pick"
            }
            request.harptabs?.takeIf { it.isNotEmpty() }?.let { url ->
                val pick = OverrideUrls.harptabsPickFromUrl(url).url
                OverrideWriters.addHarptabs(db, song.display, pick)
                picked += "[harptabs] $pick"
            }
            request.gametabs?.takeIf { it.isNotEmpty() }?.let { url ->
                val pick = OverrideUrls.gametabsPickFromUrl(url).url
                OverrideWriters.addGametabs(db, song.display, pick)
                picked += "[gametabs] $pick"
            }
            if (picked.isNotEmpty()) overrides = lookup.readOverrides(db)
        } catch (e: OverridesError) {
            throw Stop("Couldn't note your pick in overrides.toml: ${e.message}")
        }
        found = song
        songId = song.id
        display = song.display
        ask.owedSong = song.id
        lookup.progress.song(song.id, song.display)
        return said + if (picked.isNotEmpty()) "; noted in overrides.toml: ${picked.joinToString(", ")}" else ""
    }

    /** get.py's `_refuse_an_unused_kind`: stop before anything is written when the tab asked for is of a type caracole
     * doesn't use (a Guitar Pro file's page, a bass tab's), whose pin would pin nothing. */
    private fun refuseAnUnusedKind(tab: String) {
        val tabId = try {
            OverrideUrls.tabIdFromUrl(tab)
        } catch (_: OverridesError) {
            return  // said as the pin is recorded
        }
        val kind = OverrideUrls.classifyTabUrl(OverrideUrls.pinUrl(tab))
        if (kind != null && kind != OverrideUrls.BARE && kind != OverrideUrls.UNRECOGNIZED) {
            throw Stop("tab $tabId isn't chords, a tab or ukulele chords")
        }
    }

    /** get.py's `_other_pins`: the song's pins that stay beside a tab you pick, as written: those of another kind
     * group (a text tab beside a chords sheet you pick), by the offline index's types; chords and ukulele chords are
     * one group. A pin of the pick's group, or of a tab the index doesn't know on either side, is replaced. */
    private fun otherPins(song: SongRow, tabId: Long): List<String> {
        fun group(tab: Long): Int? {
            val type = db.one("SELECT type FROM ug_index WHERE tab_id = ?", tab) { it.text(0) }
            return PIN_GROUPS.indexOfFirst { type in it }.takeIf { it >= 0 }
        }
        val mine = group(tabId) ?: return emptyList()
        val pasted = overrides.pinUrls[song.key].orEmpty()
        return overrides.pin[song.key].orEmpty().withIndex()
            .filter { (_, pin) -> group(pin).let { it != null && it != mine } }
            .map { (i, pin) -> if (i < pasted.size) pasted[i] else pin.toString() }
    }

    // --- the stages ---------------------------------------------------------------------------------------------

    /** A site's stage, asked through [asking] about the song as it is now; a file it would write where another
     * song keeps one fails it in get.py's words. The song is read again after. [LookupWords.NOTHING_TO_ASK] is
     * get.py's None: kept as it is for the lyrics' `_then` ([nothing]), else `done` with no words, as get.py's stage
     * reads a None. */
    private fun site(stage: SiteStage, asking: Asking = plain, nothing: Boolean = false): StageEnd {
        val current = Songs.byId(db, song.id) ?: song
        found = current
        return try {
            stage.run(StageContext(db, current, overrides, lookup.cfg, lookup.store, asking, now,
                                  lookup.clients.cacheDir))
                .let { if (nothing) it else done(it) }
        } catch (e: SharedFolder) {
            StageEnd("failed", LookupWords.sharedFolder(e))
        } finally {
            found = Songs.byId(db, song.id) ?: found
        }
    }

    /** The LaCuerda song or version picked for the song (`[lacuerda]`), or null. */
    private fun picked(): LaCuerdaPick? = overrides.lacuerda[song.key]

    /** Whether the sheet kept is the LaCuerda one picked. */
    private fun holdsPick(): Boolean {
        val pick = picked() ?: return false
        val kept = keptSheet() ?: return false
        val version = Versions.get(db, kept.versionId) ?: return false
        return version.provider == "lacuerda" && pick.holds(version.tabId)
    }

    /** The sheet: the LaCuerda one picked first; Ultimate Guitar's only when LaCuerda can't give it, the stage then
     * saying why not before what Ultimate Guitar gave. */
    private fun sheet(): StageEnd {
        if (picked() == null) return sheetFromUg()
        val said = lacuerda(lookup.stages.lacuerdaPick).detail
        if (holdsPick()) return StageEnd("done", said)
        val ug = sheetFromUg()
        return StageEnd(ug.state, if (said.isNotEmpty()) "$said; ${ug.detail}" else ug.detail)
    }

    /** Ultimate Guitar's first pass; without a sheet from it, LaCuerda's, when it would be asked tonight. */
    private fun sheetFromUg(): StageEnd {
        val ug = site(lookup.stages.ugSheet)
        if (keptSheet() != null) return ug
        val lc = lacuerda(lookup.stages.lacuerda)
        if (keptSheet() != null) return StageEnd("done", lc.detail)
        return StageEnd(if (ug.state == "done") "skipped" else ug.state, ug.detail)
    }

    /** LaCuerda, asked once a lookup: for the sheet ([stage] its pick's, or its stage's), and again at the lacuerda
     * stage, which then says what that came to. Without a sheet yet, or for a pick, the plain envelope; with one,
     * within [LookupWords.SHEETS_SHARE]. */
    private fun lacuerda(stage: SiteStage): StageEnd {
        if (lacuerdaAsked) return LookupWords.lacuerdaAgain(lacuerdaSaid)
        lacuerdaAsked = true
        val first = keptSheet() == null || picked() != null
        val out = site(stage, if (first) plain else ask.afterTheSheet)
        lacuerdaSaid = out
        return out
    }

    /** The song's pages (render.py's `render_all` for this song alone: milestone 5's PhoneRender), or none. */
    private fun pdf(): StageEnd {
        if (keptSheet() == null) return StageEnd("skipped", LookupWords.NO_SHEET_YET)
        if (lookup.pages === SongPages.NONE) return StageEnd("skipped", LookupWords.NO_PDFS)
        val stats = lookup.pages.render(db, listOf(song.id), null)
        val failed = stats.failed[song.id] ?: stats.failed.values.firstOrNull()
        if (failed != null) return StageEnd("failed", failed)
        return StageEnd("done", if (stats.written > 0) LookupWords.PAGES_MADE else LookupWords.UP_TO_DATE)
    }

    /** LRCLIB, then Megalobiz for the timed lyrics LRCLIB left the song without, then AZLyrics for a song still
     * without any. */
    private fun lyrics(): StageEnd {
        var out = site(lookup.stages.lrclib)
        out = then(out, site(lookup.stages.megalobiz, nothing = true))
        return then(out, site(lookup.stages.azlyrics, nothing = true))
    }

    private fun then(out: StageEnd, then: StageEnd): StageEnd {
        if (then == LookupWords.NOTHING_TO_ASK) return out
        val current = Songs.byId(db, song.id) ?: song
        found = current
        return LookupWords.then(out, then, current.lyricsStatus == "found")
    }

    /** The song's pages again where it keeps a sheet or a harmonica tab (a song with no sheet's too), and the library
     * page, which the phone makes as it is asked for. */
    private fun pages(): StageEnd {
        if (lookup.pages !== SongPages.NONE && (keptSheet() != null || keepsHarmonicaTabs())) {
            lookup.pages.render(db, listOf(song.id), null)
        }
        return StageEnd("done", LookupWords.LIBRARY_PAGE)
    }

    /** inbox.harmonica_files of the song: whether it keeps a harmonica tab. */
    private fun keepsHarmonicaTabs(): Boolean =
        db.query("SELECT f.name FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ? AND f.song_id = ?",
                 HARMONICA_KIND, song.id) { it.text(0) }.any { it != null && PyRe.fullmatch(HARMONICA_FILE, it) != null }

    /** The songbooks that list the song, made again; none while milestone 6's songbooks aren't on the phone. */
    private fun songbooks(): StageEnd {
        if (lookup.songbooks === SongbookPages.NONE) return StageEnd("skipped", NotYet.WORDS)
        return SongbooksStage.end(read = { Songbooks.all(db) }, leaves = !request.songbooks,
                                  listing = { books -> Songbooks.listing(db, books, song).map { it.name } },
                                  running = { names -> lookup.progress.stage("songbooks", "running", names) },
                                  render = { names -> lookup.songbooks.render(db, names) })
    }

    /** ug/fetch.py's note_looked_up: the last songs a lookup fetched, newest last (kv `lookup:songs`). */
    private fun noteLookedUp(id: Long) {
        val was = db.kvGet(LOOKED_UP)?.let { runCatching { PyJson.loads(it) }.getOrNull() } as? JsonArray
        val ids = was.orEmpty().mapNotNull { (it as? JsonPrimitive)?.longOrNull }.filter { it != id }
        db.kvSetJson(LOOKED_UP, JsonArray((ids + id).takeLast(LOOKED_UP_KEPT).map(::JsonPrimitive)))
    }

    private companion object {
        /** get.py's `_other_pins` groups, the kinds a pin replaces: ug/fetch.py's CHORDS_KINDS + UKULELE_KINDS (either
         * is the sheet), and TAB_KINDS. */
        val PIN_GROUPS: List<Set<String>> = listOf(setOf("chords", "ukulele"), setOf("tabs"))
        const val HARMONICA_KIND = "harmonica"  // inbox.HARMONICA_KIND
        val HARMONICA_FILE = PyRegex.compile("""harmonica-(\d+)\.txt""")  // inbox.HARMONICA_FILE
        const val LOOKED_UP = "lookup:songs"  // ug/fetch._LOOKED_UP
        const val LOOKED_UP_KEPT = 50
    }
}
