package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.py.PyFormat
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant

/**
 * get.py's words on the phone, verbatim: its stages and their labels, its sites' names, and how a stage says what
 * asking a site came to (`_Lookup._usable` and `asking`), what follows the sheet kept within [SHEETS_SHARE]
 * (`after_the_sheet`), the lyrics' sites put together (`_then`), the frame's own ends (the pdf, lacuerda and songbooks
 * stages'), and the lines `caracole get` prints ([LookupLines], [totals]). get.py's words of a caracole with no PDFs,
 * no wanted.txt and no index.html to write ([ADDED], [NO_PDFS], [PAGES_MADE], [LIBRARY_PAGE]) are get.py's too, used
 * on the computer by nothing but the corpus.
 *
 * A site's stage (core/lookup/sites/) words its site's answer itself, as get.py's work does, and every other end of an
 * [Asked] through [end]. tests/conformance/vectors/lookup/ holds them to Python's (tests/test_conformance_lookup.py).
 */
object LookupWords {
    /** get.STAGES: a lookup's stages, in order, with their labels. */
    val STAGES: List<Pair<String, String>> = listOf(
        "song" to "Find the song",
        "match" to "Match it against the offline index",
        "sheet" to "The sheet",
        "pdf" to "The PDF",
        "lyrics" to "Lyrics from LRCLIB",
        "ug" to "Ultimate Guitar: the sheets scored, the tab",
        "lacuerda" to "LaCuerda",
        "gtptabs" to "A Guitar Pro file from gtptabs.com",
        "harptabs" to "A harmonica tab from harptabs.com",
        "gametabs" to "A tab of game music from gametabs.net",
        "pages" to "The library page",
        "songbooks" to "The songbooks it is in",
    )

    /** get.NAMES: each site's name in words. */
    val NAMES: Map<String, String> = linkedMapOf(
        "ug" to "Ultimate Guitar", "lrclib" to "LRCLIB", "megalobiz" to "Megalobiz", "azlyrics" to "AZLyrics",
        "lacuerda" to "LaCuerda", "gtptabs" to "gtptabs.com", "musescore" to "MuseScore", "harptabs" to "harptabs.com",
        "gametabs" to "gametabs.net",
    )

    /** get.SHEETS_SHARE: of an hour's lookup requests to a site, the share kept for sheets. */
    const val SHEETS_SHARE = 0.5

    /** get.SHEET_FROM: a running sheet stage's detail once it asks a site, which the Requests tab's line reads. */
    val SHEET_FROM: Map<String, String> = linkedMapOf("lacuerda" to "from LaCuerda", "ug" to "from Ultimate Guitar")

    /** get.MATCH_NOT_FOUND: how the match stage begins for a song the offline index lacks. */
    const val MATCH_NOT_FOUND = "not in the offline Ultimate Guitar index"
    const val GTPTABS_KEPT = "Guitar Pro file downloaded"
    const val HARPTABS_KEPT = "harmonica tab kept"
    const val GAMETABS_KEPT = "game music tab kept"

    /** get.NOT_IN_INDEX: the sheet stage's detail for a song Ultimate Guitar can't be asked about. */
    const val NOT_IN_INDEX = "the offline index doesn't have it, and its artist's UG page isn't known"

    /** get.ADDED: the song stage's detail for a song new to the phone (the computer's says its wanted.txt line). */
    const val ADDED = "added to the library"

    /** get.NO_PDFS: the pdf stage's detail, skipped, while the phone makes no page of the song (SongPages.NONE). */
    const val NO_PDFS = "this caracole makes no PDF"

    /** get.PAGES_MADE: the pdf stage's detail once the phone has made the song's pages. */
    const val PAGES_MADE = "its pages made; this caracole makes no PDF"

    /** get.LIBRARY_PAGE: the pages stage's detail on the phone, whose library page is made as it is asked for. */
    const val LIBRARY_PAGE = "the library page shows it as it is now"

    /** The pdf stage's detail for a song with no sheet yet. */
    const val NO_SHEET_YET = "no sheet yet"

    /** What the pdf stage's pages came to when none was written, as render's "up to date". */
    const val UP_TO_DATE = "up to date"

    /** What a site's stage answers when there was nothing to ask its site (get.py's None, the Megalobiz and AZLyrics
     * stages' alone): the lyrics stage then says what the sites before it said. */
    val NOTHING_TO_ASK: StageEnd = StageEnd("nothing", "")

