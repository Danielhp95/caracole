package io.github.danielhp95.caracole.server.routes.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearch
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.library.NamedSong
import io.github.danielhp95.caracole.server.routes.library.SongForm
import io.github.danielhp95.caracole.server.routes.search.Mine
import io.github.danielhp95.caracole.server.routes.search.SongForms
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import java.time.Instant

/**
 * A lookup asked for by a form, short of queueing: its job ([spec]) and what a full queue's refusal says ([full]).
 */
internal data class LookupAsk(val spec: JobSpec, val full: String)

/**
 * What the library page's lookups read of a form, as caracole serve reads it, short of queueing (search_routes.py's
 * `lookup_request`, `_pick`, `_library_song`, `lacuerda_read`, `lacuerda_search` and `harptabs_read`; library_routes.py's
 * `fetch` and its pick fields; versions_routes.py's Fetch them; app.py's `song_id`, `not_ignored` and the overrides'
 * refusal; review_routes.py's `review_first`): each gives the job's [JobSpec], its commands spelled as web/jobs.py
 * spells them (JobCommands), or refuses as caracole serve does, in its words ([Refused]).
 *
 * The phone writes no wanted.txt: a song new to the library is added by its lookup's `caracole get` (the runner's
 * song stage), so a lookup's note says nothing of a line (caracole serve's names its wanted.txt line), and a full
 * queue's refusal says nothing was added ([NOTHING_ADDED]).
 */
internal object LookupForms {
    /** What a full queue's refusal says of a song new to the library, which the phone added nowhere. */
    const val NOTHING_ADDED = LibraryRoutes.FULL

    const val NO_SUCH_SONG = "That song isn't in the library."

    /** review.SHOWN: the candidates a review lists. */
    private const val SHOWN = 9

    /** lacuerda_search.SEARCHES_PER_HOUR: the searches of LaCuerda the pages send by themselves in an hour (Phase A:
     * LaCuerdaSearch.SEARCHES_PER_HOUR once lane lacuerda-pages declares it, waiting on lacuerda-pages). */
    private const val SEARCHES_PER_HOUR = 20

    /** search_routes.QUERY_LIMIT: characters of a search. */
    const val QUERY_LIMIT = 200

    /** search_routes._SLUG: the slug of a LaCuerda artist's page. */
    private val SLUG = PyRegex.compile("[a-z0-9_]{1,200}")

    /** search_routes._HARP_ARTIST: the path of a harptabs.com artist's page. */
    private val HARP_ARTIST = PyRegex.compile("""artist/\d{1,9}/[a-z0-9-]{1,200}""")

    // --- what every form names -------------------------------------------------------------------------------------

    /** app.song_id: the song a form (or an address, [where]) names by its id, as Python's int() reads it; Refused (400)
     * when it names none. An id past a Long's is no song's (404). */
    fun songId(text: String, where: String = "form"): Long {
        val n = PyInt.parse(text) ?: throw Refused(400, "Not a song", "Which song? The $where names none.")
        return if (n.bitLength() < 64) n.toLong() else -1
    }

    /** songs.get_song under app.no_such_song: Refused (404) for an id no song has. */
    fun song(db: Db, id: Long): SongRow = Songs.byId(db, id) ?: throw Refused(404, "No such song", NO_SUCH_SONG)

    /** app.not_ignored: Refused (409) for a song ignored, in the database or in the overrides. */
    fun notIgnored(song: SongRow, overrides: Overrides) {
        if (song.status == "ignored" || song.key in overrides.ignore) {
            throw Refused(409, "Ignored", "${song.display} is ignored in overrides.toml.")
        }
    }

    /** WebApp.overrides: the phone's overrides; Refused (503) when they can't be read. */
    fun overrides(db: Db): Overrides = try {
        Overrides.read(db)
    } catch (e: OverridesError) {
        throw Refused(503, "overrides.toml can't be read", "overrides.toml can't be read: ${e.message}.")
    }

