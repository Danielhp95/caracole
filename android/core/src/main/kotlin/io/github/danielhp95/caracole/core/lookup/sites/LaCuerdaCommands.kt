package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearch
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearchAnswer
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.py.PyInt
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * `caracole lacuerda --artist` and `--search` on the phone (commands/lyrics.py's `_lacuerda_artist` and
 * `_lacuerda_search`), each through the command's asking (the lookup pace and budget; a block cooling LaCuerda down
 * and an error counted, by the asking, never here), each returning its last line, which its runner (lane lookup's
 * LaCuerdaRunner) says, its name or query with its whitespace folded as lacuerda_cmd folds it:
 *
 * - [artist]: one artist's page into LaCuerda's index now ([LaCuerdaSheets.readArtistPage]): "Read: " (the page, in the
 *   index now), "Not found: " (no artist page by that name or slug) or "Not read: " (a cooldown, a block, a spent
 *   budget or an error: nothing changed).
 * - [search]: LaCuerda's own search for a query, one request ([LaCuerdaSearch.search], a policy of one request), its
 *   one stage's `--progress` events said as the lines `caracole lacuerda --search --progress` prints (get.py's
 *   `caracole-progress: ` JSON, stage "search", running "asking LaCuerda", then its end with the last line as its
 *   detail): "Searched: " (its songs, in the index now, or asked within 30 days), "Found already: " (your library or
 *   the index answers it well: no request), "Nothing found: " (no song) or "Not searched: " (no word LaCuerda reads,
 *   a cooldown, a block, a spent share or budget, an error, which is remembered for an hour, or with [auto] a search
 *   that failed lately or the hour's searches the page sends by itself spent).
 *
 * A good run is recorded where Python records it (Health.recordOk after Health.answeredAny of the command's run,
 * LookupWords.lookupRunOf's: the lookup's, `lookup:<now>`, or the search's own, `lookup:lacuerda-search:<now>`, under
 * which LaCuerdaSearch.searchesUsed counts the hour's searches the page sends by itself). So the runner's asking logs
 * its events under that run at the same [CommandContext.now], as LaCuerdaRunner's InteractiveAsk does.
 * The computer's search first stores the artist pages its HTTP cache holds that its index lacks (backfill_cached);
 * the phone stores each page it reads as it reads it, so it has none to store. vectors/lookup/commands_lacuerda.jsonl
 * holds both to Python's (tests/test_conformance_lacuerda_lookups.py, LaCuerdaReplay).
 */
object LaCuerdaCommands {
    const val PROVIDER = LaCuerdaSheets.PROVIDER
    const val NOT_READ = "Not read: "
    const val NOT_SEARCHED = "Not searched: "
    private const val NAME = "LaCuerda"
    private const val STAGE = "search"
    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    /** `caracole lacuerda --artist NAME`: [artist]'s page read now, under [first] first (none: their name when it is
     * written as a slug); its last line. */
    fun artist(c: CommandContext, artist: String, first: String?): String {
        val db = c.db
        val now = c.now
        if (Health.isCooling(db, PROVIDER, now)) return NOT_READ + cooling(Health.state(db, PROVIDER).cooldownUntil)
        val asked = c.asking.ask(PROVIDER) { client -> LaCuerdaSheets.readArtistPage(db, client, artist, now, first) }
        val found = when (asked) {
            is Asked.Done -> asked.value
            is Asked.Cooling -> return NOT_READ + cooling(asked.until)
            is Asked.Off -> return NOT_READ + "${asked.why}; nothing changed."
            is Asked.Blocked -> return NOT_READ + blocked(asked)
            is Asked.Spent -> {
                val p = PhoneConfig.read(db).provider(PROVIDER)
                val spent = if (asked.hour) "this hour's ${p.lookupPerHour} lookup requests to $NAME are spent"
                            else "the lookup's ${p.lookupRequests} requests to $NAME are spent"
                return "$NOT_READ$spent; ask again later."
            }
            is Asked.Failed -> return "${NOT_READ}$NAME failed (${asked.error.message}); nothing changed: try again later."
        }
        recordOk(c, LookupWords.lookupRunOf(now))
        if (found == null) return "Not found: $NAME has no artist page for $artist."
        val (slug, songs) = found
        val name = db.one("SELECT artist FROM lacuerda_index WHERE artist_slug = ? LIMIT 1", slug) { it.text(0) } ?: artist
        return "Read: $NAME's page of $name lists ${plural(songs, "song")}, in the index now."
    }

    /** `caracole lacuerda --search QUERY` (with `--auto`: a search the page sent by itself); its last line, and with
     * [progress] (`--progress`, as caracole serve and LaCuerdaRunner always run it) its stage's events said before
     * it. */
    fun search(c: CommandContext, query: String, auto: Boolean, progress: Boolean = true): String {
        val db = c.db
        val shownQuery = "“$query”"
        fun say(state: String, detail: String) {
            if (progress) c.say(progressLine(state, detail))
        }
        fun end(line: String, state: String = "skipped"): String {
            say(state, line)
            return line
        }
        val key = LaCuerdaSearch.queryKey(query)
        if (key.isEmpty()) {
            return end("${NOT_SEARCHED}LaCuerda's search reads only words of 4 letters or more, and $shownQuery has none.")
        }
        say("running", "asking LaCuerda")
        val now = c.now
        LaCuerdaSearch.asked(db, key, now)?.let { was ->
            val at = Stamps.parse(was["at"])?.let { shown(Stamps.instant(it)) } ?: "?"
            return end("Searched: $NAME was asked for $shownQuery on $at: ${plural(count(was["songs"]), "song")}, in " +
                           "the index.", "done")
        }
        Rekey.ensure(db, Stamps.of(now))  // songs.ensure_current_keys, which search_library's list_songs runs first
        if (LaCuerdaSearch.answered(db, query)) {  // what the page's gate saw may be older than the index now
            return end("Found already: caracole has $shownQuery already, in your library or its copy of LaCuerda's " +
                           "index; no request sent.", "done")
        }
        val config = PhoneConfig.read(db)
        val p = config.provider(PROVIDER)
        if (Health.isCooling(db, PROVIDER, now)) {
            return end(NOT_SEARCHED + cooling(Health.state(db, PROVIDER).cooldownUntil))
        }
        val policy = Pace.lookupPolicy(config, db, PROVIDER, now)
        if (policy.budget < 1) {
            return end("${NOT_SEARCHED}this hour's ${p.lookupPerHour} lookup requests to $NAME are spent; ask again later.")
        }
        if (auto) {
            LaCuerdaSearch.failed(db, key, now)?.let { failure ->
                return end("$NOT_SEARCHED${failure.said(shownQuery)}; its Ask LaCuerda button, Try again or a terminal " +
                               "asks now.")
            }
            if (LaCuerdaSearch.searchesUsed(db, now) >= LaCuerdaSearch.SEARCHES_PER_HOUR) {
                return end("${NOT_SEARCHED}this hour's ${LaCuerdaSearch.SEARCHES_PER_HOUR} searches of LaCuerda the page " +
                               "sends by itself are spent; its Ask LaCuerda button, or a terminal, asks anyway.")
            }
        }
        val asked = c.asking.ask(PROVIDER, policy.copy(budget = 1)) { client ->
            LaCuerdaSearch.search(db, client, query, now)
        }
        val answer: LaCuerdaSearchAnswer = when (asked) {
            is Asked.Done -> asked.value
            is Asked.Cooling -> return end(NOT_SEARCHED + cooling(asked.until))
            is Asked.Off -> return end("$NOT_SEARCHED${asked.why}; nothing changed.")
            is Asked.Blocked -> return end(NOT_SEARCHED + blocked(asked))
            is Asked.Spent -> return end("${NOT_SEARCHED}the search's one request to $NAME is spent; ask again later.")
            is Asked.Failed -> {
                // Not sent by the page by itself for an hour.
                LaCuerdaSearch.recordFailure(db, key, now, "$NAME failed: ${asked.error.message}")
                return end("${NOT_SEARCHED}$NAME failed (${asked.error.message}); nothing changed: try again later.")
            }
        }
        recordOk(c, LookupWords.searchRunId(now))
        return when {
            answer.songs.isNotEmpty() -> {
                val some = if (answer.stated > BigInteger.valueOf(answer.songs.size.toLong())) {
                    "${plural(answer.stated, "song")} for $shownQuery: the first ${answer.songs.size} are"
                } else {
                    "${plural(answer.songs.size.toLong(), "song")} for $shownQuery,"
                }
                end("Searched: $NAME has $some in the index now.", "done")
            }
            answer.artists.isNotEmpty() ->
                end("Searched: $NAME names ${plural(answer.artists.size.toLong(), "artist")} for $shownQuery, in the " +
                        "index now.", "done")
            else -> end("Nothing found: $NAME has no song for $shownQuery.", "done")
        }
    }

    /** record_ok once the command's run [runId] got an answer (health.answered_any of the requests it sent). */
    private fun recordOk(c: CommandContext, runId: String) {
        val sent = c.asking.requests[PROVIDER] ?: 0
        if (Health.answeredAny(c.db, runId, PROVIDER, sent)) Health.recordOk(c.db, PROVIDER, c.now)
    }

    private fun cooling(until: Instant?): String =
        "$NAME is cooling down after a block until ${shown(until)}; caracole won't ask it before then."

    private fun blocked(asked: Asked.Blocked): String =
        "$NAME blocked caracole (${asked.error.message}); no more requests to it until " +
            "${shown(asked.state.cooldownUntil)}."

    /** get.progress_line of the search's stage. */
    private fun progressLine(state: String, detail: String): String = LookupWords.progressLine(
        JsonObject(linkedMapOf("stage" to JsonPrimitive(STAGE), "state" to JsonPrimitive(state),
                               "detail" to JsonPrimitive(detail))))

    /** stamps.shown: a time in UTC, "2026-11-03 12:30 UTC"; "?" for none. */
    private fun shown(at: Instant?): String = at?.let(WHEN::format) ?: "?"

    /** logs.plural: "1 song", "2 songs", a count of any size (LaCuerda's search may state one past a Long). */
    private fun plural(n: BigInteger, noun: String): String = "$n ${if (n == BigInteger.ONE) noun else noun + "s"}"

    private fun plural(n: Long, noun: String): String = plural(BigInteger.valueOf(n), noun)

    private fun plural(n: Int, noun: String): String = plural(n.toLong(), noun)

    /** `int(was.get('songs') or 0)`: a number's whole part, a text's integer, 0 for none. */
    private fun count(value: JsonElement?): Long {
        if (value == null || value is JsonNull || value !is JsonPrimitive) return 0
        if (value.isString) return PyInt.parse(value.content)?.toLong() ?: 0
        return when (value.content) {
            "true" -> 1
            "false" -> 0
            else -> PyInt.parse(value.content)?.toLong() ?: value.content.toDoubleOrNull()?.toLong() ?: 0
        }
    }
}
