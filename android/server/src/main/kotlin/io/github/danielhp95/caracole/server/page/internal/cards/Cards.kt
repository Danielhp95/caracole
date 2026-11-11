package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sites.MuseScorePages
import io.github.danielhp95.caracole.core.ug.SheetVersion
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.server.page.CardText
import io.github.danielhp95.caracole.viewer.chinese.Hanzi
import io.github.danielhp95.caracole.viewer.progressions.Progressions
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.SongKey
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.File
import java.io.IOException
import java.nio.file.DirectoryIteratorException
import java.nio.file.Files
import java.time.Instant

/**
 * library_page.song_cards on the phone, in one place: every card the page's data carries of the phone's songs, as
 * the computer's page makes it of the same library (vectors/web/cards_full.jsonl): `_song` field for field and in its
 * order, `_files`, `_in_line_order` with the sheet's exports, UG's versions (`_ug_versions`, `_versions_data`),
 * LaCuerda's (`_lacuerda_versions`, `_lacuerda_pick`, `_lacuerda_sheet`), the auto sheet beside a human one
 * (`_auto_sheet`), a review's candidates and a song not found (`_add_picks`), the sites (`_add_sites`), MuseScore's
 * links, the buy links (todo.songs_to_buy), the progressions and a Chinese song's names in either script.
 *
 * The phone has no YouTube route: no song has a state there (`song_states` is the computer's alone), so no card says
 * where its audio stands, and its sites name YouTube for none. [names] gives each song's folder's files (the
 * folder's, as `_file_names` lists it, and those the mirror serves of it: PhonePageData's).
 *
 * **What no sync carries.** A card says some things of inputs that are the computer's alone: the export PDFs made of
 * the sheet (kv `render:export:<id>`), what its PDF is moved by (kv `render:<id>`), the misses of gtptabs.com,
 * harptabs.com and gametabs.net (kv `<site>:checked:<id>`), UG's left-out tabs and artist-page reads (fetch_due's
 * kv), a purchase linked from Music/ (`audio_path`) and its YouTube route. For a song [computers] gives the computer's
 * card of (one the mirror lists as the phone holds it: PhonePageData's), those are the computer's card's
 * ([COMPUTERS]: `transpose`, `buy`, `youtube`, `youtubeSheet`, `sites`, and the files' exports by its `version`
 * entries), as are its `progressions` and `hanzi` while the phone has recorded none of its own; any other song's card
 * says what the phone knows.
 *
 * Reads only, through [db]; [now] is the buy list's time (fetch_due's ages).
 */