    /**
     * review_routes.review_first: whether `caracole get` would find no sheet to fetch for the song before its review:
     * a review its artist's UG page doesn't settle (ug.fetch.needs_artist_page: a not-found song, or a review whose
     * candidates all come of the steps that never accept), nor a `[match]` or `[pin]`, nor a `[reject]` naming every
     * candidate it has now (review.candidates_of: those that name a UG song, nine at most).
     */
    fun reviewFirst(song: SongRow, overrides: Overrides): Boolean {
        val candidates = candidates(song)
        if (song.matchDecision != "review" || needsArtistPage(song, candidates)) return false
        if (song.key in overrides.match || song.key in overrides.pin) return false
        val rejected = overrides.reject[song.key] ?: return true
        val shown = candidates.filter { truthy(it["artist_key"]) && truthy(it["song_key"]) }.take(SHOWN)
        return !shown.all { c ->
            val artist = text(c["artist_key"])
            val title = text(c["song_key"])
            artist != null && title != null && (artist to title) in rejected
        }
    }

    /** ug.fetch.needs_artist_page. */
    private fun needsArtistPage(song: SongRow, candidates: List<JsonObject>): Boolean {
        if (song.matchDecision == "not_found") return true
        return song.matchDecision == "review" && candidates.isNotEmpty() &&
            candidates.all { text(it["step"]) in Match.REVIEW_ONLY_STEPS }
    }

    /** songs.match_candidates as Song reads them: the stored JSON's objects ([] for none). */
    private fun candidates(song: SongRow): List<JsonObject> =
        (runCatching { PyJson.loads(song.matchCandidates) }.getOrNull() as? JsonArray).orEmpty().filterIsInstance<JsonObject>()

    /** A JSON string's text; null for none or another kind. */
    private fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Python's truth of a value json.loads made. */
    private fun truthy(e: JsonElement?): Boolean = when (e) {
        null, JsonNull -> false
        is JsonObject -> e.isNotEmpty()
        is JsonArray -> e.isNotEmpty()
        is JsonPrimitive -> if (e.isString) e.content.isNotEmpty() else e.booleanOrNull ?: (e.doubleOrNull != 0.0)
    }

    // --- a lookup's picks ------------------------------------------------------------------------------------------

    /** search_routes._pick: the Ultimate Guitar song and tab a form picks (each "" for none), and the UG song's keys;
     * Refused for any pick too long, a song that isn't one, or a tab no Ultimate Guitar tab's. */
    fun pick(form: Map<String, String>): Pair<Map<String, String>, Pair<String, String>?> {
        val pick = SongForm.PICK_LIMITS.keys.associateWith { Py.strip(form[it].orEmpty()) }
        for ((name, value) in pick) {
            val limit = SongForm.PICK_LIMITS.getValue(name)
            if (Py.len(value) > limit) throw Refused(400, "Too long", "The $name is too long: $limit characters at most.")
        }
        val ug = pick.getValue("ug")
        val sep = ug.indexOf('/')
        val artistKey = if (sep >= 0) ug.substring(0, sep) else ug
        val songKey = if (sep >= 0) ug.substring(sep + 1) else ""
        if (ug.isNotEmpty() && (sep < 0 || artistKey.isEmpty() || songKey.isEmpty() || '/' in songKey)) {
            throw Refused(400, "Not a pick", "${PyStr.repr(ug)} isn't an Ultimate Guitar song (artist-key/song-key).")
        }
        val tab = pick.getValue("tab")
        if (tab.isNotEmpty()) {
            try {
                OverrideUrls.tabIdFromUrl(tab)
            } catch (e: OverridesError) {
                throw Refused(400, "Not a pick", "That isn't an Ultimate Guitar tab: ${e.message}")
            }
        }
        return pick to if (ug.isNotEmpty()) artistKey to songKey else null
    }

    /** library_routes.lacuerda_field: the LaCuerda song or version picked, as caracole asks for it; null for none. */
    fun lacuerdaField(form: Map<String, String>): String? =
        field(form, "lacuerda", "a LaCuerda song") { OverrideUrls.lacuerdaPickFromUrl(it).url }

    /** library_routes.harptabs_field. */
    fun harptabsField(form: Map<String, String>): String? =
        field(form, "harptabs", "a harptabs.com tab") { OverrideUrls.harptabsPickFromUrl(it).url }

