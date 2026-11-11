package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SheetVersion
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.UgFetch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * `caracole versions --keep` and `--keep-more` on the phone (versions_cmd.py's `keep` and `keep_more`), the song found
 * and its `song` stage begun by the runner (lane lookup's VersionsRunner), in the song's folder of [LibraryStore]:
 *
 * - [keep]: one of the song's UG chords versions kept beside its sheet now ([UgFetch.keepVersion]): one tab page at
 *   most, through the command's asking (the lookup pace and budget, a block cooling Ultimate Guitar down, an error
 *   counted), noted as yours. Refused ([KeepRefused], exit 1) for a version the song hasn't or UG no longer has, and
 *   one under `[block]`; the sheet already, or kept beside it already (then noted as yours), asks nothing.
 * - [keepMore]: [keep] for each version a keep may still keep ([SheetVersions.mayKeep]), in rank order, through one
 *   client, until the lookup's budget is spent or UG blocks caracole or fails; a version whose page has no sheet, or
 *   the very text of another kept file, noted so ([SheetVersions.noteUnkeepable]) and never read again.
 *
 * Each says versions_cmd.py's lines (`--progress`, as caracole serve queues them: get.py's `caracole-progress:` events
 * of its `song`, `version`, `pdf` and `pages` stages, and its output lines) through [CommandContext.say], and returns
 * its last line, which the runner says once it returns. The `pdf` and `pages` stages are where versions_cmd.py makes
 * the song's pages (`render_all` once a version is kept, `write_pages` for any answer past the refusals; none for a
 * keep-more stopped before anything changed): the runner makes them at their running events. No `Viewer:` line: the
 * phone's viewer is a page it serves, no file to name. A good run is recorded (Health.recordOk) only after a request,
 * as versions_cmd.py records it (vectors/lookup/commands_versions.jsonl, tests/test_conformance_ug_fetch.py).
 */
object VersionsCommands {
    const val PROVIDER = "ug"
    private const val NAME = "Ultimate Guitar"
    private const val PROGRESS = "caracole-progress: "
    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    /** A keep's refusal (versions_cmd.py's `fail`, exit 1): the version isn't one the song may keep, why in words. */
    class KeepRefused(message: String) : Exception(message)

    /** KEPT_WORDS: what [UgFetch.keepVersion] came to, in words. */
    val KEPT_WORDS: Map<String, String> = linkedMapOf(
        "same" to "its text is the very text of {page}, which shows it",
        "held" to "same text as another file in the song's folder; not kept twice",
        "sheet" to "it is the sheet already",
        "gone" to "gone from UG",
        "unreadable" to "couldn't read its page; it waits",
        "closed" to "UG moved its page behind robots.txt; nothing kept",
        "no text" to "its page has no sheet we can keep",
        "unknown" to "not one of the song's chords versions we may use",
    )

    /** `keep`: tab [tab] of [song] kept beside its sheet in [library]; its last line. */
    fun keep(c: CommandContext, library: LibraryStore, song: SongRow, tab: Long): String {
        val db = c.db
        val overrides = Overrides.read(db)
        val config = PhoneConfig.read(db)
        val v = listed(c, config, song, tab)
        if (tab in overrides.block) throw KeepRefused("Tab $tab is under [block] in overrides.toml: caracole never uses it.")
        begun(c, song)
        if (v.chosen) return said(c, "skipped", "Tab $tab is the sheet of ${song.display} already.")
        if (v.kept && v.page != SHEET_PAGE) {
            SheetVersions.noteKeptByYou(db, song.id, v.tabId)
            return said(c, "done", "Tab $tab is kept beside the sheet of ${song.display} already; it stays kept now.")
        }
        val asked = c.asking.ask(PROVIDER) { client ->
            UgFetch.keepVersion(FetchContext(db, client, overrides, config.rank, library, c.now), song, tab)
        }
        val outcome = when (asked) {
            is Asked.Done -> asked.value
            is Asked.Cooling -> return said(c, "skipped", cooling(asked.until))
            else -> {
                val (state, why, again) = stopped(config, asked)
                return said(c, state, nothingKept(why, again))
            }
        }
        if ((c.asking.requests[PROVIDER] ?: 0) > 0) Health.recordOk(db, PROVIDER, c.now)
        val line = cameTo(c, library, song, tab.toString(), outcome)
        stage(c, "version", if (outcome in setOf("kept", "same", "sheet")) "done" else "skipped", line)
        if (outcome == "kept") made(c, "pdf", "the version's page made")
        made(c, "pages", PAGES_DONE)
        return line
    }