internal class Cards(private val db: Db, private val libraryDir: File, private val config: PhoneConfig,
                     private val overrides: Overrides, private val now: Instant,
                     private val names: (SongRow) -> Set<String> = { folderNames(libraryDir, it) },
                     private val computers: (SongRow) -> JsonObject? = { null }) {

    /** song_cards: the cards of [songs], or of every song (Songs.list's order) with [only] false. */
    fun cards(songs: List<SongRow>, only: Boolean): List<JsonObject> {
        val browsable = guitarPages()
        val sources = downloaded()
        val origins = Sources.keptSources(db)
        val ukulele = ukuleleSheets()
        val exports = exports()
        val theirs = songs.associate { it.id to computers(it) }
        val keys = songs.associate { it.id to MusicKeys.songKey(db, libraryDir, it.id) }
        val audio = audioPaths(songs)
        val toBuy = ToBuy.songsToBuy(db, songs, overrides, now, audio).mapTo(HashSet()) { it.id }
        val fromYoutube = videosByAudio()
        val musescore = config.provider("musescore").enabled
        val pages = if (musescore) songs.associate { it.id to museScoreLinks(it) } else emptyMap()
        val met = lacuerdaVersions(if (only) songs.mapTo(HashSet()) { it.id } else null)
        val ug = ugVersions(songs)
        val made = songs.map { s ->
            val folder = names(s)
            val path = audio[s.id]
            val computer = theirs[s.id]
            song(s, folder, keys[s.id], s.id in toBuy, sources[s.id].orEmpty(), pages[s.id].orEmpty(),
                 origins[s.id].orEmpty(), computer?.let(::exportsOf) ?: exports[s.id].orEmpty(),
                 computer?.let(::transposeOf) ?: pdfTranspose(s), met[s.id].orEmpty(), ug[s.id],
                 browsable[s.id], s.id in ukulele, !path.isNullOrEmpty() && path !in fromYoutube)
        }.map { LinkedHashMap<String, JsonElement>(it) }
        addPicks(songs, made)
        addSites(songs, made, origins, met, pages)
        val played = Progressions.library(db)
        val chinese = PhoneRender.chineseSongs(db)  // render.chinese_songs, the phone's records (kv render:<id>:phone)
        for ((song, card) in songs.zip(made)) {
            val computer = theirs[song.id]
            card["progressions"] = played[song.id] ?: computer?.get("progressions")?.takeIf { it is JsonArray }
                ?: JsonArray(emptyList())
            if (song.id in chinese) {
                val title = (card.getValue("title") as JsonPrimitive).content
                val artist = (card.getValue("artist") as JsonPrimitive).content
                val either = Hanzi.names(listOf(title, artist))
                if (either.values.any { it.isNotEmpty() }) card["hanzi"] = json(either)
            } else if (computer?.get("hanzi") is JsonObject && WrittenPages.rendered(db, song.id) == null) {
                card["hanzi"] = computer.getValue("hanzi")  // the computer's, until the phone records the song's script
            }
            if (computer != null) {
                for (field in COMPUTERS) computer[field]?.let { if (field in card) card[field] = it }
            }
        }
        return made.map { JsonObject(it) }
    }

    /**
     * library_page.result_cards: what a list the page doesn't make itself (/api/search's rows) shows of each song as
     * its line does: its files as the line has them but with no site's name (`links`: `_files` with no sources), where
     * its sheet came from (`source`), its key and what it holds for one instrument. By song id, in [songs]' order.
     */
    fun results(songs: List<SongRow>): Map<Long, JsonObject> {
        val origins = Sources.keptSources(db)
        val exports = exports()
        val browsable = guitarPages()
        val ukulele = ukuleleSheets()
        val out = LinkedHashMap<Long, JsonObject>()
        for (s in songs) {
            val folder = names(s)
            val made = computers(s)?.let(::exportsOf) ?: exports[s.id].orEmpty()
            val files = files(s, folder, emptyMap(), origins[s.id].orEmpty(), made, browsable[s.id], s.id in ukulele)
            val key = MusicKeys.songKey(db, libraryDir, s.id)
            out[s.id] = JsonObject(linkedMapOf(
                "links" to JsonArray(files),
                "source" to (files.firstOrNull { it["primary"] == JsonPrimitive(true) }?.get("source") ?: JsonNull),
                "key" to (key?.key?.let(::JsonPrimitive) ?: JsonNull),
                "instruments" to JsonArray(instrumentsOf(folder, s.id in ukulele).map(::JsonPrimitive)),
            ))
        }
        return out
    }

    /** The computer's card's exports of the sheet: each file it lists with a `version` (`_files`' export entries),
     * by name, its version's label. */
    private fun exportsOf(card: JsonObject): Map<String, String> {
        val found = LinkedHashMap<String, String>()
        for (file in (card["files"] as? JsonArray).orEmpty()) {
            val f = file as? JsonObject ?: continue
            val name = (f["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: continue
            val label = (f["version"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: continue
            if (Sources.isExport(name)) found[name] = label
        }
        return found
    }

    /** The computer's card's `transpose`, what its PDF is moved by; null for none that is an int. */
    private fun transposeOf(card: JsonObject): Long? =
        (card["transpose"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull()

    // --- one song ------------------------------------------------------------------------------------------------

    /** library_page._song: one song's card, its fields in Python's order. */
    private fun song(song: SongRow, names: Set<String>, key: SongKey?, forBuying: Boolean, sources: Map<String, String>,
                     musescore: List<JsonObject>, origins: Map<String, String>, exports: Map<String, String>,
                     transpose: Long, lacuerda: List<JsonObject>, versions: UgVersions?, guitar: Map<String, String>?,
                     ukulele: Boolean, purchase: Boolean): Map<String, JsonElement> {
        val title = Normalize.cleanTitle(song.title)
        val status = if (song.key in overrides.ignore) "ignored" else song.status
        val ignored = status == "ignored"
        val human = HUMAN_SHEETS.any { it in names }
        val auto = AUTO_SHEETS.any { it in names }
        val (links, buy) = if (!(human || auto || ignored)) elsewhere(song, forBuying) else emptyList<JsonObject>() to emptyList()
        val files = files(song, names, sources, origins, exports, guitar, ukulele)
        val sortArtist = CardText.sortKey(song.artist)
        val sortTitle = CardText.sortKey(title)
        val mode = key?.let { listOf(MusicKeys.keyName(it.key).substringAfterLast(' ')) }.orEmpty()
        val initials = CardText.initials(title)
        return linkedMapOf<String, JsonElement>(
            "id" to JsonPrimitive(song.id),
            "artist" to JsonPrimitive(song.artist),
            "artists" to JsonArray(song.artists.ifEmpty { listOf(song.artist) }.map(::JsonPrimitive)),
            "title" to JsonPrimitive(title),
            "display" to JsonPrimitive(song.display),
            "status" to JsonPrimitive(status),
            "review" to JsonPrimitive(song.review && !ignored),
            "added" to JsonPrimitive(song.addedAt),
            "key" to (key?.key?.let(::JsonPrimitive) ?: JsonNull),
            "key_source" to (key?.source?.let(::JsonPrimitive) ?: JsonNull),
            "transpose" to JsonPrimitive(transpose),
            "lyrics" to JsonPrimitive(song.lyricsStatus),
            "lyricsFrom" to CardText.lyricsFrom(song.lyricsStatus, song.lyricsJson),
            "auto" to JsonPrimitive(!human && auto),
            "files" to JsonArray(files),
            "instruments" to JsonArray(instrumentsOf(names, ukulele).map(::JsonPrimitive)),
            "versions" to versionsData(versions, names, folderHref(song)),
            "autoSheet" to autoSheet(song, names),
            "source" to (files.firstOrNull { it["primary"] == JsonPrimitive(true) }?.get("source") ?: JsonNull),
            "museScore" to JsonArray(musescore),
            "links" to JsonArray(links),
            "buy" to JsonArray(buy),
            "youtube" to JsonNull,  // no song is on YouTube's route on the phone (`_youtube_note` of no state)
            "youtubeSheet" to JsonPrimitive(!ignored && !purchase && !human),
            "lacuerda" to lacuerdaPick(song, status),
            "lacuerdaVersions" to JsonArray(lacuerda),
            "lacuerdaSheet" to lacuerdaSheet(song, status, origins,
                                             (lacuerda.firstOrNull()?.get("href") as? JsonPrimitive)?.content),
            "identity" to JsonPrimitive(song.key),
            "sortArtist" to JsonPrimitive(sortArtist),
            "sortTitle" to JsonPrimitive(sortTitle),
            "artistLetter" to JsonPrimitive(CardText.letter(sortArtist)),
            "titleLetter" to JsonPrimitive(CardText.letter(sortTitle)),
            "search" to JsonPrimitive(CardText.haystack(listOf(song.artist) + song.artists + listOf(title, song.display) +
                                                        mode)),
        ).apply { if (initials.isNotEmpty()) put("initials", JsonPrimitive(initials)) }
    }

    /** library_page._elsewhere: where to look for a sheet (Chordify, YouTube), and, for a song on the buy list, where
     * to buy its audio. */
    private fun elsewhere(song: SongRow, forBuying: Boolean): Pair<List<JsonObject>, List<JsonObject>> {
        val found = ToBuy.searchLinks(song.artist, song.title)
        val links = listOf(link("Chordify", found.getValue("chordify")),
                           link("YouTube", found.getValue("youtube"), "youtube"))
        val buy = if (forBuying) listOf("Bandcamp" to "bandcamp", "Qobuz" to "qobuz", "iTunes" to "itunes")
            .map { (label, name) -> link(label, found.getValue(name)) } else emptyList()
        return links to buy
    }

    private fun link(label: String, href: String, source: String? = null) = JsonObject(linkedMapOf<String, JsonElement>(
        "label" to JsonPrimitive(label), "href" to JsonPrimitive(href)).apply {
        if (source != null) put("source", JsonPrimitive(source))
    })

    /** library_page._files: the kept files that exist, in the line's order, each with its label, its link (the
     * song's folder and its name percent-encoded), whether the line opens it, where it came from, and, where they
     * apply, its export's version, its Guitar Pro page, its harmonica tab's page and the name it downloads under. */
    private fun files(song: SongRow, names: Set<String>, sources: Map<String, String>, origins: Map<String, String>,
                      exports: Map<String, String>, guitar: Map<String, String>?, ukulele: Boolean): List<JsonObject> {
        val made = exports.entries.filter { it.key in names }.map { (n, label) -> label to n }
            .sortedWith { a, b ->
                Py.CODE_POINT_ORDER.compare(a.first, b.first).takeIf { it != 0 } ?: Py.CODE_POINT_ORDER.compare(a.second, b.second)
            }
        val ordered = CardText.inLineOrder(names, made.map { it.second })
        val primary = CardText.primary(ordered)
        val base = folderHref(song)
        val labels = HashMap<String, String>()
        for ((label, n) in made) labels[n] = "Sheet PDF, $label"
        if (ukulele) for (n in CardText.UKULELE_LABELLED) if (n in names) labels[n] = "${CardText.ownLabel(n)} · ${CardText.UKULELE_SHEET}"
        val versions = made.associate { (label, n) -> n to label }
        val title = Normalize.cleanTitle(song.title)
        return ordered.map { n ->
            val page = HarmonicaFiles.page(n)?.takeIf { it in names }
            JsonObject(linkedMapOf<String, JsonElement>(
                "name" to JsonPrimitive(n),
                "label" to JsonPrimitive(labels[n]?.takeIf { it.isNotEmpty() } ?: CardText.label(n, sources[n])),
                "href" to JsonPrimitive("$base/${PyUrl.quote(n, safe = "")}"),
                "primary" to JsonPrimitive(n == primary),
                "source" to (Sources.sourceOf(n, origins)?.let(::JsonPrimitive) ?: JsonNull),
            ).apply {
                versions[n]?.let { put("version", JsonPrimitive(it)) }
                guitar?.get(n)?.let { put("guitarPage", JsonPrimitive(it)) }
                page?.let { put("harmonicaPage", JsonObject(mapOf("href" to JsonPrimitive("$base/${PyUrl.quote(it, safe = "")}")))) }
                if (CardText.downloads(n)) put("download", JsonPrimitive(DownloadNames.downloadName(song.artist, title, n)))
            })
        }
    }

    /** library_page._folder_href: the song's folder, relative to index.html, each part percent-encoded. */
    private fun folderHref(song: SongRow): String {
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        return PyUrl.quote(artist, safe = "") + "/" + PyUrl.quote(title, safe = "")
    }

    /** library_page.instruments_of: what the folder holds for one instrument: "ukulele" (its sheet UG's Ukulele
     * Chords), "harmonica", "score". */
    private fun instrumentsOf(names: Set<String>, ukulele: Boolean): List<String> = buildList {
        if (ukulele) add("ukulele")
        if (names.any(CardText::isHarmonica)) add("harmonica")
        if (names.any(CardText::isScore)) add("score")
    }

    /** library_page._auto_sheet: the auto sheet of a song with a human one too: its viewer (else PDF, else text) and
     * its PDF, text and ChordPro, each downloading under its "(auto)" name. */
    private fun autoSheet(song: SongRow, names: Set<String>): JsonElement {
        if (!(HUMAN_SHEETS.any { it in names } && AUTO_SHEETS.any { it in names })) return JsonNull
        val base = folderHref(song)
        val opens = AUTO_OPENS.first { it in names }
        val title = "${Normalize.cleanTitle(song.title)} (auto)"
        return JsonObject(linkedMapOf(
            "href" to JsonPrimitive("$base/${PyUrl.quote(opens, safe = "")}"),
            "files" to JsonArray(AUTO_FILES.filter { it.first in names }.map { (n, label) ->
                JsonObject(linkedMapOf("label" to JsonPrimitive(label), "href" to JsonPrimitive("$base/${PyUrl.quote(n, safe = "")}"),
                                       "download" to JsonPrimitive(DownloadNames.downloadName(song.artist, title, n))))
            }),
        ))
    }

    // --- UG's versions -------------------------------------------------------------------------------------------

    /** library_page._UgVersions. */
    private class UgVersions(val listed: List<SheetVersion>, val rest: Int, val keepMore: Int, val pinned: Boolean)

    /** library_page._ug_versions: each song's UG versions listed for its sheet (SheetVersions.inLibraryOf, every song
     * at once), and how many a keep may still keep. */
    private fun ugVersions(songs: List<SongRow>): Map<Long, UgVersions> {
        val listings = SheetVersions.inLibraryOf(db, songs.map { it.id }, config.rank)
        val budget = config.provider(SheetVersions.PROVIDER).lookupRequests
        val found = HashMap<Long, UgVersions>()
        for (song in songs) {
            val listed = listings[song.id] ?: continue
            val rest = SheetVersions.mayKeep(db, song.id, listed, overrides.block).size
            found[song.id] = UgVersions(listed, rest, minOf(rest, budget),
                                        SheetVersions.sheetPins(db, song.id, overrides.pin[song.key].orEmpty()).isNotEmpty())
        }
        return found
    }

    /** library_page._versions_data: the kept versions in rank order (each as_data's, with the link it opens, where it
     * came from and its lyric score), how many UG still has, how many a keep may still keep and one press keeps, and
     * whether a `[pin]` chooses the sheet; null for a song with none. */
    private fun versionsData(versions: UgVersions?, names: Set<String>, base: String): JsonElement {
        versions ?: return JsonNull
        val data = SheetVersions.asData(versions.listed, versions.listed.size)
        val listed = ArrayList<JsonObject>()
        for ((version, entry) in versions.listed.zip((data.getValue("list") as JsonArray).map { it as JsonObject })) {
            if (entry["kept"] != JsonPrimitive(true)) continue
            val page = (entry["page"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val opens = if (entry["chosen"] == JsonPrimitive(true)) listOf(page, "sheet.txt", "sheet.pdf")
                        else listOf(page, SheetVersions.versionNames((entry.getValue("tab") as JsonPrimitive).content).first)
            val name = opens.firstOrNull { it != null && it in names } ?: continue
            listed += JsonObject(LinkedHashMap(entry).apply {
                put("href", JsonPrimitive("$base/${PyUrl.quote(name, safe = "")}"))
                put("source", JsonPrimitive("ug"))
                put("complete", version.complete?.let(::JsonPrimitive) ?: JsonNull)
                put("coverage", version.coverage?.let(::JsonPrimitive) ?: JsonNull)
            })
        }
        return JsonObject(linkedMapOf(
            "total" to JsonPrimitive(versions.listed.count { !it.gone }), "list" to JsonArray(listed),
            "rest" to JsonPrimitive(versions.rest), "keepMore" to JsonPrimitive(versions.keepMore),
            "pinned" to JsonPrimitive(versions.pinned),
        ))
    }

    // --- LaCuerda's ----------------------------------------------------------------------------------------------

    /** library_page._lacuerda_versions: the LaCuerda sheets caracole met for each song that LaCuerda still has, the
     * one that covers the most of its lyrics first: each its page, its coverage and whether it is the kept sheet. */
    private fun lacuerdaVersions(ids: Set<Long>?): Map<Long, List<JsonObject>> {
        val only = if (ids == null) "" else " AND v.song_id IN (SELECT value FROM json_each(?))"
        val args = if (ids == null) arrayOf<Any?>(Sources.HUMAN_SHEET)
                   else arrayOf<Any?>(Sources.HUMAN_SHEET, ids.sorted().joinToString(", ", "[", "]"))
        val met = LinkedHashMap<Long, MutableList<JsonObject>>()
        db.query(
            "SELECT v.song_id, v.url, v.coverage, f.id IS NOT NULL FROM versions v " +
                "LEFT JOIN files f ON f.version_id = v.id AND f.song_id = v.song_id AND f.name = ? " +
                "WHERE v.provider = 'lacuerda' AND v.slot = 'sheet' AND v.gone = 0" + only +
                " ORDER BY v.song_id, v.coverage IS NULL, v.coverage DESC, v.id",
            *args,
        ) {
            it.long(0)!! to JsonObject(linkedMapOf(
                "href" to JsonPrimitive(it.text(1)!!),
                "coverage" to (it.double(2)?.let(::JsonPrimitive) ?: JsonNull),
                "sheet" to JsonPrimitive(it.long(3) == 1L),
            ))
        }.forEach { (song, entry) -> met.getOrPut(song) { ArrayList() }.add(entry) }
        return met
    }

    /** library_page._lacuerda_pick: the sheet you picked on LaCuerda, for a wanted song LaCuerda wasn't asked for yet. */
    private fun lacuerdaPick(song: SongRow, status: String): JsonElement {
        val pick = overrides.lacuerda[song.key] ?: return JsonNull
        if (status != "wanted" || song.lacuerdaCheckedAt != null) return JsonNull
        return JsonObject(linkedMapOf("label" to JsonPrimitive("the sheet you picked on LaCuerda"),
                                      "href" to JsonPrimitive(pick.url)))
    }

    /** library_page._lacuerda_sheet: the LaCuerda sheet the song could be looked up with now: your pick, else the best
     * one met; none when its sheet is LaCuerda's already, or it is ignored. */
    private fun lacuerdaSheet(song: SongRow, status: String, origins: Map<String, String>, met: String?): JsonElement {
        if (status == "ignored" || origins[Sources.HUMAN_SHEET] == "lacuerda") return JsonNull
        val url = overrides.lacuerda[song.key]?.url ?: met
        return if (!url.isNullOrEmpty() && url.startsWith("https://")) JsonPrimitive(url) else JsonNull
    }

    // --- what is added to every card -----------------------------------------------------------------------------

    /** library_page._add_picks: a song in review (not ignored) its candidates; a song not found, `notFound`. */
    private fun addPicks(songs: List<SongRow>, cards: List<LinkedHashMap<String, JsonElement>>) {
        for ((song, card) in songs.zip(cards)) {
            if (card["review"] == JsonPrimitive(true)) {
                val choices = Choices.reviewChoices(db, song)
                if (choices.isNotEmpty()) card["candidates"] = JsonArray(choices)
            } else if (song.matchDecision == "not_found" && card["status"] != JsonPrimitive("ignored") &&
                card["lacuerda"] == JsonNull) {
                card["notFound"] = JsonPrimitive(true)
            }
        }
    }

    /** library_page._add_sites: each card's `sites`, song_sites.py's marks. */
    private fun addSites(songs: List<SongRow>, cards: List<LinkedHashMap<String, JsonElement>>,
                         origins: Map<Long, Map<String, String>>, lacuerda: Map<Long, List<JsonObject>>,
                         musescore: Map<Long, List<JsonObject>>) {
        val sites = SongSites.shown(config)
        val checks = SongSites.checked(db)
        val read = "musescore" in sites && SongSites.musescoreRead(db)
        for ((song, card) in songs.zip(cards)) {
            card["sites"] = JsonArray(SongSites.songSites(
                song, sites, origins[song.id].orEmpty(), checks, lacuerda = !lacuerda[song.id].isNullOrEmpty(),
                musescore = if ("musescore" in sites) !musescore[song.id].isNullOrEmpty() else null,
                musescoreRead = read, youtube = null,
            ))
        }
    }

    // --- read for every song at once ---------------------------------------------------------------------------

    /** library_page._musescore_links: the song's MuseScore pages, each a possible match, none for an ignored song. */
    private fun museScoreLinks(song: SongRow): List<JsonObject> {
        if (song.status == "ignored" || song.key in overrides.ignore) return emptyList()
        return MuseScorePages.songPages(db, song).map { p ->
            JsonObject(linkedMapOf("label" to JsonPrimitive("${p.path.removePrefix("song/")} (possible match)"),
                                   "href" to JsonPrimitive(p.url), "source" to JsonPrimitive("musescore")))
        }
    }

    /** library_page.guitar_pages: the address of the Guitar Pro page of each file it shows, by song and name. */
    private fun guitarPages(): Map<Long, Map<String, String>> {
        val found = HashMap<Long, LinkedHashMap<String, String>>()
        for (f in GuitarFiles.of(db)) {
            if (f.inBrowser) found.getOrPut(f.songId) { LinkedHashMap() }[f.name] = "guitar?" + PyUrl.urlencode(listOf("file" to f.path))
        }
        return found
    }

    /** library_page._downloaded: the files downloaded from gtptabs.com, harptabs.com and gametabs.net, by song and
     * name, each its site's name. */
    private fun downloaded(): Map<Long, Map<String, String>> {
        val found = HashMap<Long, LinkedHashMap<String, String>>()
        db.query("SELECT f.song_id, f.name, v.provider FROM files f JOIN versions v ON v.id = f.version_id " +
                     "WHERE v.provider IN ('gtptabs', 'harptabs', 'gametabs')") {
            Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }.forEach { (song, name, provider) -> found.getOrPut(song) { LinkedHashMap() }[name] = DOWNLOADED_FROM.getValue(provider) }
        return found
    }

    /** library_page.ukulele_sheets: the songs whose kept sheet.txt is a version of UG's Ukulele Chords type. */
    private fun ukuleleSheets(): Set<Long> = db.query(
        "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id " +
            "WHERE f.name = 'sheet.txt' AND v.provider = 'ug' AND v.kind = 'ukulele'") { it.long(0)!! }.toSet()

    /** library_page._exports: the PDFs made of each song's sheet in other versions (kv `render:export:<id>`), by
     * song and name, each its version's label. */
    private fun exports(): Map<Long, Map<String, String>> {
        val found = HashMap<Long, LinkedHashMap<String, String>>()
        val rows = db.query("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", EXPORT_KV.length, EXPORT_KV) {
            it.text(0)!! to it.text(1)!!
        }
        for ((key, value) in rows) {
            val number = key.substring(EXPORT_KV.length)
            val record = try {
                PyJson.loads(value)
            } catch (_: IllegalArgumentException) {
                continue
            } catch (_: IOException) {
                continue
            }
            if (number.isEmpty() || !number.all { it in '0'..'9' } || record !is JsonObject) continue
            val id = number.toBigInteger().takeIf { it.bitLength() < 64 }?.toLong() ?: continue
            for ((label, entry) in record) {
                val name = ((entry as? JsonObject)?.get("pdf") as? JsonPrimitive)?.takeIf { it.isString }?.content
                if (name != null && Sources.isExport(name)) found.getOrPut(id) { LinkedHashMap() }[name] = label
            }
        }
        return found
    }

    /** Each song's audio_path (a purchase linked from Music/; on the phone none, which no sync carries). */
    private fun audioPaths(songs: List<SongRow>): Map<Long, String?> {
        if (songs.isEmpty()) return emptyMap()
        val ids = songs.map { it.id }.toSet()
        return db.query("SELECT id, audio_path FROM songs WHERE audio_path IS NOT NULL") { it.long(0)!! to it.text(1) }
            .filter { it.first in ids }.toMap()
    }

    /** youtube_fetch.videos_by_audio: each file of audio YouTube gave (kv `youtube:<id>`'s `audio` with its video). */
    private fun videosByAudio(): Set<String> {
        val found = HashSet<String>()
        db.query("SELECT key, value FROM kv WHERE key LIKE ?", "youtube:%") { it.text(0)!! to it.text(1)!! }
            .forEach { (key, value) ->
                val id = key.removePrefix("youtube:")
                if (id.isEmpty() || !id.all { it in '0'..'9' }) return@forEach
                val raw = try {
                    PyJson.loads(value)
                } catch (_: Exception) {
                    return@forEach
                } as? JsonObject ?: return@forEach
                val audio = (raw["audio"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { it.isNotEmpty() }
                val video = raw["video"] as? JsonObject
                val videoId = (video?.get("id") as? JsonPrimitive)?.takeIf { it.isString }?.content
                if (audio != null && videoId != null && VIDEO_ID.matches(videoId)) found += audio
            }
        return found
    }

    /** render.pdf_transpose: what the song's PDF is moved by: its own version's `t` (a move from the sheet, or
     * `[transpose]`); for one kept by its key, the PDF's as it was last made (kv `render:<id>`'s `transpose`), else 0. */
    private fun pdfTranspose(song: SongRow): Long {
        val transpose = overrides.transpose[song.key] ?: 0
        val query = overrides.version[song.key] ?: return transpose.toLong()
        if (Versions.keyVersion(query) != null) {
            val made = db.kvGet("render:${song.id}")?.let { runCatching { PyJson.loads(it) }.getOrNull() } as? JsonObject
            val t = made?.get("transpose") as? JsonPrimitive ?: return 0
            if (t.isString || t.booleanOrNull != null) return 0
            return t.content.toLongOrNull() ?: 0
        }
        val asked = if (query.startsWith("#") || query.startsWith("?")) query.substring(1) else query
        return if ("t" in PyUrl.parseQs(asked, keepBlank = true)) Versions.fromQuery(query).t.toLong() else transpose.toLong()
    }

    companion object {
        private val HUMAN_SHEETS = listOf("sheet.txt", "sheet.pdf")
        private val AUTO_SHEETS = listOf("sheet (auto).txt", "sheet (auto).pdf")
        private val AUTO_OPENS = listOf("sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt")
        private val AUTO_FILES = listOf("sheet (auto).pdf" to "PDF", "sheet (auto, Traditional).pdf" to "PDF, Traditional",
                                        "sheet (auto).txt" to "Text", "sheet (auto).cho" to "ChordPro")
        private val DOWNLOADED_FROM = mapOf("gtptabs" to "gtptabs.com", "harptabs" to "harptabs.com",
                                            "gametabs" to "gametabs.net")
        private const val EXPORT_KV = "render:export:"

        /** The fields of a card made of what no sync carries, the computer's card's for a song it holds as the phone
         * does (the class's docstring). */
        private val COMPUTERS = listOf("transpose", "buy", "youtube", "youtubeSheet", "sites")
        private val VIDEO_ID = Regex("[A-Za-z0-9_-]{11}")

        /** library_page._file_names: the regular files of the song's folder (a link followed, as Path.is_file
         * does), but those whose name starts with a dot; none for no folder. */
        fun folderNames(libraryDir: File, song: SongRow): Set<String> {
            val (artist, title) = SafeName.songFolder(song.artist, song.title)
            val folder = File(File(libraryDir, artist), title).toPath()
            return try {
                Files.newDirectoryStream(folder).use { entries ->
                    entries.filter { !it.fileName.toString().startsWith(".") && Files.isRegularFile(it) }
                        .mapTo(HashSet()) { it.fileName.toString() }
                }
            } catch (_: IOException) {
                emptySet()
            } catch (_: DirectoryIteratorException) {
                emptySet()
            }
        }

        private fun json(value: Map<String, Map<String, String>>): JsonObject =
            JsonObject(value.mapValues { (_, table) -> JsonObject(table.mapValues { JsonPrimitive(it.value) }) })
    }
}
