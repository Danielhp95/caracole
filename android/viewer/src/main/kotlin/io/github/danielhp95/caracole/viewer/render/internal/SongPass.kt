package io.github.danielhp95.caracole.viewer.render.internal

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.inbox.HarmonicaFile
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.SheetVersion
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.viewer.chinese.Hanzi
import io.github.danielhp95.caracole.viewer.chinese.ViewerPinyin
import io.github.danielhp95.caracole.viewer.harpfit.HarpFit
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.pages.HarmonicaPage
import io.github.danielhp95.caracole.viewer.pages.SheetPage
import io.github.danielhp95.caracole.viewer.pages.ViewerInputs
import io.github.danielhp95.caracole.viewer.progressions.Progressions
import io.github.danielhp95.caracole.viewer.render.RenderNames
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.SongKey
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.NoSuchFileException
import io.github.danielhp95.caracole.core.library.Versions as Rows

/**
 * One song's pass of render.py's page path with no PDF (`_render_song` and what it calls), as the phone makes a song's
 * pages: the pages of the versions kept beside the sheet, each sheet's .cho and page (the human one, then an auto one
 * beside it, or alone), then the pages of its harmonica tabs, whatever came of the sheets; every file written only when
 * its bytes change and recorded at the unit digest [unit] (WrittenPages), a page that leaves forgotten, deleted while it
 * is as written. [facts] alone records what the library finds the song by (its progressions and its sheet's script),
 * for a song whose pages the mirror serves.
 *
 * What fails a page is said in render.py's words ([failures], the first the song's why), and costs the song's other
 * pages nothing; a sheet that can't be read is a [RenderError], which stops the song's sheets (its tabs' pages are
 * still made), as render_all's `except (RenderError, OSError)`.
 */
