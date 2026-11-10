package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.match.MatchCandidate
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * `caracole review --song=… --pick=…` (or `--none`, `--seen=…`) on the phone (commands/library.py's `_answer`): one
 * song's answer, with no question, as the picker of `POST /review` queues it.
 *
 * - **A pick** (a candidate's number in the list, or its ARTIST/SONG) writes `[match]`, and `[alias]` when the artist
 *   differs ([Review.writesAlias]); for a song not found, one of what `caracole search` finds for it
 *   ([Review.searchCandidates], less its `[reject]`), `[match]` alone.
 * - **None of these** writes the candidates [`--seen`], else every one it lists, under `[reject]`.
 * - Then the song is no longer in review, and its match is decided again (Matcher.matchAll), with, after an `[alias]`,
 *   every song with that artist among its artists (aliases apply by each artist's slug_key).
 *
 * The phone's overrides and its database are written in one savepoint of one `Database.writeBlocking`, so an answer
 * is written whole or not at all. Its lines are `caracole review`'s, but the one that names the pages it wrote
 * (`Wrote …`): the phone writes no _todo.md or index.html, its library page is made as it is asked for. A usage error,
 * a song named as no "Artist - Title" or an overrides.toml that can't be read exits 2 ([CommandExit]); a song not in
 * the library, one that needs no review, a candidate it hasn't or nothing to reject, 1; each in its words.
 * vectors/web/review.jsonl's `caracole review` records hold it to the computer's (ReviewReplay).
 *
 * Without `--pick` or `--none` caracole review asks its questions in a terminal: the phone has none, so it refuses.
 */
class ReviewRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = Overrides::read) :
    CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val asked = Asked.of(args)
        val lines = parts.database.writeBlocking { db -> db.savepoint("review") { answer(db, asked) } }
        for (line in lines) context.say(line)
    }

    /** One song's answer, as `caracole review` takes it: its lines. */
    private fun answer(db: Db, asked: Asked): List<String> {
        val display = asked.song
        val overrides = overrides(db)
        val song = songNamed(db, display)
        val searched = asked.pick != null && searched(song, overrides)
        if (song.status == "ignored" || song.key in overrides.ignore || !(song.review || searched)) {
            throw CommandExit(1, "\"${song.display}\" doesn't need review, so nothing was written.")
        }
        val cands = if (searched) Review.searchCandidates(db, song, overrides.reject[song.key].orEmpty())
                    else Review.candidatesOf(song)
        val again = "caracole review --song \"${song.display}\""
        val changed = linkedSetOf(song.id)
        val lines = ArrayList<String>()
        var accepted = 0
        var rejected = 0
        try {
            val pick = asked.pick
            if (pick != null) {
                val wanted = Py.strip(pick)
                val chosen = picked(cands, wanted)
                    ?: throw CommandExit(1, "\"${song.display}\" has no candidate $wanted now: $again lists them.")
                Review.accept(db, song, chosen)
                accepted++
                val alias = if (Review.writesAlias(song, chosen)) {
                    ", and [alias] \"${song.artist}\" = \"${chosen.artistKey}\""
                } else ""
                if (alias.isNotEmpty()) {
                    val artist = Normalize.slugKey(song.artist)
                    Songs.list(db).filter { s -> s.artists.ifEmpty { listOf(s.artist) }.any { Normalize.slugKey(it) == artist } }
                        .mapTo(changed) { it.id }
                }
                lines += "${song.display}: \"${Review.ref(chosen)}\" under [match]$alias"
            } else {
                val shown = asked.seen.ifEmpty { cands }
                if (shown.isEmpty()) {
                    throw CommandExit(1, "\"${song.display}\" has no candidates to reject: $again offers the rest.")
                }
                Review.reject(db, song, shown)
                rejected++
                lines += "${song.display}: ${shown.joinToString(", ") { Review.ref(it) }} under [reject]"
            }
        } catch (e: OverridesError) {  // what the phone holds can't take it
            throw CommandExit(2, "overrides: ${e.message}")
        }
        // _rewrite_pages: the songs the answer can change matched again, with the overrides as they are now
        val now = overrides(db)
        Matcher.matchAll(db, now, parts.config().match, Songs.list(db).filter { it.id in changed }, now = Stamps.now())
        lines += "accepted $accepted, pinned 0, ignored 0, rejected $rejected, skipped 0"
        lines += standing(Songs.byId(db, song.id) ?: song)
        return lines
    }

    /** `_common.load_ovr`: the phone's overrides, or the command refused (exit 2). */
    private fun overrides(db: Db): Overrides = try {
        readOverrides(db)
    } catch (e: OverridesError) {
        throw CommandExit(2, "overrides: ${e.message}")
    }

    /** commands/library.py's `_song_named`: the song "Artist - Title" names; a name of another shape exits 2, a song
     * not in the library 1. */
    private fun songNamed(db: Db, display: String): SongRow {
        val key = try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, "--song: ${e.message}")
        }
        parts.store.ensureCurrentKeys(db)
        return Songs.byKey(db, key) ?: throw CommandExit(1, "No song \"$display\" in the library.")
    }

    /** `_searched`: whether `--pick` takes one of the song's search hits: a song not found, and not ignored. */
    private fun searched(song: SongRow, overrides: Overrides): Boolean =
        !song.review && song.matchDecision == "not_found" && song.status != "ignored" && song.key !in overrides.ignore

    /** `_picked`: the candidate `--pick` names, by its number in the list (str.isdigit, as int() reads it), or by its
     * ARTIST/SONG. */
    private fun picked(cands: List<MatchCandidate>, pick: String): MatchCandidate? {
        if (pick.isNotEmpty() && pick.codePoints().allMatch { PyUnicode.isDigit(it) }) {
            val n = PyInt.parse(pick) ?: return null
            return if (n >= java.math.BigInteger.ONE && n <= cands.size.toBigInteger()) cands[n.toInt() - 1] else null
        }
        return cands.firstOrNull { Review.ref(it) == pick }
    }

    /** `_now`: where the song stands after the rematch. */
    private fun standing(song: SongRow): String {
        val artist = song.matchArtistKey
        val title = song.matchSongKey
        return when {
            song.matchDecision in setOf("accept", "pinned") && !artist.isNullOrEmpty() && !title.isNullOrEmpty() ->
                "Now matched to $artist/$title: caracole fetch --song \"${song.display}\" fetches it now, or the " +
                    "nightly run does."
            song.matchDecision == "review" ->
                "Still in review, with other candidates: caracole review --song \"${song.display}\" lists them."
            song.matchDecision == "not_found" ->
                "Not found now: caracole goes on looking for it, on its artist's UG page too."
            else -> "Now ${song.matchDecision.takeUnless { it.isNullOrEmpty() } ?: "not matched yet"}."
        }
    }

    /**
     * `caracole review`'s command line, as typer reads it: `--song`, `--pick` and each `--seen` (`--name=value` or
     * `--name value`), `--none`; checked as review_cmd checks it, in its order (exit 2).
     */
    internal class Asked(val song: String, val pick: String?, val seen: List<MatchCandidate>) {
        companion object {
            private val VALUED = setOf("--song", "--pick", "--seen")

            fun of(args: List<String>): Asked {
                var song: String? = null
                var pick: String? = null
                var none = false
                val seen = ArrayList<String>()
                var i = 1  // after `review`
                while (i < args.size) {
                    val arg = args[i]
                    val (name, given) = if (arg.startsWith("--") && '=' in arg) arg.substringBefore('=') to arg.substringAfter('=')
                                        else arg to null
                    val value = when {
                        name !in VALUED -> null
                        given != null -> given
                        else -> args.getOrNull(++i) ?: throw CommandExit(2, "Option '$name' requires an argument.")
                    }
                    when (name) {
                        "--song" -> song = value
                        "--pick" -> pick = value
                        "--seen" -> seen += value!!
                        "--none" -> if (given == null) none = true else throw CommandExit(2, "Option '--none' does not take a value.")
                        else -> throw CommandExit(2, if (arg.startsWith("-")) "No such option: $name"
                                                     else "Got unexpected extra argument ($arg)")
                    }
                    i++
                }
                if ((pick != null || none) && song == null) {
                    throw CommandExit(2, "--pick and --none answer for one song: name it with --song")
                }
                if (pick != null && none) throw CommandExit(2, "--pick or --none, not both")
                if (seen.isNotEmpty() && !none) throw CommandExit(2, "--seen goes with --none")
                val shown = seen.map(::seenCandidate)
                if (song == null || (pick == null && !none)) {
                    throw CommandExit(2, "caracole review asks its questions in a terminal: on the phone, answer with " +
                                         "--song and --pick or --none")
                }
                return Asked(song, pick, shown)
            }

            /** `_seen_candidate`: a `--seen` UG song, as a candidate; one that isn't ARTIST/SONG exits 2. */
            private fun seenCandidate(text: String): MatchCandidate {
                val stripped = Py.strip(text)
                val slash = stripped.indexOf('/')
                val artist = if (slash >= 0) stripped.substring(0, slash) else stripped
                val song = if (slash >= 0) stripped.substring(slash + 1) else ""
                if (slash < 0 || artist.isEmpty() || song.isEmpty() || '/' in song) {
                    throw CommandExit(2, "--seen: ${PyStr.repr(text)} isn't a UG song: write it as ARTIST/SONG, as " +
                                         "caracole review lists it")
                }
                return MatchCandidate(artist, song, null, null)
            }
        }
    }
}

