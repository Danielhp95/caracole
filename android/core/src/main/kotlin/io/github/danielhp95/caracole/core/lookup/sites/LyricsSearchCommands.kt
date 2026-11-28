package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lyrics.AzLyrics
import io.github.danielhp95.caracole.core.http.AzLyricsParseError
import io.github.danielhp95.caracole.core.lyrics.Lrclib
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.lyrics.Megalobiz
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.http.MegalobizParseError
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.youtube.Records
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * lyrics_search.py on the phone, `caracole lyrics --song X --as "A - T"` (commands/lyrics.py's `_lyrics_as`): what
 * the three lyrics sites list under a name the owner types, for a song whose own name finds nothing there.
 *
 * [search] notes the name first (`[lyrics]`' `as`, OverrideWriters.setLyricsName; taken out for the song's own name)
 * and, for a new one, asks the question anew ([askAnew]); then asks each site once, by the command's asking (the lookup
 * pace, a client a site; a block cooling the site down, an error counted, by the asking, never here; a site off or
 * cooling passed over first, [notNow], in the search's words):
 *
 * - LRCLIB's `/api/search` for the typed name, then `/api/get` with it and the audio's length only when no record of
 *   the search fits it ([Lrclib.pickCandidate]): each record with lyrics a row, an instrumental or empty one counted;
 *   its get a second ask of the same client, whose block, spent budget or error leaves the search's rows ([NOT_MADE]);
 * - Megalobiz's search ([Megalobiz.searchParams]): each result a row, its lyrics never asked;
 * - AZLyrics' page of the typed artist ([AzLyrics.artistUrl]), none asked for a name with no Latin letter or digit:
 *   the songs on it whose title fits the typed one.
 *
 * So 2 to 4 requests, each through the HTTP cache while it is younger than [PICKABLE_FOR] (`max_age`). The rows are
 * kept in kv `lyrics-search:<song id>` ([KV], Search.json, PyJson as `kv_set_json` writes), never under an id another
 * song took meanwhile. A good run is recorded where Python records it: a site whose own requests got an answer
 * (Health.answeredAny of the command's run) and met no block. [lines] are the command's printed lines, its last
 * [lastLine]'s ("Searched: ", "Nothing found: ", "Not searched: "), which the Journal reads. The card's words of a kept
 * search ([notes], [rowFacts], [askedLine], [far]) are here too, for the routes. vectors/lookup/lyrics_search.jsonl
 * holds it to Python's (tests/test_conformance_lyrics_search.py, LyricsSearchReplay).
 *
 * What the phone does otherwise: a block alerts once (the asking's, as every lookup's on the phone); the audio's
 * length is the line's, else its YouTube video's ([audioLength]), else what [fileLength] reads of its own audio file
 * (none on the phone's core: the computer reads it with mutagen).
 */
object LyricsSearchCommands {
    const val KV = "lyrics-search:"
    val PICKABLE_FOR: Duration = Duration.ofDays(7)
    const val MOST_ROWS = 40
    const val FAR = 10.0
    val SITES: List<String> = listOf("lrclib", "megalobiz", "azlyrics")
    const val ROWS = "rows"
    const val NONE = "none"
    const val OFF = "off"
    const val COOLING = "cooling"
    const val SPENT = "spent"
    const val BLOCKED = "blocked"
    const val FAILED = "failed"
    val STATES: List<String> = listOf(ROWS, NONE, OFF, COOLING, SPENT, BLOCKED, FAILED)
    private val ANSWERED = setOf(ROWS, NONE)
    const val NOT_MADE = "; its ask by the exact name not made: "

    private val AZLYRICS_PAGE by lazy { PyRegex.compile("https://www\\.azlyrics\\.com/lyrics/([a-z0-9-]+/[a-z0-9-]+)\\.html") }
    private val RECORD_IDS by lazy {
        val number = PyRegex.compile("[1-9][0-9]{0,11}")
        mapOf("lrclib" to number, "megalobiz" to number, "azlyrics" to PyRegex.compile("[a-z0-9-]+/[a-z0-9-]+"))
    }
    private val SHOWN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)
    private val PAGE_ACCEPT = setOf(200, 404)  // an artist's page AZLyrics hasn't: no artist page

    /** lyrics_search.Row: a record a site listed, `record` as `[lyrics]` writes it. */
    data class Row(val record: String, val site: String, val artist: String, val title: String, val album: String,
                   val duration: Double?, val timed: Boolean, val best: Boolean = false, val fits: Boolean = false) {
        fun json(): JsonObject = JsonObject(linkedMapOf(
            "record" to JsonPrimitive(record), "site" to JsonPrimitive(site), "artist" to JsonPrimitive(artist),
            "title" to JsonPrimitive(title), "album" to JsonPrimitive(album),
            "duration" to (duration?.let(PyJson::float) ?: JsonNull), "timed" to JsonPrimitive(timed),
            "best" to JsonPrimitive(best), "fits" to JsonPrimitive(fits)))
    }

    /** lyrics_search.Search: a song's search, when, the name asked, the audio's length, LRCLIB's exact query, the
     * rows, each site's words and state, and the instrumental records not listed. */
    data class Search(val at: String, val asked: Pair<String, String>, val length: Double?,
                      val lrclib: List<Pair<String, String>>, val rows: List<Row>, val said: Map<String, String>,
                      val state: Map<String, String>, val instrumental: BigInteger = BigInteger.ZERO) {
        val name: String get() = "${asked.first} - ${asked.second}"

        fun json(): JsonObject = JsonObject(linkedMapOf(
            "at" to JsonPrimitive(at), "as" to JsonArray(listOf(JsonPrimitive(asked.first), JsonPrimitive(asked.second))),
            "length" to (length?.let(PyJson::float) ?: JsonNull),
            "lrclib" to JsonObject(lrclib.associate { (k, v) -> k to JsonPrimitive(v) }),
            "rows" to JsonArray(rows.map { it.json() }),
            "said" to JsonObject(said.mapValues { JsonPrimitive(it.value) }),
            "state" to JsonObject(state.mapValues { JsonPrimitive(it.value) }),
            "instrumental" to JsonPrimitive(instrumental)))
    }

    /** lyrics_search.Note: a line a search says beside its rows. */
    data class Note(val site: String, val state: String, val line: String)

    // --- the name -------------------------------------------------------------------------------------------------

    /** lyrics_search.typed_name: the artist and the title a name typed says (SongNames.readNames, the library's known
     * artists by [songs]), each part cleaned as `as` is (Lyrics.askedPart); null for none, or a part of nothing. */
    fun typedName(db: Db?, text: String, songs: List<SongRow>): Pair<String, String>? {
        val kept = StringBuilder()
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (PyUnicode.isSpace(cp) || PyUnicode.category(cp) != "Cc") kept.appendCodePoint(cp)
            i += Character.charCount(cp)
        }
        val named = SongNames.readNames(db, kept.toString(), songs) ?: return null
        val artist = Lyrics.askedPart(named.first)
        val title = Lyrics.askedPart(named.second)
        return if (artist.isNotEmpty() && title.isNotEmpty()) artist to title else null
    }

    /** lyrics_search.is_own_name: [name] is the song's own, by its identity key. */
    fun isOwnName(song: SongRow, name: Pair<String, String>): Boolean = Normalize.identityKey(name.first, name.second) == song.key

    /**
     * lyrics_search.audio_length: the song's length, its line's first, else its YouTube video's (youtube_fetch's
     * `youtube_audio`: the record's video while the song's audio is the file YouTube gave), else [fileLength] of its
     * audio file; null for none.
     */
    fun audioLength(db: Db, song: SongRow, fileLength: (String) -> Double? = { null }): Double? {
        song.durationMs?.takeIf { it != 0L }?.let { return it.toDouble() / 1000.0 }
        val record = Records.load(db, song.id)
        val video = record.video.takeIf { !record.audio.isNullOrEmpty() && song.audioPath == record.audio }
        video?.duration?.takeIf { it != 0.0 }?.let { return it }
        return song.audioPath?.let(fileLength)
    }

    // --- the search -----------------------------------------------------------------------------------------------

    private class Found(val rows: MutableList<Row> = ArrayList(), var best: String? = null, var said: String = "",
                        var instrumental: Int = 0, var state: String? = null)

    /** lyrics_search.search_lyrics: [name] noted under the song's `[lyrics]`, then each site asked under it, the rows
     * kept; [config] the phone's settings the command's asking was made with, [fileLength] as [audioLength]'s. */
    fun search(c: CommandContext, song: SongRow, name: Pair<String, String>, config: PhoneConfig = PhoneConfig.read(c.db),
               fileLength: (String) -> Double? = { null }): Search {
        val db = c.db
        val now = c.now
        if (OverrideWriters.setLyricsName(db, song.display, if (isOwnName(song, name)) null else "${name.first} - ${name.second}")) {
            askAnew(db, song, now, renamed = true)
        }
        val length = audioLength(db, song, fileLength)
        val query = Lrclib.searchQuery(name.first, name.second)
        val finds = LinkedHashMap<String, Found>()
        for (site in SITES) {
            if (site == "azlyrics" && AzLyrics.artistUrl(name.first) == null) {
                finds[site] = Found(said = "no artist page for ${name.first}", state = NONE)
                continue
            }
            finds[site] = ask(c, config, site, name, length, query)
        }
        val search = Search(at = Stamps.of(now), asked = name, length = length, lrclib = query, rows = ordered(finds),
                            said = SITES.associateWith { said(finds.getValue(it)) },
                            state = SITES.associateWith { finds.getValue(it).state ?: NONE },
                            instrumental = BigInteger.valueOf(finds.values.sumOf { it.instrumental }.toLong()))
        if (db.one("SELECT 1 FROM songs WHERE id = ? AND key = ?", song.id, song.key) { true } == true) {
            db.kvSetJson("$KV${song.id}", search.json())
        }
        return search
    }

    /**
     * lyrics_search.ask_anew: a `[lyrics]` entry changed is a new question: LRCLIB's failure and Megalobiz's and
     * AZLyrics' misses forgotten, a song with no lyrics pending again with no `lyrics_at`; found lyrics kept.
     * [renamed], a search's new name: only a song pending or missing is asked anew.
     */
    fun askAnew(db: Db, song: SongRow, now: Instant, renamed: Boolean = false) {
        if (renamed && song.lyricsStatus !in setOf("pending", "missing")) return
        db.savepoint("ask_anew") {
            for (prefix in listOf(Lrclib.FAILED, Megalobiz.CHECKED, AzLyrics.CHECKED)) db.kvDelete("$prefix${song.id}")
            if (song.lyricsStatus != "found") {
                Versions.updateSong(db, song.id, mapOf("lyrics_status" to "pending", "lyrics_at" to null), Stamps.of(now))
            }
        }
    }

    /** lyrics_search._Asking: one site asked (its work [Asked] through the command's asking), in its words and
     * state; its good run recorded once its own requests got an answer and none met a block. */
    private fun ask(c: CommandContext, config: PhoneConfig, site: String, name: Pair<String, String>, length: Double?,
                    query: List<Pair<String, String>>): Found {
        notNow(config, c.db, c.now, site)?.let { (state, said) -> return Found(said = said, state = state) }
        val asked = c.asking.ask(site) { client ->
            when (site) {
                "lrclib" -> lrclibSearch(client, name, length, query)
                "megalobiz" -> megalobiz(client, name, length)
                else -> azlyrics(client, name)
            }
        }
        val first = when (asked) {
            is Asked.Done -> asked.value
            else -> return stopped(c, config, site, asked).let { (state, said) -> Found(said = said, state = state) }
        }
        val (found, got) = if (site == "lrclib") lrclibGet(c, first, name, length) else (first.found to null)
        if (got !is Asked.Blocked && Health.answeredAny(c.db, runOf(c), site, c.asking.requests[site] ?: 0)) {
            Health.recordOk(c.db, site, c.now)
        }
        if (got != null && got !is Asked.Done) {
            val (state, said) = stopped(c, config, site, got)
            val listed = if (found.rows.isNotEmpty()) "listed ${found.rows.size}" else "nothing listed"
            found.said = "$listed$NOT_MADE$said"
            found.state = if (found.rows.isNotEmpty()) ROWS else state
            return found
        }
        found.state = if (found.rows.isNotEmpty()) ROWS else NONE
        return found
    }

    /** The run the command's requests are logged under: the lookup's at [CommandContext.now] (`lookup_run_id`), as
     * its runner's asking logs them (LookupJobs.context). */
    internal fun runOf(c: CommandContext): String = LookupWords.lookupRunOf(c.now)

    /** What a site's first ask came to: its rows so far, and LRCLIB's search's records to rank. */
    private class First(val found: Found, val listed: LinkedHashMap<String, JsonObject> = LinkedHashMap(),
                        val seen: MutableSet<String> = HashSet())

    /** lyrics_search._lrclib's search: each record with lyrics listed, an instrumental or empty one counted. */
    private fun lrclibSearch(client: Client, name: Pair<String, String>, length: Double?,
                             query: List<Pair<String, String>>): First {
        val answered = Lrclib.searchRecords(client, query, maxAge = PICKABLE_FOR)
        val first = First(Found())
        for (cand in answered) take(first, cand)
        val best = Lrclib.pickCandidate(first.listed.values.toList(), name.first, name.second, length)
        first.found.best = best?.let { b -> first.listed.entries.first { it.value === b }.key }
        return first
    }

    /** lyrics_search._lrclib's `take`: a record once by its id, listed when it has lyrics and an id of `[lyrics]`'
     * shape, else (no lyrics) counted. */
    private fun take(first: First, cand: JsonElement) {
        if (cand !is JsonObject) return
        val id = PyValues.repr(cand["id"])
        if (id in first.seen) return
        first.seen += id
        if (!Lyrics.fromRecord(cand).hasLyrics) {
            first.found.instrumental++
            return
        }
        record("lrclib", cand["id"])?.let { first.listed[it] = cand }
    }

    /**
     * lyrics_search._lrclib's get and rows: with no record of the search fitting, LRCLIB's own match of the name with
     * the audio's length, a second ask of its client, its record taken as the search's are and the best where it is
     * one; then a row a record listed. The get's [Asked] when it was asked and didn't answer.
     */
    private fun lrclibGet(c: CommandContext, first: First, name: Pair<String, String>,
                          length: Double?): Pair<Found, Asked<*>?> {
        val found = first.found
        var got: Asked<*>? = null
        if (found.best == null) {
            val params = Lrclib.getParams(name.first, name.second, album = null, durationS = length)
            val asked = c.asking.ask("lrclib") { client -> Lrclib.getMatch(client, params, maxAge = PICKABLE_FOR) }
            if (asked is Asked.Done) {
                asked.value?.let { record ->
                    take(first, record)
                    val listed = record("lrclib", record["id"])
                    if (listed != null && listed in first.listed) found.best = listed
                }
            } else {
                got = asked
            }
        }
        for ((record, cand) in first.listed) {
            val lyrics = Lyrics.fromRecord(cand)
            val gotArtist = str(cand["artistName"])
            val gotTitle = str(cand["trackName"]?.takeIf(PyValues::truthy) ?: cand["name"])
            val fit = Lrclib.fits(name.first, name.second, length, gotArtist, gotTitle, lyrics.duration)
            val album = (cand["albumName"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: ""
            found.rows += Row(record, "lrclib", gotArtist, gotTitle, album, lyrics.duration,
                              !lyrics.synced.isNullOrEmpty(), fits = fit != null)
        }
        return found to got
    }

    /** lyrics_search._megalobiz: Megalobiz's search, each result a row once by its record. */
    private fun megalobiz(client: Client, name: Pair<String, String>, length: Double?): First {
        val (artist, title) = name
        val params = Megalobiz.searchParams(artist, title, length)
        val resp = client.get(Megalobiz.SEARCH, params = params, maxAge = PICKABLE_FOR)
        val results = HttpRules.readOnceMore(client, resp, Megalobiz.SEARCH, { it is MegalobizParseError },
                                             params = params) { Megalobiz.parseSearch(it) }
        val best = Megalobiz.pickResult(results, artist, title, length)
        val found = Found()
        for (result in results) {
            val record = record("megalobiz", result.id) ?: continue
            if (found.rows.any { it.record == record }) continue
            val fit = Py.strip(result.artist).isNotEmpty() && !Lrclib.anotherVersion(title, result.title) &&
                Lrclib.fits(artist, title, length, result.artist, result.title, result.duration) != null
            found.rows += Row(record, "megalobiz", result.artist, result.title, "", result.duration, true, fits = fit)
            if (result === best) found.best = record
        }
        return First(found)
    }

    /** lyrics_search._azlyrics: the typed artist's page, the songs on it whose title fits the typed one. */
    private fun azlyrics(client: Client, name: Pair<String, String>): First {
        val (artist, title) = name
        val found = Found()
        val url = AzLyrics.artistUrl(artist) ?: return First(found.also { it.said = "no artist page for $artist" })
        val resp = client.get(url, accept = PAGE_ACCEPT, maxAge = PICKABLE_FOR)
        if (resp.status == 404) return First(found.also { it.said = "no artist page for $artist" })
        val page = HttpRules.readOnceMore(client, resp, url, { it is AzLyricsParseError }, accept = PAGE_ACCEPT) {
            AzLyrics.parseArtist(it)
        }
        val best = AzLyrics.pickSong(page, artist, title)
        for (song in page.songs) {
            if (Lrclib.anotherVersion(title, song.title) ||
                Lrclib.fits(artist, title, null, page.name, song.title, null) == null) continue
            val address = PyRe.fullmatch(AZLYRICS_PAGE, song.url)
            val record = address?.groups?.get(1)?.value?.let { record("azlyrics", JsonPrimitive(it)) } ?: continue
            if (found.rows.any { it.record == record }) continue
            found.rows += Row(record, "azlyrics", page.name, song.title, "", null, false, fits = true)
            if (song === best) found.best = record
        }
        if (found.rows.isEmpty()) found.said = "no song titled $title on ${page.name}'s page"
        return First(found)
    }

    /** lyrics_search.not_now: why a lookup asks [site] nothing now (turned off, cooling down), as a state and words;
     * null to ask it. A search's and a pick's alike. */
    fun notNow(config: PhoneConfig, db: Db, now: Instant, site: String): Pair<String, String>? {
        val name = LookupWords.name(site)
        if (!config.provider(site).enabled) return OFF to "$name is off (caracole.toml)"
        if (Health.isCooling(db, site, now)) return COOLING to "waiting out $name until ${shown(Health.state(db, site).cooldownUntil)}"
        return null
    }

    /**
     * lyrics_search.stopped: what stopped an ask of [site] ([asked], which the asking recorded: a block, an error), as
     * a state and words: [whose] asks a lookup's budget was ("this pick's"), [why] the block's reason said too.
     */
    fun stopped(c: CommandContext, config: PhoneConfig, site: String, asked: Asked<*>, whose: String = "this search's",
                why: Boolean = false): Pair<String, String> {
        val name = LookupWords.name(site)
        val p = config.provider(site)
        return when (asked) {
            is Asked.Blocked -> {
                val reason = if (why) " (${asked.error.message})" else ""
                BLOCKED to "$name turned us back$reason; no asks until ${shown(asked.state.cooldownUntil)}"
            }
            is Asked.Spent -> when {
                p.perDay != null && Pace.requestsToday(c.db, site, c.now) >= p.perDay ->
                    SPENT to "no more asks of $name today (${p.perDay} spent)"
                asked.hour -> SPENT to "no more asks of $name this hour (${p.lookupPerHour} spent)"
                else -> SPENT to "$whose ${p.lookupRequests} asks of $name are spent"
            }
            is Asked.Failed -> FAILED to "$name failed (${asked.error.message})"
            is Asked.Off -> OFF to asked.why
            is Asked.Cooling -> COOLING to "waiting out $name until ${shown(asked.until)}"
            is Asked.Done -> throw IllegalArgumentException("nothing stopped an ask that answered")
        }
    }

    private fun said(found: Found): String = found.said.ifEmpty {
        if (found.rows.isNotEmpty()) "listed ${found.rows.size}" else "nothing listed"
    }

    /** lyrics_search._ordered: the best fit first, then the rows that fit, then the rest, at most [MOST_ROWS]. */
    private fun ordered(finds: Map<String, Found>): List<Row> {
        val best = SITES.firstNotNullOfOrNull { finds[it]?.best }
        val rows = SITES.flatMap { finds.getValue(it).rows }
        val first = rows.filter { it.record == best }.map { it.copy(best = true) }
        val fitting = rows.filter { it.fits && it.record != best }
        val rest = rows.filter { !it.fits && it.record != best }
        return (first + fitting + rest).take(MOST_ROWS)
    }

    // --- its words ------------------------------------------------------------------------------------------------

    /** lyrics_search.last_line: "Searched: ", "Nothing found: " or "Not searched: ". */
    fun lastLine(search: Search): String {
        val quoted = "“${search.name}”"
        val listing = SITES.filter { site -> search.rows.any { it.site == site } }
        if (listing.isNotEmpty()) {
            return "Searched: ${joined(listing)} ${if (listing.size == 1) "lists" else "list"} " +
                "${plural(search.rows.size, "record")} for $quoted."
        }
        val answered = SITES.filter { search.state[it] in ANSWERED }
        val left = SITES.filter { it !in answered && search.state[it] != OFF }
        if (left.isNotEmpty()) {
            val why = left.map { site ->
                val said = search.said[site].orEmpty()
                val at = said.indexOf(NOT_MADE)
                if (at >= 0) said.substring(at + NOT_MADE.length).ifEmpty { said } else said
            }
            return "Not searched: ${why.joinToString("; ")}; try again later."
        }
        if (answered.isNotEmpty()) {
            return "Nothing found: ${joined(answered)} ${if (answered.size == 1) "lists" else "list"} nothing for $quoted."
        }
        return "Not searched: every lyrics site is off (caracole.toml); nothing asked."
    }

    /** lyrics_search.notes: each site that listed no row in its words, then the instrumental records counted. */
    fun notes(search: Search): List<Note> {
        val out = ArrayList<Note>()
        for (site in SITES) {
            if (search.rows.any { it.site == site }) continue
            val words = search.said[site].orEmpty()
            val who = LookupWords.name(site)
            val line = if (who in words) PyUnicode.upper(Py.slice(words, 0, 1)) + Py.slice(words, 1, null) else "$who: $words"
            out += Note(site, search.state[site] ?: NONE, if (line.endsWith(".")) line else "$line.")
        }
        if (search.instrumental.signum() != 0) {
            val n = search.instrumental
            val one = n == BigInteger.ONE
            out += Note("", "instrumental", "$n ${if (one) "record" else "records"} marked instrumental " +
                "${if (one) "isn't" else "aren't"} listed.")
        }
        return out
    }

    /** lyrics_search.far: a row more than [FAR] seconds off the audio's [length]. */
    fun far(row: Row, length: Double?): Boolean =
        row.duration != null && length != null && Math.abs(row.duration - length) > FAR

    /** lyrics_search.clock: a length as m:ss. */
    fun clock(seconds: Double): String {
        val whole = PyFormat.roundHalfEven(seconds)
        return "${Math.floorDiv(whole, 60L)}:${Math.floorMod(whole, 60L).toString().padStart(2, '0')}"
    }

    /** lyrics_search.row_facts: "Artist - Title · album · 4:31, audio 3:45 · timed". */
    fun rowFacts(row: Row, length: Double?): String {
        val parts = mutableListOf("${row.artist.ifEmpty { "(no artist)" }} - ${row.title}")
        if (row.album.isNotEmpty()) parts += row.album
        if (row.duration != null && row.duration != 0.0) {
            parts += clock(row.duration) + if (far(row, length) && length != null && length != 0.0) ", audio ${clock(length)}" else ""
        }
        if (row.timed) parts += "timed"
        return parts.joinToString(" · ")
    }

    /** lyrics_search.asked_line: "Asked as “A - T” on 26/11/26.", and past its week what to do. */
    fun askedLine(search: Search, now: Instant): String {
        val day = Py.slice(search.at, 0, 10)
        val whenSaid = if (day.length == 10) "${day.substring(8, 10)}/${day.substring(5, 7)}/${day.substring(2, 4)}" else search.at
        val stale = if (pickable(search, now)) "" else ": over a week ago. Search again to pick one"
        return "Asked as “${search.name}” on $whenSaid$stale."
    }

    /** The lines `caracole lyrics --as` prints for [search] of [song] under [name], its last [lastLine]. */
    fun lines(song: SongRow, name: Pair<String, String>, search: Search): List<String> {
        val out = ArrayList<String>()
        val audio = search.length?.takeIf { it != 0.0 }?.let { " (its audio is ${clock(it)})" } ?: ""
        val noted = if (isOwnName(song, name)) "; the song's own name, so none is kept under [lyrics]" else "; noted under [lyrics]"
        out += "Asked as ${search.name}$audio$noted."
        for ((n, row) in search.rows.withIndex()) {
            out += "${(n + 1).toString().padStart(2)}. ${LookupWords.name(row.site).padEnd(10)} ${rowFacts(row, search.length)}" +
                if (row.best) " · best fit" else ""
        }
        for (note in notes(search)) out += note.line
        if (search.rows.isNotEmpty()) out += "Take one: caracole lyrics --song ${shellQuoted(song.display)} --pick 1"
        out += lastLine(search)
        return out
    }

    // --- what is kept ---------------------------------------------------------------------------------------------

    /** lyrics_search.kept_search: the song's last search while it may be picked from; else null. */
    fun keptSearch(db: Db, songId: Long, now: Instant): Search? = lastSearch(db, songId, now)?.takeIf { pickable(it, now) }

    /** lyrics_search.pickable: made [PICKABLE_FOR] ago at most. */
    fun pickable(search: Search, now: Instant): Boolean = inItsWeek(search.at, now)

    private fun inItsWeek(at: String, now: Instant): Boolean {
        val whenMade = parse(at) ?: return false
        return Stamps.micros(now) - whenMade <= PICKABLE_FOR.toMillis() * 1000
    }

    /** stamps.parse: null for no time; a time out of range raises, as Python's OverflowError does. */
    private fun parse(at: String): Long? = Stamps.parse(at)

    /** lyrics_search.row_of: the row of [search] that names [record]. */
    fun rowOf(search: Search, record: String): Row? = search.rows.firstOrNull { it.record == record }

    /**
     * lyrics_search.last_search: the song's last search as kept; past [PICKABLE_FOR] only the name it asked under and
     * when; null for none, or one that won't read (a record kept before each site's state was among them). A kv text
     * that isn't JSON is IllegalArgumentException, as `kv_get_json` raises Python's ValueError; one nested past
     * PyJson.MAX_DEPTH is none here (Python reads it, and it is no record of a search either).
     */
    fun lastSearch(db: Db, songId: Long, now: Instant): Search? {
        val text = db.kvGet("$KV$songId") ?: return null
        val kept = try {
            PyJson.loads(text)
        } catch (e: PyJson.RecursionError) {
            return null
        } as? JsonObject ?: return null
        val (at, asked) = asked(kept) ?: return null
        if (!inItsWeek(at, now)) return Search(at, asked, null, emptyList(), emptyList(), emptyMap(), emptyMap())
        val state = kept["state"] as? JsonObject ?: return null
        if (SITES.any { site -> PyValues.string(state[site]) !in STATES }) return null
        val rows = (kept["rows"] as? JsonArray)?.mapNotNull(::row).orEmpty()
        val query = (kept["lrclib"] as? JsonObject)?.entries
            ?.mapNotNull { (k, v) -> PyValues.string(v)?.let { k to it } }.orEmpty()
        val said = (kept["said"] as? JsonObject)?.entries
            ?.mapNotNull { (k, v) -> PyValues.string(v)?.let { k to it } }?.toMap().orEmpty()
        return Search(at, asked, PyValues.number(kept["length"]), query, rows, said,
                      SITES.associateWith { PyValues.string(state[it])!! }, PyValues.bigInt(kept["instrumental"]) ?: BigInteger.ZERO)
    }

    private fun asked(kept: JsonObject): Pair<String, Pair<String, String>>? {
        val at = PyValues.string(kept["at"]) ?: return null
        if (parse(at) == null) return null
        val parts = kept["as"] as? JsonArray ?: return null
        if (parts.size != 2 || parts.any { PyValues.string(it) == null }) return null
        return at to (PyValues.string(parts[0])!! to PyValues.string(parts[1])!!)
    }

    /** lyrics_search._row: a kept row, read as strictly as a site's answer. */
    private fun row(value: JsonElement): Row? {
        val o = value as? JsonObject ?: return null
        val site = PyValues.string(o["site"]) ?: return null
        val record = PyValues.string(o["record"]) ?: return null
        if (site !in SITES || !record.startsWith("$site:")) return null
        if (PyRe.fullmatch(RECORD_IDS.getValue(site), record.removePrefix("$site:")) == null) return null
        fun text(k: String) = PyValues.string(o[k]) ?: ""
        fun yes(k: String) = o[k] == JsonPrimitive(true)
        return Row(record, site, text("artist"), text("title"), text("album"), PyValues.number(o["duration"]),
                   yes("timed"), yes("best"), yes("fits"))
    }

    // --- Python's values ------------------------------------------------------------------------------------------

    /** lyrics_search._record: `site:id` for an id of the shape `[lyrics]` takes: an int (never a bool), AZLyrics' a
     * text as written. */
    private fun record(site: String, id: JsonElement?): String? {
        val text = (if (site == "azlyrics") PyValues.string(id) else null) ?: PyValues.bigInt(id)?.toString() ?: return null
        return if (PyRe.fullmatch(RECORD_IDS.getValue(site), text) != null) "$site:$text" else null
    }

    private fun record(site: String, id: BigInteger): String? = record(site, JsonPrimitive(id))

    /** `str(v or "")` of a record's name: a text as it is, a falsy value "", anything else as Python's str writes it
     * (its repr). */
    private fun str(v: JsonElement?): String = when {
        !PyValues.truthy(v) -> ""
        else -> PyValues.string(v) ?: PyValues.repr(v)
    }

    /** stamps.shown: "2026-11-03 12:30 UTC"; "?" for none. */
    private fun shown(at: Instant?): String = at?.let(SHOWN::format) ?: "?"

    /** logs.plural. */
    private fun plural(n: Int, noun: String): String = "$n ${if (n == 1) noun else noun + "s"}"

    private fun joined(sites: List<String>): String {
        val names = sites.map(LookupWords::name)
        return if (names.size == 1) names[0] else "${names.dropLast(1).joinToString(", ")} and ${names.last()}"
    }

    /** shlex.quote: as it is when every character is safe (ASCII letters, digits, `@%+=:,./-_`), else in single
     * quotes, each one in it closed, escaped and opened again. */
    fun shellQuoted(s: String): String {
        if (s.isEmpty()) return "''"
        val safe = s.all { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it in "@%+=:,./-_" }
        return if (safe) s else "'" + s.replace("'", "'\"'\"'") + "'"
    }

}