    /** library_routes.gametabs_field. */
    fun gametabsField(form: Map<String, String>): String? =
        field(form, "gametabs", "a gametabs.net tab") { OverrideUrls.gametabsPickFromUrl(it).url }

    private fun field(form: Map<String, String>, name: String, what: String, url: (String) -> String): String? {
        val value = Py.strip(form[name].orEmpty())
        if (value.isEmpty()) return null
        val limit = SongForm.PICK_LIMITS.getValue(name)
        if (Py.len(value) > limit) throw Refused(400, "Too long", "The $name is too long: $limit characters at most.")
        return try {
            url(value)
        } catch (e: OverridesError) {
            throw Refused(400, "Not a pick", "That isn't $what: ${e.message}")
        }
    }

    /**
     * search_routes._library_song: the song of the library a lookup is about: the one `song` names (by its id); else
     * the one the UG pick [ug] is (matched to it, or by its names' forms: [Mine]); else the one of the form's artist
     * and title, by its identity key. Null for a song new to the library.
     */
    fun librarySong(db: Db, form: Map<String, String>, ug: Pair<String, String>?): SongRow? {
        if (Py.strip(form["song"].orEmpty()).isNotEmpty()) return song(db, songId(form.getValue("song")))
        val artist = Py.strip(form["artist"].orEmpty())
        val title = Py.strip(form["title"].orEmpty())
        if (ug != null) Mine(Songs.list(db), SongForms()).songFor(ug.first, ug.second, artist, title)?.let { return it }
        if (artist.isNotEmpty() && title.isNotEmpty()) return Songs.byKey(db, Normalize.identityKey(artist, title))
        return null
    }

    // --- the requests --------------------------------------------------------------------------------------------

    /**
     * search_routes.lookup_request (POST /lookup, Get it): a song looked up now, a job of `caracole get --progress`: a
     * song of the library as it is (by `song`, its UG pick or its names), with none of the form's album or length,
     * else a new one (the form's names as wanted.txt's line would hold them). One text, `q`, in place of the artist and
     * the title, is read as every page reads one (SongForm.named). Its picks go on the command line: `--ug`, `--tab`,
     * `--lacuerda`, `--harptabs`, `--gametabs`.
     */
    fun lookupRequest(database: Database, asked: Map<String, String>): LookupAsk {
        val form = SongForm.named(database, asked)
        val (pick, ug) = pick(form)
        val lacuerda = lacuerdaField(form)
        val harptabs = harptabsField(form)
        val gametabs = gametabsField(form)
        val found = database.read { db -> librarySong(db, form, ug) }
        val song = found?.let { NamedSong(it.artist, it.title, null, null) } ?: SongForm.song(form)
        // the song as your library has it: no second song, and no new source for it; else caracole serve's note
        // names its wanted.txt line, and the phone writes none
        val note = found?.let { "In your library as ${it.display}." }.orEmpty()
        val commands = JobCommands.lookupSteps(song.artist, song.title, album = song.album, durationMs = song.durationMs,
                                               ug = pick.getValue("ug").ifEmpty { null },
                                               tab = pick.getValue("tab").ifEmpty { null },
                                               lacuerda = lacuerda, harptabs = harptabs, gametabs = gametabs)
        val full = if (found != null) {
            "$note The queue is full, so it wasn't looked up now: the nightly run looks for it, or ask again once the " +
                "queue empties."
        } else NOTHING_ADDED
        return LookupAsk(spec("Fetch ${song.artist} - ${song.title}", found?.key ?: song.key, commands,
                              display = found?.display ?: song.display, note = note, fetching = true), full)
    }

    /** library_routes.request with `fetch` (Fetch now): [song], as the request form names it, looked up now, with the
     * LaCuerda song or version it picked ([lacuerda]); `caracole get` adds it. */
    fun fetchNow(song: NamedSong, lacuerda: String?): LookupAsk = LookupAsk(
        spec("Fetch ${song.display}", song.key,
             JobCommands.lookupSteps(song.artist, song.title, album = song.album, durationMs = song.durationMs,
                                     lacuerda = lacuerda),
             display = song.display, fetching = true),
        NOTHING_ADDED,
    )