internal class SongPass(
    private val db: Db,
    private val libraryDir: File,
    private val overrides: Overrides,
    private val rank: RankPolicy,
    private val mark: () -> JsonObject,
    private val song: SongRow,
    private val unit: String,
) {
    private val folder: File = LibraryStore(libraryDir).folderOf(song)

    /** Whether a .cho or a page was written (its bytes changed). */
    var wrote: Boolean = false
        private set

    /** What failed, each as render.py logs it ("no viewer for Artist - Title: …"). */
    val failures = ArrayList<String>()

    /** The characters the song's sheet's Chinese is written in, from the sheet its progressions are read from. */
    var script: String? = null
        private set

    private fun fail(why: String) {
        failures.add("no viewer for ${song.display}: $why")
    }

    // --- the song's progressions and script alone -------------------------------------------------------------------

    /** The song's progressions and its sheet's script, from its human sheet, else its auto sheet; none for a song
     * with neither (or a sheet that can't be read). */
    fun facts() {
        val files = Kept.keptFiles(db, song.id).associateBy { it.name }
        val human = files[RenderNames.HUMAN_SHEET]
        val auto = files[RenderNames.AUTO_SHEET]
        if (human == null && auto == null) {
            Progressions.forget(db, song.id)
            return
        }
        val (humanKey, autoKey) = MusicKeys.sheetKeys(db, libraryDir, song.id)
        val sheet = try {
            if (human != null) Sources.human(db, libraryDir, human) else Sources.auto(db, libraryDir, auto!!)
        } catch (_: RenderError) { // its pages are the computer's, which say what they can of it
            Progressions.forget(db, song.id)
            return
        }
        noteProgressions(Sources.cho(song, sheet), if (human != null) humanKey else autoKey)
    }

    // --- render._render_song --------------------------------------------------------------------------------------

    fun pages() {
        val files = Kept.keptFiles(db, song.id).associateBy { it.name }
        val human = files[RenderNames.HUMAN_SHEET]
        val auto = files[RenderNames.AUTO_SHEET]
        val versions = SheetVersions.inLibrary(db, song.id, rank)
        val pins = SheetVersions.sheetPins(db, song.id, overrides.pin[song.key].orEmpty())
        val listed = versionsData(versions, human ?: auto, pinned = pins.isNotEmpty())
        val guitar = guitarNames()
        val tabs = HarmonicaFiles.of(db, song.id)
        val harmonica = tabs.map { f ->
            JsonObject(linkedMapOf<String, JsonElement>(
                "name" to JsonPrimitive(f.name), "href" to JsonPrimitive(PyUrl.quote(f.name, safe = "")),
                "page" to JsonPrimitive(PyUrl.quote(f.page, safe = ""))).apply {
                f.key?.takeIf { it.isNotEmpty() }?.let { put("key", JsonPrimitive(it)) }
            })
        }
        renderVersions(files, versions, listed, guitar)
        val (humanKey, autoKey) = if (human != null || auto != null) MusicKeys.sheetKeys(db, libraryDir, song.id)
                                  else null to null
        val chosen = versions.firstOrNull { it.chosen }?.tabId
        var primary: Pair<String, SongKey?>? = null
        val harps = LinkedHashMap<String, Int>()

        fun render(kept: KeptFile, sheet: SheetSource, beside: Boolean, listing: JsonObject?) {
            val found = if (sheet.auto) autoKey else humanKey
            val text = Sources.cho(song, sheet)
            val isPrimary = !sheet.auto || human == null
            if (isPrimary) {
                if (primary == null) primary = text to found
                harps.putAll(tabHarps(tabs, files, text, found))
            }
            var played = Versions.ownVersion(overrides, song, text, found?.key, found?.source)
            if (beside) played = played.copy(at = emptyMap(), alt = emptyMap())
            val video = sheet.video?.let(::videoData)
            renderSheet(kept, text, played,
                        start = if (song.key in overrides.version) exportQuery(played) else null,
                        key = found, export = !beside, primary = isPrimary, versions = listing, guitar = guitar,
                        harmonica = harmonica.map { h ->
                            val harp = harps[(h["name"] as JsonPrimitive).content]
                            if (harp == null) h else JsonObject(LinkedHashMap(h).apply { put("harp", JsonPrimitive(harp)) })
                        },
                        video = video, viewerText = if (video != null) Sources.cho(song, sheet, credit = false) else null)
        }

        try {
            if (human != null) {
                render(human, Sources.human(db, libraryDir, human), beside = false, listing = onPage(listed, chosen))
                if (auto == null) { // no auto sheet now: its outputs go
                    for (name in RenderNames.AUTO_OUTPUTS + RenderNames.TRADITIONAL_PDFS.getValue(RenderNames.AUTO_SHEET)) {
                        LibraryReads.unlink(File(folder, name))
                    }
                    db.kvDelete("render:${song.id}:auto")
                    db.kvDelete("render:${song.id}:auto:trad")
                    WrittenPages.forget(db, song.id, RenderNames.AUTO_OUTPUTS)
                }
            } else {
                // _drop_human_outputs: the .cho and the page made of a human sheet the song keeps no longer, while
                // they are as written (the phone keeps no PDF record, so no PDF of it goes)
                WrittenPages.forget(db, song.id, listOf(RenderNames.HUMAN_OUTPUTS[0], RenderNames.HUMAN_OUTPUTS[2]), folder)
                if (auto == null) Progressions.forget(db, song.id)
            }
            if (auto != null) {
                val beside = human != null
                render(auto, Sources.auto(db, libraryDir, auto), beside = beside,
                       listing = if (beside) null else onPage(listed, null))
            }
        } finally { // the tabs' pages, whatever came of the sheets: with the sheet's text read, if it was
            val back = when {
                human != null -> RenderNames.HUMAN_OUTPUTS[2]
                auto != null -> RenderNames.AUTO_OUTPUTS[2]
                else -> null
            }
            renderHarmonica(tabs, files, primary, back)
        }
    }

    /** render._versions_data: what every page of the song says of its UG chords versions (sheet_versions.as_data with
     * `sheet`, the provider of the sheet the title opens, and `pinned`); null when UG lists no chords version of it. */
    private fun versionsData(versions: List<SheetVersion>, one: KeptFile?, pinned: Boolean): JsonObject? {
        if (versions.isEmpty()) return null
        val provider = one?.let { Rows.get(db, it.versionId)?.provider }
        return JsonObject(LinkedHashMap(SheetVersions.asData(versions, versions.size)).apply {
            put("sheet", provider?.let(::JsonPrimitive) ?: kotlinx.serialization.json.JsonNull)
            put("pinned", JsonPrimitive(pinned))
        })
    }

    /** render._on_page: [listed] as one page holds it, each entry's `this` true on the page's own ([tab]'s). */
    private fun onPage(listed: JsonObject?, tab: String?): JsonObject? {
        if (listed == null) return null
        val list = (listed["list"] as kotlinx.serialization.json.JsonArray).map { v ->
            val entry = v as JsonObject
            val mine = tab != null && (entry["tab"] as? JsonPrimitive)?.content == tab
            JsonObject(LinkedHashMap(entry).apply { put("this", JsonPrimitive(mine)) })
        }
        return JsonObject(LinkedHashMap(listed).apply { put("list", kotlinx.serialization.json.JsonArray(list)) })
    }

    /** The song's Guitar Pro files the Guitar Pro page shows (inbox.guitar_files' `in_browser`), each page links. */
    private fun guitarNames(): List<String> = try {
        GuitarFiles.of(db, song.id).filter { it.inBrowser }.map { it.name }
    } catch (_: NotImplementedError) {
        emptyList() // Phase A: waiting on lane guitar-alphatab, whose GuitarFiles.of this is
    }

    /** render.export_query: the version as an address that always says its `t`. */
    private fun exportQuery(v: Version): String {
        val rest = Versions.query(v).split("&").filter { it.isNotEmpty() && !it.startsWith("t=") }
        return (listOf("t=${v.t}") + rest).joinToString("&")
    }

    /** render._video_data: the video an auto sheet's audio came from, as its page's data gives it, with YouTube's mark
     * as the library page draws it ([mark]). */
    private fun videoData(video: Video): JsonObject = JsonObject(linkedMapOf(
        "title" to JsonPrimitive(video.title.ifEmpty { video.id }), "href" to JsonPrimitive(video.url),
        "channel" to JsonPrimitive(video.channel), "mark" to mark()))

    // --- the versions kept beside the sheet ---------------------------------------------------------------------------

    /** render._render_versions: a page for each version kept beside the sheet, `version-<tab>.html`; the page of one
     * no longer kept goes while it is as written. */
    private fun renderVersions(files: Map<String, KeptFile>, versions: List<SheetVersion>, listed: JsonObject?,
                               guitar: List<String>) {
        val pages = LinkedHashMap<String, SheetVersion>()
        for (v in versions) if (v.page != null && v.page == SheetVersions.versionNames(v.tabId).third) pages[v.page!!] = v
        for ((page, v) in pages) renderVersion(files, v, page, onPage(listed, v.tabId), guitar)
        val left = WrittenPages.record(db, song.id).keys.filter { SheetVersions.tabOf(it) != null && it !in pages }
        WrittenPages.forget(db, song.id, left, folder)
    }

    private fun renderVersion(files: Map<String, KeptFile>, v: SheetVersion, page: String, listed: JsonObject?,
                              guitar: List<String>) {
        val doc = SheetVersions.versionNames(v.tabId).second
        val kept = files[doc] ?: return fail("$doc isn't kept")
        val raw = Sources.raw(db, kept.versionId)
        val sheet = try {
            Sources.ug(File(libraryDir, kept.path), raw)
        } catch (e: RenderError) {
            return fail(e.message.orEmpty())
        }
        val found = MusicKeys.sheetKey(raw, sheet.markup, sheet.capo)
        val text = ChordPro.chordProText(sheet.markup, Normalize.cleanTitle(song.title), song.artist, sheet.key, sheet.capo)
        val data = writeViewer(text, page, ViewerInputs(text, key = found?.key, keySource = found?.source, export = false,
                                                        versions = listed, guitar = guitar)) ?: return
        WrittenPages.note(db, song.id, page, data, unit)
    }

    // --- a sheet ----------------------------------------------------------------------------------------------------

    /** render._render_sheet, no PDF: the sheet's .cho ([text]), its progressions when it is the song's [primary]
     * sheet, then its page, in the song's own version [played] (from [start]). */
    private fun renderSheet(kept: KeptFile, text: String, played: Version, start: String?, key: SongKey?,
                            export: Boolean, primary: Boolean, versions: JsonObject?, guitar: List<String>,
                            harmonica: List<JsonObject>, video: JsonObject?, viewerText: String?) {
        val (cho, _, page) = RenderNames.SHEET_OUTPUTS.getValue(kept.name)
        val data = text.toByteArray(Charsets.UTF_8)
        if (LibraryReads.writeIfChanged(File(folder, cho), data)) wrote = true
        WrittenPages.note(db, song.id, cho, data, unit)
        if (primary) noteProgressions(text, key)
        val shown = viewerText?.takeIf { it.isNotEmpty() } ?: text
        val bytes = writeViewer(shown, page, ViewerInputs(shown, key = key?.key, keySource = key?.source,
                                                          transpose = played.t, start = start, export = export,
                                                          versions = versions, guitar = guitar, harmonica = harmonica,
                                                          video = video)) ?: return
        WrittenPages.note(db, song.id, page, bytes, unit)
    }

    /** render._write_viewer, no PDF: the page built ([SheetPage.build]) and written unless it holds those bytes; its
     * bytes, or null, said as "no viewer for", when it can't be built (a bug) or written (a link in its place). */
    private fun writeViewer(text: String, page: String, inputs: ViewerInputs): ByteArray? {
        val html = try {
            SheetPage.build(inputs.copy(cho = text))
        } catch (e: Exception) { // a sheet the viewer can't read must never cost the song's other pages
            fail("cannot build $page")
            return null
        }
        return write(page, html.toByteArray(Charsets.UTF_8))
    }

    private fun write(page: String, data: ByteArray): ByteArray? = try {
        if (LibraryReads.writeIfChanged(File(folder, page), data)) wrote = true
        data
    } catch (e: RenderError) {
        fail(e.message.orEmpty())
        null
    } catch (e: IOException) {
        fail(e.message.orEmpty())
        null
    }

    /** render._note_progressions: what the sheet [text] plays, in its [key], for finding the song by it; a sheet its
     * code can't read leaves none. And the characters its Chinese is written in (page.written_script). */
    private fun noteProgressions(text: String, key: SongKey?) {
        try {
            Progressions.record(db, song.id, text, key?.key, key?.source)
        } catch (e: Exception) { // a bug in the theory must never cost the pages
            Progressions.forget(db, song.id)
        }
        script = writtenScript(text)
    }

    // --- the harmonica tabs -----------------------------------------------------------------------------------------

    /** render._tab_harps: the harp each harmonica tab is played on, by its file's name, as its page chooses it with the
     * song's chord sheet [cho] in [key], the tab read as its page reads it ([Choice.tabsHarp]); a tab with neither, or
     * whose text can't be read, has none. */
    private fun tabHarps(tabs: List<HarmonicaFile>, files: Map<String, KeptFile>, cho: String,
                         key: SongKey?): Map<String, Int> {
        val out = LinkedHashMap<String, Int>()
        for (tab in tabs) {
            val kept = files[tab.name] ?: continue
            val found = try {
                val text = LibraryReads.replaced(LibraryReads.regular(File(libraryDir, kept.path)))
                val notation = pinOf(tab)?.let { HarpTabs.pinned(it, text) }
                HarpFit.choose(HarpTabs.parse(text, harp = tab.harp, notation = notation), cho = cho, key = key?.key,
                               keySource = key?.source, pageKey = tab.key)
            } catch (_: IOException) {
                continue // its page says why
            } catch (_: Exception) { // a tab the overlay can't read must never cost the sheet's page
                continue
            }
            found.tabsHarp?.let { out[tab.name] = it }
        }
        return out
    }

    /** render._harmonica_pin: how the phone's overrides (`[harmonica]`) have the tab read, or null: as guessed. */
    private fun pinOf(tab: HarmonicaFile): JsonElement? = overrides.harmonica[song.key]?.get(tab.name)

    /** render._render_harmonica: a page for each harmonica tab the song keeps, `harmonica-N.html` beside its text,
     * with the song's chord sheet [sheet] (its ChordPro and its key), [back] the sheet's page; the page of a tab no
     * longer kept, or whose text is gone from the folder, goes while it is as written. */
    private fun renderHarmonica(tabs: List<HarmonicaFile>, files: Map<String, KeptFile>, sheet: Pair<String, SongKey?>?,
                                back: String?) {
        val pages = HashSet<String>()
        for (tab in tabs) {
            val kept = files[tab.name] ?: continue
            if (tab.page.isEmpty()) continue
            val text = try {
                LibraryReads.replaced(LibraryReads.regular(File(libraryDir, kept.path)))
            } catch (_: NoSuchFileException) {
                continue // deleted from the folder: its page goes too
            } catch (e: IOException) {
                fail("cannot read ${tab.name}: ${e.message}")
                pages.add(tab.page)
                continue
            }
            pages.add(tab.page)
            val version = Rows.get(db, kept.versionId) ?: throw NoSuchElementException("no version ${kept.versionId}")
            val html = try {
                HarmonicaPage.build(text, title = Normalize.cleanTitle(song.title), artist = song.artist,
                                    tabFile = tab.name, url = version.url, pageKey = tab.key, harp = tab.harp,
                                    pin = pinOf(tab), facts = version.raw, cho = sheet?.first, key = sheet?.second?.key,
                                    keySource = sheet?.second?.source, back = back)
            } catch (e: Exception) { // a tab the page can't read must never cost the song's other pages
                fail("cannot build ${tab.page}")
                continue
            }
            val data = write(tab.page, html.toByteArray(Charsets.UTF_8)) ?: continue
            WrittenPages.note(db, song.id, tab.page, data, unit)
        }
        val left = WrittenPages.record(db, song.id).keys.filter { PyRe.fullmatch(HarmonicaFiles.PAGE, it) != null && it !in pages }
        WrittenPages.forget(db, song.id, left, folder)
    }

    companion object {
        /** page.written_script: "simplified" or "traditional", the characters a ChordPro sheet's Chinese is written in,
         * as its page judges them; null for a sheet in no Chinese. */
        fun writtenScript(cho: String): String? {
            val sheet = Sheets.parse(cho)
            if (!ViewerPinyin.isChinese(SheetView.drawnLines(sheet))) return null
            return if (Hanzi.writtenInTraditional(SheetView.writtenTexts(sheet))) "traditional" else "simplified"
        }
    }
}