    /** `keep_more`: the song's versions not kept yet kept in rank order, as many as one lookup may; its last line. */
    fun keepMore(c: CommandContext, library: LibraryStore, song: SongRow): String {
        val db = c.db
        val overrides = Overrides.read(db)
        val config = PhoneConfig.read(db)
        begun(c, song)
        val todo = SheetVersions.mayKeep(db, song.id, SheetVersions.inLibrary(db, song.id, config.rank), overrides.block)
        if (todo.isEmpty()) {
            return said(c, "skipped", "Nothing more to keep of ${song.display}: every Ultimate Guitar version caracole " +
                "may keep is kept already, or can't be.")
        }
        var kept = 0  // kept: a file, or a kept one's text
        var files = false  // a file written
        var changed = false  // a count moved
        val asked = c.asking.ask(PROVIDER) { client ->
            val ctx = FetchContext(db, client, overrides, config.rank, library, c.now)
            for (v in todo) {
                val outcome = UgFetch.keepVersion(ctx, song, v.tabId.toLong())
                if (outcome in setOf("kept", "same")) kept += 1
                files = files || outcome == "kept"
                changed = changed || outcome in setOf("kept", "same", "no text", "held", "gone")
                c.say(cameTo(c, library, song, v.tabId, outcome))
                stage(c, "version", "running", "kept $kept of ${todo.size}")
            }
        }
        if (asked is Asked.Cooling) return said(c, "skipped", cooling(asked.until))
        val stopped = if (asked is Asked.Done) null else stopped(config, asked)
        val spent = asked is Asked.Spent
        if ((c.asking.requests[PROVIDER] ?: 0) > 0 && (stopped == null || spent)) Health.recordOk(db, PROVIDER, c.now)
        val line = if (stopped != null && kept == 0) {
            val (state, why, again) = stopped
            nothingKept(why, again).also { stage(c, "version", state, it) }
        } else {
            var counted = "kept $kept of ${todo.size}"
            if (stopped != null && !spent) {  // a block or an error after some were kept: say it
                counted += "; ${stopped.second}"
                c.say("${stopped.second}.")
            }
            stage(c, "version", if (kept > 0) "done" else "skipped", counted)
            val left = SheetVersions.mayKeep(db, song.id, SheetVersions.inLibrary(db, song.id, config.rank),
                                             overrides.block).size
            val again = if (stopped == null || stopped.third) ": ask again" else ""  // not after a block: it cools down
            val versions = if (kept > 0) "$kept version" + (if (kept == 1) "" else "s") else "no version"
            "Kept $versions of ${song.display}; " + (if (left > 0) "$left more not kept$again." else "none is left to keep.")
        }
        if (stopped != null && !changed) return line  // nothing to write, as keep's refusals
        if (files) made(c, "pdf", "the versions' pages made")
        made(c, "pages", PAGES_DONE)
        return line
    }

    private const val SHEET_PAGE = "sheet.html"

    /** The pages stage's end, as versions_cmd.py words it once `write_pages` is done. */
    private const val PAGES_DONE = "_todo.md and index.html rewritten"

    /** `_listed`: the song's version [tab], one UG still has; else why there is none ([KeepRefused]). */
    private fun listed(c: CommandContext, config: PhoneConfig, song: SongRow, tab: Long): SheetVersion {
        val v = SheetVersions.inLibrary(c.db, song.id, config.rank).firstOrNull { it.tabId == tab.toString() }
            ?: throw KeepRefused("Tab $tab isn't one of the Ultimate Guitar chords versions of ${song.display}: " +
                                 "caracole versions \"${song.display}\" lists them.")
        if (v.gone) throw KeepRefused("Ultimate Guitar no longer has tab $tab of ${song.display}.")
        return v
    }