    /** library_routes.fetch (POST /fetch, Fetch now on a card): a song of the library looked up now, unless it is
     * ignored or a review must come first. */
    fun fetch(database: Database, form: Map<String, String>): LookupAsk {
        val asked = songId(form["song"].orEmpty())
        val (song, overrides) = database.read { db -> overrides(db).let { song(db, asked) to it } }
        notIgnored(song, overrides)
        if (reviewFirst(song, overrides)) {
            throw Refused(409, "Review it first",
                          "caracole isn't sure which Ultimate Guitar song ${song.display} is, so it can't fetch it " +
                              "yet: run caracole review, or settle it in overrides.toml, then fetch it.")
        }
        return LookupAsk(spec("Fetch ${song.display}", song.key, JobCommands.lookupSteps(song.artist, song.title),
                              display = song.display, fetching = true), QUEUE_FULL)
    }

    /**
     * search_routes.lacuerda_read (POST /lacuerda/artist, an artist's Songs): a LaCuerda artist's page read into the
     * index, `caracole lacuerda --artist`, a job of its own: by the `slug` of a page the index lists, or by a `name`
     * (its spaces collapsed), for an artist under a letter of LaCuerda's listings not read yet.
     */
    fun lacuerdaRead(database: Database, form: Map<String, String>): LookupAsk {
        val slug = Py.strip(form["slug"].orEmpty())
        val name = Py.split(form["name"].orEmpty()).joinToString(" ")
        val (display, key, who) = if (name.isNotEmpty() && slug.isEmpty()) {
            if (Py.len(name) > SongForm.LIMITS.getValue("artist") || LaCuerda.artistSlugCandidates(name).isEmpty()) {
                throw Refused(400, "Not an artist", "That name makes no LaCuerda artist page's address.")
            }
            Triple(name, JobCommands.LACUERDA_ARTIST + "name:" + LaCuerda.nameKey(name), name)
        } else {
            if (!SLUG.matches(slug)) {
                throw Refused(400, "Not an artist", "Which artist? The form names no LaCuerda artist page.")
            }
            val named = database.read { db -> LaCuerda.lacuerdaArtist(db, slug) }
                ?: throw Refused(404, "No such artist", "LaCuerda's index has no such artist.")
            Triple(named.artist, JobCommands.LACUERDA_ARTIST + slug, slug)
        }
        return LookupAsk(spec("Read the page of $display on LaCuerda", key, JobCommands.lacuerdaArtistSteps(who, display),
                              display = "$display on LaCuerda"), QUEUE_FULL)
    }

    /** search_routes.harptabs_read (POST /harptabs/artist): a harptabs.com artist's page read into its index, `caracole
     * harptabs --artist`, a job of its own, by the `path` of a page the sitemap lists. */
    fun harptabsRead(database: Database, form: Map<String, String>): LookupAsk {
        val path = Py.strip(form["path"].orEmpty())
        if (!HARP_ARTIST.matches(path)) {
            throw Refused(400, "Not an artist", "Which artist? The form names no harptabs.com artist page.")
        }
        val named = database.read { db -> SiteSearch.harptabsArtist(db, path) }
            ?: throw Refused(404, "No such artist", "harptabs.com's index has no such artist.")
        return LookupAsk(spec("Read the page of ${named.artist} on harptabs.com", JobCommands.HARPTABS_ARTIST + path,
                              JobCommands.harptabsArtistSteps(path, named.artist),
                              display = "${named.artist} on harptabs.com"), QUEUE_FULL)
    }