    /** A site's name in words, or the provider's own for one of no name (`NAMES.get(p, p)`). */
    fun name(provider: String): String = NAMES[provider] ?: provider

    // --- the envelope (get.py's `_usable` and `asking`) -----------------------------------------------------------

    /** `_usable`: a provider turned off. */
    fun off(provider: String): String = "${name(provider)} is off in caracole.toml"

    /** `_usable`: a provider that blocked caracole earlier in this lookup. */
    fun blockedEarlier(provider: String): String =
        "${name(provider)} blocked caracole: it cools down, and the nightly run asks again later"

    /** `_usable`: a provider that failed earlier in this lookup. */
    fun failedEarlier(provider: String): String =
        "${name(provider)} failed earlier in this lookup; the nightly run tries again"

    /** A cooldown's end as get.py says it, `strftime("%Y-%m-%d %H:%M UTC")`, or "later" for none. */
    fun until(at: Instant?): String {
        if (at == null) return "later"
        val stamp = Stamps.of(at)  // 2026-11-04T14:00:00Z
        return stamp.substring(0, 10) + " " + stamp.substring(11, 16) + " UTC"
    }

    /** `_usable`: a provider cooling down after a block. */
    fun cooling(provider: String, until: Instant?): String =
        "${name(provider)} is cooling down after a block, until ${until(until)}"

    /** `asking`: a block met just now, and the cooldown it began. */
    fun blocked(error: ProviderError, until: Instant?): String =
        "${name(error.provider)} blocked caracole (${error.message}): no more requests to it until ${until(until)}. " +
            "Nothing was marked not found."

    /** `_kept_for_sheets`: what follows the sheet held to what leaves [SHEETS_SHARE] (a half) for sheets. */
    fun keptForSheets(provider: String, policy: ProviderPolicy): String =
        "this hour's lookups have spent half of their ${policy.lookupPerHour} requests to ${name(provider)}, and " +
            "the other half is kept for sheets"

    /** `asking`'s BudgetExhausted: kept for sheets, the hour's lookups spent, or the lookup's own. */
    fun spent(provider: String, policy: ProviderPolicy, hour: Boolean, keptForSheets: Boolean): String {
        val spent = when {
            keptForSheets -> keptForSheets(provider, policy)
            hour -> "this hour's ${policy.lookupPerHour} lookup requests to ${name(provider)} are spent"
            else -> "the lookup's ${policy.lookupRequests} requests to ${name(provider)} are spent"
        }
        return "$spent; the nightly run does the rest"
    }

    /** `asking`'s ProviderError: the site's part ends for this lookup. */
    fun failed(error: ProviderError): String =
        "${name(error.provider)} failed (${error.message}); the nightly run tries again"

    /** report.shared_folder: a file that would go where another song keeps one. */
    fun sharedFolder(error: SharedFolder): String =
        "${error.message}. Nothing is written over it, and the song waits until the folder is its own: remove one of " +
            "the two (caracole remove), and ask for it again under a shorter title."

    /**
     * A stage's end for what asking [provider] came to: [done] of the work's value, else get.py's words for the rest
     * (a site off, blocked or failed earlier, cooling, blocked now, spent, failing), [config] the phone's settings
     * (its lookup counts).
     */
    fun <T> end(config: PhoneConfig, provider: String, asked: Asked<T>, done: (T) -> StageEnd): StageEnd = when (asked) {
        is Asked.Done -> done(asked.value)
        is Asked.Off -> StageEnd("skipped", asked.why)
        is Asked.Cooling -> StageEnd("skipped", cooling(provider, asked.until))
        is Asked.Blocked -> StageEnd("skipped", blocked(asked.error, asked.state.cooldownUntil))
        is Asked.Spent -> StageEnd("skipped", spent(provider, config.provider(provider), asked.hour, asked.keptForSheets))
        is Asked.Failed -> StageEnd("failed", failed(asked.error))
    }

    /** [end] for work that words its own end. */
    fun end(config: PhoneConfig, provider: String, asked: Asked<StageEnd>): StageEnd = end(config, provider, asked) { it }

    // --- the frame's ends ---------------------------------------------------------------------------------------