/**
 * review.py's rules on the phone, for the review runner and the picker (ReviewRoutes): the candidates a review lists
 * ([candidatesOf]), a song not found's search hits ([searchCandidates]), the UG song a candidate is ([ref]), whether a
 * pick writes an `[alias]` ([writesAlias]), the two answers ([accept], [reject]), and the picker's choices
 * ([choices]: library_page.review_choices). vectors/web/review.jsonl holds each to Python's (ReviewReplay).
 */
object Review {
    /** review.SHOWN: the candidates a review lists, numbered 1 to 9. */
    const val SHOWN = 9

    /** review.SEARCH: the step of a candidate caracole search found, for a song not found. */
    const val SEARCH = "search"

    /** review.SEARCHED: the search hits offered as a song not found's candidates. */
    const val SEARCHED = 5

    /** review.candidates_of: the song's stored candidates that name a UG song, best first, nine at most. */
    fun candidatesOf(song: SongRow): List<MatchCandidate> = Matcher.candidatesOf(song).take(SHOWN)

    /** review.ref: a candidate as overrides.toml names a UG song, "artist-key/song-key". */
    fun ref(cand: MatchCandidate): String = "${cand.artistKey}/${cand.songKey}"

    /**
     * review.search_candidates: for a song not found (and not ignored), what `caracole search` finds for its artist and
     * title in the offline index, best first, as candidates of step [SEARCH], the UG songs [rejected] for it (its
     * `[reject]` entry) left out, [limit] at most; none for any other song.
     */
    fun searchCandidates(db: Db, song: SongRow, rejected: Set<Pair<String, String>> = emptySet(),
                         limit: Int = SEARCHED): List<MatchCandidate> {
        if (song.matchDecision != "not_found" || song.status == "ignored") return emptyList()
        val hits = Search.searchIndex(db, "${song.artist} ${Normalize.cleanTitle(song.title)}", limit + rejected.size)
        return hits.filter { (it.artistKey to it.songKey) !in rejected }
            .map { MatchCandidate(it.artistKey, it.songKey, it.score, SEARCH) }.take(maxOf(limit, 0))
    }