    /**
     * search_routes.lacuerda_search (POST /lacuerda/search): LaCuerda's search for a query (`q`, its spaces collapsed),
     * `caracole lacuerda --search --progress`, a job of its own, `--auto` unless asked `by_hand`; under the query's key,
     * so a query asked again under any spelling LaCuerda reads the same is that job. Refused as its gate (read at [now]
     * under [config]) refuses it: no word LaCuerda reads (400), LaCuerda's index or your library has the song or the
     * query was asked within 30 days (409), a cooldown or the hour's lookups spent, or, without `by_hand`, the page's
     * share of them spent or a search that failed lately (429). With [searchesLacuerda] false, the gate is none, as
     * `WebApp(searches_lacuerda=False)` has it: every query is found already.
     */
    fun lacuerdaSearch(database: Database, config: PhoneConfig, form: Map<String, String>, searchesLacuerda: Boolean,
                       now: Instant): LookupAsk {
        val q = Py.split(form["q"].orEmpty()).joinToString(" ")
        val byHand = form["by_hand"].orEmpty() == "1"
        if (q.isEmpty() || Py.len(q) > QUERY_LIMIT) {
            throw Refused(400, "Not a query", "Which query? A search is 1 to $QUERY_LIMIT characters.")
        }
        if (LaCuerdaSearch.queryKey(q).isNullOrEmpty()) {
            throw Refused(400, "Not a query", "LaCuerda's search reads only words of 4 letters or more: “$q” has none.")
        }
        val said = if (searchesLacuerda) database.read { db -> LaCuerdaSearch.gate(config, db, q, now) } else null
        when {
            said == null -> throw Refused(409, "Found already",
                                          "Your library or LaCuerda's index has “$q” already: no search needed.")
            said.state == "asked" -> throw Refused(409, "Searched already",
                                                   "LaCuerda was asked for “$q” within 30 days: what it answered is in " +
                                                       "its index.")
            said.state == "spent" -> throw Refused(429, "Not now",
                                                   "LaCuerda is cooling down after a block, or this hour's lookups to " +
                                                       "it are spent: ask again later.")
            said.state == "failed" && !byHand -> throw Refused(429, "Not by itself",
                                                               "${said.why.orEmpty().removeSuffix(".")}: press Ask " +
                                                                   "LaCuerda to ask anyway.")
            said.state == "button" && !byHand -> throw Refused(429, "Not by itself",
                                                               "This hour's $SEARCHES_PER_HOUR searches " +
                                                                   "the page sends by itself are spent: press Ask " +
                                                                   "LaCuerda to ask anyway.")
        }
        return LookupAsk(spec("Search LaCuerda for “$q”", JobCommands.LACUERDA_SEARCH + said!!.key,
                              JobCommands.lacuerdaSearchSteps(q, auto = !byHand), display = "“$q” on LaCuerda"),
                         QUEUE_FULL)
    }

    /**
     * versions_routes.versions_post's Fetch them (POST /versions/keep-more, by `song`, the library page's card alone
     * posts it): the song's UG versions not kept yet, as many as a lookup may, `caracole versions --keep-more
     * --progress`, under the song's key; refused when none is left to keep (sheet_versions.may_keep under [config]'s
     * rank), then for a song ignored.
     */
    fun keepMore(database: Database, config: PhoneConfig, form: Map<String, String>): LookupAsk {
        val asked = songId(form["song"].orEmpty())
        val (song, overrides, toKeep) = database.read { db ->
            val overrides = overrides(db)
            val song = song(db, asked)
            val versions = SheetVersions.inLibrary(db, song.id, config.rank)
            Triple(song, overrides, SheetVersions.mayKeep(db, song.id, versions, overrides.block))
        }
        if (toKeep.isEmpty()) {
            throw Refused(409, "Nothing to do", "Nothing is left to keep of ${song.display}: every Ultimate Guitar " +
                                                "version caracole may keep is kept already, or can't be.")
        }
        notIgnored(song, overrides)
        return LookupAsk(spec("Fetch the other versions of ${song.display}", song.key,
                              JobCommands.versionSteps(song.artist, song.title, keepMore = true),
                              display = song.display, fetching = true), QUEUE_FULL)
    }

    /** A job of [commands] under [key], of the kind the history reads it back as (JobCommands.kindOf), its stages
     * those its commands report. */
    fun spec(title: String, key: String, commands: List<Command>, display: String = "", note: String = "",
             fetching: Boolean = false): JobSpec = JobSpec(
        title = title, key = key, kind = JobCommands.kindOf(key, commands.map { it.args }, emptyList()),
        stages = emptyList(), display = display, commands = commands, fetching = fetching, note = note,
    )

    /** app.py's QUEUE_FULL. */
    private const val QUEUE_FULL = JobQueue.QUEUE_FULL
}