    /**
     * `_then`: the lyrics stage's end once one more site was asked after those before it ([then] null, or
     * [NOTHING_TO_ASK]: there was nothing to ask it), [hasLyrics] whether the song has lyrics by then. A site that
     * answered is one whose end is `done` (get.py's text).
     */
    fun then(out: StageEnd, then: StageEnd?, hasLyrics: Boolean): StageEnd {
        if (then == null || then == NOTHING_TO_ASK) return out
        val answered = out.state == "done"
        val thenAnswered = then.state == "done"
        if (answered && (thenAnswered || hasLyrics)) return StageEnd("done", "${out.detail}; ${then.detail}")
        if (answered) return then
        return if (thenAnswered && hasLyrics) StageEnd("done", then.detail) else out
    }

    /** The lacuerda stage's end when LaCuerda was asked already, for the sheet: what that came to, said again. */
    fun lacuerdaAgain(said: StageEnd): StageEnd {
        val again = "asked already, for the sheet" + if (said.detail.isNotEmpty()) ": ${said.detail}" else ""
        return StageEnd(if (said.state == "done") "skipped" else said.state, again)
    }

    /** The songbooks stage's detail when songbooks.toml can't be read. */
    fun songbooksUnread(error: String?): String =
        "songbooks.toml can't be read (${error.orEmpty()}); no songbook was made again"

    /** The songbooks stage's detail for a lookup that leaves them (`--no-songbooks`). */
    const val SONGBOOKS_LEFT = "left to the job that makes the songbook after the lookups"

    /** The songbooks stage's detail for a song no songbook lists. */
    const val NO_SONGBOOK = "no songbook lists it"

    /** The songbooks stage's end once the songbooks [names] (", "-joined) list were made again as [stats] says. */
    fun songbooksEnd(names: String, stats: SongbookStats): StageEnd = when {
        stats.failed.isNotEmpty() ->
            StageEnd("failed", "a file of ${stats.failed.joinToString(", ")} couldn't be made; the nightly run tries again")
        stats.fontError != null -> StageEnd("skipped", stats.fontError)
        else -> StageEnd("done", if (stats.rendered > 0) "$names made again" else "$names up to date")
    }

    // --- a lookup command's lines and records ----------------------------------------------------------------------
    //
    // A lookup command on the phone (core/lookup/sites/'s VersionsCommands, LaCuerdaCommands, HarpTabsCommands), run
    // by its runner of server/lookups in a CommandContext:
    // - says its Python's `--progress` events as [progressLine]s ([stageLine], [songLine]) and its other lines as
    //   they are, through `CommandContext.say`, and returns its last line, which the runner says; the runner makes
    //   each event its job's (or, for a command line without `--progress`, a line of its output, as caracole serve
    //   keeps one);
    // - asks every site through `CommandContext.asking`, the envelope (InteractiveAsk), which records a block
    //   (Health.recordBlock, its cooldown in Asked.Blocked, Alerts.blocked once) and an error (Health.recordError):
    //   a command never records either itself, and words them from the Asked it gets;
    // - records its own good run where its Python does: Health.recordOk(c.db, provider, c.now), after
    //   Health.answeredAny of its run, [lookupRunOf] (`lookup:` and `c.now`, or [searchRunId] for LaCuerda's
    //   search), where its Python reads answered_any, or when `c.asking.requests[provider]` is more than none where
    //   its Python counts requests (versions_cmd.py's keep);
    // - `versions --keep` and `--keep-more`: the runner begins the song stage and finds the song; the command says
    //   from `{"song": …}` on, and versions_cmd.py's `pdf` and `pages` running events where it makes the song's
    //   pages, which the runner makes then and ends in the phone's words (its own ends of those two are not said).

    /** get.PROGRESS_PREFIX: what begins a line of `caracole get --progress` (and the other commands' `--progress`). */
    const val PROGRESS_PREFIX = "caracole-progress: "

    /** get.progress_line: a progress event as the line a command with `--progress` prints, `json.dumps(event,
     * ensure_ascii=False, separators=(",", ":"))` after [PROGRESS_PREFIX]. */
    fun progressLine(event: JsonObject): String = PROGRESS_PREFIX + PyJson.dumps(event, compact = true)

    /** lacuerda_search.RUN: after `lookup:`, how a search of LaCuerda's is named in events. */
    const val LACUERDA_SEARCH_RUN = "lacuerda-search:"