    /** review.writes_alias: whether accepting the candidate adds an `[alias]` too: when the artist's name differs, but
     * never for a title-only match, a catch-all's (match.NO_ALIAS_STEPS) nor a search hit. */
    fun writesAlias(song: SongRow, cand: MatchCandidate): Boolean =
        cand.step !in Match.NO_ALIAS_STEPS + SEARCH && Normalize.slugKey(song.artist) != cand.artistKey

    /** review.accept: `[match]`, and `[alias]` when [writesAlias]; the review is settled. */
    fun accept(db: Db, song: SongRow, cand: MatchCandidate) {
        OverrideWriters.addMatch(db, song.display, ref(cand))
        if (writesAlias(song, cand)) OverrideWriters.addAlias(db, song.artist, cand.artistKey)
        Versions.updateSong(db, song.id, mapOf("review" to false))
    }

    /** review.reject: every candidate shown under `[reject]`; the song is still looked for. */
    fun reject(db: Db, song: SongRow, cands: List<MatchCandidate>) {
        OverrideWriters.addReject(db, song.display, cands.map(::ref))
        Versions.updateSong(db, song.id, mapOf("review" to false))
    }

    // --- waiting on library-cards: its Choices (server/page/internal/cards/Choices.kt) is the one port of
    // review_choices and step_words; until it merges, these stand in for it, and go once it has ---------------------