    /** The song found, its stage done, and the version's begun. */
    private fun begun(c: CommandContext, song: SongRow) {
        event(c, JsonObject(linkedMapOf("song" to JsonObject(linkedMapOf(
            "id" to JsonPrimitive(song.id), "display" to JsonPrimitive(song.display))))))
        stage(c, "song", "done", "in the book")
        stage(c, "version", "running")
    }

    /** The version stage ends in [state] with [line], said as its last line too. */
    private fun said(c: CommandContext, state: String, line: String): String {
        stage(c, "version", state, line)
        return line
    }

    /** The `pdf` or `pages` stage [name] where versions_cmd.py makes the song's pages (`render_all`, `write_pages`):
     * its running event, at which lane lookup's runner makes them (LookupJobs.CommandLines), then its end in
     * versions_cmd.py's words [done], which the runner says in the phone's own. */
    private fun made(c: CommandContext, name: String, done: String) {
        stage(c, name, "running")
        stage(c, name, "done", done)
    }

    private fun stage(c: CommandContext, name: String, state: String, detail: String = "") =
        event(c, JsonObject(linkedMapOf("stage" to JsonPrimitive(name), "state" to JsonPrimitive(state),
                                        "detail" to JsonPrimitive(detail))))

    /** get.py's `progress_line`: the event as json.dumps(ensure_ascii=False, separators=(",", ":")) writes it. */
    private fun event(c: CommandContext, event: JsonObject) = c.say(PROGRESS + PyJson.dumps(event, compact = true))

    private fun shown(at: Instant?): String = at?.let { WHEN.format(it) } ?: "later"

    /** `_cooling`'s words: Ultimate Guitar may not be asked now, its cooldown after a block. */
    private fun cooling(until: Instant?): String =
        "$NAME is cooling down after a block, until ${shown(until)}; nothing kept."

    /** `_stopped`: what stopped a keep, which the asking recorded (a block cooling Ultimate Guitar down, an error
     * counted): the version stage's state, why in words, and whether to ask again later (not after a block). */
    private fun stopped(config: PhoneConfig, asked: Asked<*>): Triple<String, String, Boolean> = when (asked) {
        is Asked.Blocked -> Triple("skipped", "$NAME blocked caracole (${asked.error.message}): no more requests to it " +
            "until ${shown(asked.state.cooldownUntil)}", false)
        is Asked.Failed -> Triple("failed", "$NAME failed (${asked.error.message})", true)
        is Asked.Off -> Triple("skipped", asked.why, true)
        else -> {
            val p = config.provider(PROVIDER)
            Triple("skipped", "The lookup requests to $NAME are spent (${p.lookupRequests} a lookup, " +
                "${p.lookupPerHour} an hour)", true)
        }
    }

    private fun nothingKept(why: String, again: Boolean): String =
        "$why; nothing kept." + if (again) " Ask again later." else ""

    /** `_came_to`: what [UgFetch.keepVersion] came to for one version, in a sentence; a version it can't keep (`no
     * text`, `held`) noted so, which `--keep-more` never reads again. */
    private fun cameTo(c: CommandContext, library: LibraryStore, song: SongRow, tab: String, outcome: String): String {
        if (outcome == "no text" || outcome == "held") SheetVersions.noteUnkeepable(c.db, song.id, tab)
        if (outcome == "kept") {
            val txt = File(library.folderOf(song), SheetVersions.versionNames(tab).first)
            return "Kept tab $tab beside the sheet of ${song.display}: ${txt.path}"
        }
        val page = if (outcome == "same") SheetVersions.samePages(c.db, song.id)[tab] ?: "another kept version"
                   else "another kept version"
        return "Tab $tab of ${song.display}: " + (KEPT_WORDS[outcome] ?: outcome).replace("{page}", page) + "."
    }
}