    /** A LaCuerda search's run at [now], `lookup:lacuerda-search:` and the time (commands/lyrics.py's), whose
     * requests count in the hour's searches. */
    fun searchRunId(now: Instant): String = Pace.LOOKUP_RUN + LACUERDA_SEARCH_RUN + Stamps.of(now)

    /** A lookup command's run at [now]: `_common.lookup_run_id`, or [searchRunId] for LaCuerda's search. */
    fun lookupRunOf(now: Instant, search: Boolean = false): String = if (search) searchRunId(now) else Pace.lookupRunId(now)

    /** [progressLine] of a stage's event, `{"stage": name, "state": state, "detail": detail}`. */
    fun stageLine(name: String, state: String, detail: String = ""): String =
        progressLine(JsonObject(linkedMapOf("stage" to JsonPrimitive(name), "state" to JsonPrimitive(state),
                                            "detail" to JsonPrimitive(detail))))

    /** [progressLine] of the song a command is about, `{"song": {"id": id, "display": display}}`. */
    fun songLine(id: Long, display: String): String =
        progressLine(JsonObject(mapOf("song" to JsonObject(linkedMapOf("id" to JsonPrimitive(id),
                                                                        "display" to JsonPrimitive(display))))))

    // --- caracole get's lines (commands/get.py) -------------------------------------------------------------------

    /** commands/get.py's _SHORT: a stage's name in a line. */
    val SHORT: Map<String, String> = linkedMapOf(
        "song" to "Song", "match" to "Match", "sheet" to "Sheet", "pdf" to "PDF", "lyrics" to "Lyrics",
        "audio" to "Audio", "chords" to "Chords", "ug" to "Ultimate Guitar", "lacuerda" to "LaCuerda",
        "gtptabs" to "gtptabs.com", "harptabs" to "harptabs.com", "gametabs" to "gametabs.net", "pages" to "Pages",
        "songbooks" to "Songbooks",
    )

    /** commands/get.py's _totals: the lookup's last line. */
    fun totals(result: LookupResult): String {
        result.refused?.let { return "Nothing looked up: $it." }
        val sent = result.requests.filterValues { it != 0 }
        val total = sent.values.sum()
        var words = "$total request" + if (total == 1) "" else "s"
        if (sent.isNotEmpty()) words += " (" + sent.entries.joinToString(", ") { "${name(it.key)} ${it.value}" } + ")"
        return "Done in ${PyFormat.fixed(result.seconds, 1)} s: $words."
    }
}

/**
 * commands/get.py's _Lines: a lookup as the lines `caracole get` prints, one a stage, the sheet's path the moment it
 * is readable (said with the sheet stage's line, which waits for it), each said through [say]; [library] the library
 * folder the paths are under.
 */
class LookupLines(private val library: File, private val say: (String) -> Unit) {
    private var held: String? = null
    private var files: Map<String, String> = emptyMap()

    /** The sheet stage's line, held for its path, said now. */
    fun flush() {
        held?.let(say)
        held = null
    }

    /** A stage starts or ends. */
    fun stage(name: String, state: String, detail: String = "") {
        if (state == "running") {
            flush()
            return
        }
        var said = detail.ifEmpty { state }
        if (state != "done" && detail.isNotEmpty()) said = "$state: $detail"
        val line = "${LookupWords.SHORT[name] ?: name}: $said."
        if (name == "sheet" && state == "done") {
            held = line
            return
        }
        say(line)
    }

    /** The sheet can be read (the first time, or a page of it made, or a better one): its paths. */
    fun readable(files: Map<String, String>, seconds: Double) {
        val first = this.files.isEmpty()
        val sheet = File(library, files.getValue("sheet")).path
        if (first) {
            val said = (held ?: "Sheet").trimEnd('.')
            held = null
            say("$said: $sheet, readable after ${PyFormat.fixed(seconds, 1)} s.")
        } else {
            for ((name, label) in listOf("pdf" to "PDF", "viewer" to "Viewer")) {
                if (name in files && name !in this.files) say("$label: ${File(library, files.getValue(name)).path}")
            }
            if (files == this.files) say("Sheet: a better one replaced it, in $sheet.")
        }
        this.files = LinkedHashMap(files)
    }
}