    /** review._STEP_WORDS: why the matcher thought of a candidate, by the step that found it. */
    private val STEP_WORDS = mapOf(
        SEARCH to "a caracole search hit for its artist and title",
        "exact" to "same artist and title",
        "alias" to "under the artist's [alias]",
        "fuzzy_title" to "title spelled differently",
        "fuzzy_artist" to "artist spelled differently",
        "word_title" to "a title of the artist's with words more or fewer",
        "typo_artist" to "artist a letter or two off",
        "title_only" to "title only: another artist's song, probably a cover",
        "override" to "your [match] in overrides.toml",
        "pin" to "pinned in overrides.toml",
        "artist_page" to "on the artist's UG page",
    )

    /** library_page._TAB_KINDS. */
    private val TAB_KINDS = mapOf("chords" to "Chords", "tabs" to "Tabs", "ukulele" to "Ukulele Chords")

    /** review.step_words: why the matcher thought of a candidate, in plain words; an unknown step as it is. */
    fun stepWords(cand: MatchCandidate): String {
        val step = cand.step ?: ""
        if (step == "catch_all") {
            val performer = if (cand.artistKey in Match.PERFORMER_CATCH_ALLS) ", the performer's name first" else ""
            return "under UG's catch-all ${cand.artistKey}$performer"
        }
        return STEP_WORDS[step] ?: step
    }

    /** library_page.review_choices: each candidate ([cands], else the song's own) as the picker shows it, numbered:
     * its ref, its artist and title as UG writes them (named from its keys when the index no longer has it, with no
     * tabs and no page), its score rounded, why, its tabs per type and its UG page. */
    fun choices(db: Db, song: SongRow, cands: List<MatchCandidate>? = null): List<JsonObject> =
        (cands ?: candidatesOf(song)).mapIndexed { i, cand ->
            val hit = Search.indexSong(db, cand.artistKey, cand.songKey)
            val (artist, title) = if (hit != null) hit.artist to hit.title
                                  else Search.displayFromKeys(cand.artistKey, cand.songKey)
            JsonObject(linkedMapOf(
                "n" to JsonPrimitive(i + 1),
                "ref" to JsonPrimitive(ref(cand)),
                "artist" to JsonPrimitive(artist),
                "title" to JsonPrimitive(title),
                "score" to JsonPrimitive(Math.rint(cand.score ?: 0.0).toLong()),
                "why" to JsonPrimitive(stepWords(cand)),
                "tabs" to JsonPrimitive(hit?.counts?.entries?.joinToString(" · ") { (kind, n) ->
                    "${TAB_KINDS[kind] ?: kind} ×$n"
                } ?: ""),
                "href" to JsonPrimitive(hit?.url ?: ""),
            ))
        }
}
