package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.HarmonicaFile
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.pages.HarmonicaPage
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * `caracole harmonica` on the phone (commands/harmonica.py and harmonica_cmd.py), one song's, `-- ARTIST TITLE`:
 *
 * - `--as=NOTATION [--symbol=SYMBOL=MEANING]…` (`--tab=NAME`, the song's only tab by default): the tab read so,
 *   whatever caracole guesses, the pin checked as harptab.py's `check_spec` checks it (HarpTabs.checkSpec), recorded
 *   in `[harmonica]` (OverrideWriters.addHarmonica), then the song rendered again (PhoneParts.pages, for the song
 *   alone: its tab's page and its sheet's viewers, whose overlay starts on the harp the tab plays on); a pin by the
 *   tab's own legend needs a tab with one;
 * - `--clear`: the tab's `[harmonica]` entry taken out, then the same: caracole guesses how it is read again;
 * - neither: how each of the song's tabs is read, and every reading caracole weighs for it, best first.
 *
 * Each in one `database.writeBlocking` on the queue's worker, its lines its job's output; a usage error (a tab the song
 * hasn't got, a legend the tab hasn't got, a reading that is none) exits 2 and writes nothing, as Python's does, in
 * its words. vectors/web/harmonica_routes.jsonl's `caracole harmonica` records hold it to Python's (ChoicesReplay).
 * [readOverrides] stands in for the phone's overrides, a test's.
 */
class HarmonicaRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = Overrides::read) :
    CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = line(args)
        if (line.asked != null && line.clear) throw CommandExit(2, "caracole harmonica takes one of --as and --clear")
        if (line.symbols.isNotEmpty() && line.asked == null) {
            throw CommandExit(2, "--symbol needs --as: the notation whose symbol it changes")
        }
        val spec = line.asked?.let { spec(it, line.symbols) }
        val display = artistTitle(line.words).let { (artist, title) -> "$artist - $title" }
        parts.database.writeBlocking { db ->
            when {
                spec != null -> pin(db, display, line.tab, spec, context)
                line.clear -> clear(db, display, line.tab, context)
                else -> show(db, display, context)
            }
        }
    }

    /** The command line as typer reads it: `--tab`, `--as` and each `--symbol` (`--name=value` or `--name value`),
     * `--clear`, and the song's words (after `--`, or the rest). */
    private class Line(val tab: String?, val asked: String?, val symbols: List<String>, val clear: Boolean,
                       val words: List<String>)

    private fun line(args: List<String>): Line {
        var tab: String? = null
        var asked: String? = null
        val symbols = ArrayList<String>()
        var clear = false
        val words = ArrayList<String>()
        var i = 1  // after the command's own word
        while (i < args.size) {
            val arg = args[i]
            if (arg == "--") {
                words += args.subList(i + 1, args.size)
                break
            }
            if (!arg.startsWith("--")) {
                words += arg
                i++
                continue
            }
            val name = arg.substringBefore('=')
            if (name == "--clear" && '=' !in arg) {
                clear = true
                i++
                continue
            }
            if (name !in TAKES_VALUE) throw CommandExit(2, "No such option: $name")
            val value = if ('=' in arg) arg.substringAfter('=') else {
                i++
                args.getOrNull(i) ?: throw CommandExit(2, "Option '$name' requires an argument.")
            }
            when (name) {
                "--tab" -> tab = value
                "--as" -> asked = value
                else -> symbols += value
            }
            i++
        }
        return Line(tab, asked, symbols, clear, words)
    }

    /** commands/harmonica.py's `_spec`: the pin `--as` and its `--symbol`s say, checked; a usage error else. */
    private fun spec(name: String, symbols: List<String>): JsonElement {
        var spec: JsonElement = JsonPrimitive(name)
        if (symbols.isNotEmpty()) {
            val table = LinkedHashMap<String, JsonElement>()
            table["as"] = JsonPrimitive(name)
            for (given in symbols) {
                val at = given.lastIndexOf('=')
                val sym = if (at >= 0) given.substring(0, at) else ""
                if (at < 0 || sym.isEmpty()) {
                    throw CommandExit(2, "--symbol: expected SYMBOL=MEANING (\"*=bend\"), got ${PyStr.repr(given)}")
                }
                table[sym] = JsonPrimitive(given.substring(at + 1))
            }
            spec = JsonObject(table)
        }
        try {
            HarpTabs.checkSpec(spec)
        } catch (e: IllegalArgumentException) {
            throw CommandExit(2, if (symbols.isEmpty()) "--as: ${e.message}" else "--symbol: ${e.message}")
        }
        return spec
    }

    /** commands/harmonica.py's `_artist_title`: "Artist - Title", or ARTIST TITLE. */
    private fun artistTitle(words: List<String>): Pair<String, String> {
        val (artist, title, sep) = when (words.size) {
            1 -> words[0].indexOf(" - ").let { at ->
                if (at < 0) Triple(words[0], "", false) else Triple(words[0].substring(0, at), words[0].substring(at + 3), true)
            }
            2 -> Triple(words[0], words[1], true)
            else -> Triple("", "", false)
        }
        if (!sep || Py.strip(artist).isEmpty() || Py.strip(title).isEmpty()) {
            throw CommandExit(2, "caracole harmonica takes a song as \"Artist - Title\", or as ARTIST TITLE, not " +
                                 PyStr.repr(words.joinToString(" ")))
        }
        return Py.strip(artist) to Py.strip(title)
    }

    /** harmonica_cmd.spec_words: a pin in a few words: "letters", "legend", "signs, *=bend". */
    private fun specWords(spec: JsonElement): String {
        if (spec is JsonPrimitive) return spec.content
        val table = spec as JsonObject
        return (listOf((table["as"] as? JsonPrimitive)?.content ?: "signs") +
            table.filterKeys { it != "as" }.map { (k, v) -> "$k=${(v as JsonPrimitive).content}" }).joinToString(", ")
    }

    /** harmonica_cmd._tab: the song's harmonica tab [name], or its only one; a usage error else. */
    private fun tab(db: Db, song: SongRow, name: String?): HarmonicaFile {
        val tabs = HarmonicaFiles.of(db, song.id)
        if (tabs.isEmpty()) throw CommandExit(2, "${song.display} keeps no harmonica tab")
        if (name == null) {
            if (tabs.size > 1) {
                throw CommandExit(2, "${song.display} keeps ${tabs.size} harmonica tabs: say which with --tab: " +
                                     tabs.joinToString(" or ") { it.name })
            }
            return tabs[0]
        }
        return tabs.firstOrNull { it.name == name } ?: throw CommandExit(
            2, "${song.display} has no harmonica tab $name: it keeps " + tabs.joinToString(", ") { it.name })
    }

    /** harmonica_cmd._render: the song rendered again, as the overrides now say (the library page is made as it is
     * asked for). */
    private fun render(db: Db, song: SongRow) {
        val stats = parts.pages.render(db, listOf(song.id), null)
        if (stats.failed.isNotEmpty()) {
            throw CommandExit(1, "${song.display}: its pages could not all be rendered again; the log says why")
        }
    }

    /** harmonica_cmd.pin. */
    private fun pin(db: Db, display: String, tabName: String?, spec: JsonElement, context: JobContext) {
        val overrides = LookupJobs.overrides(db, readOverrides)
        val song = LookupJobs.songNamed(parts, db, display, overrides)
        val tab = tab(db, song, tabName)
        val text = HarmonicaPage.tabText(db, parts.store.libraryDir, song, tab)
            ?: throw CommandExit(1, "${tab.name} of ${song.display} can't be read")
        if (spec == JsonPrimitive("legend") && HarpTabs.pinned(spec, text) == null) {
            throw CommandExit(2, "${tab.name} has no legend of its own: name a notation instead")
        }
        try {
            OverrideWriters.addHarmonica(db, song.display, tab.name, spec, HarpTabs::checkSpec)
        } catch (e: OverridesError) {
            throw CommandExit(1, "overrides.toml can't be written: ${e.message}")
        }
        render(db, song)
        val read = HarpTabs.parse(text, tab.harp, HarpTabs.pinned(spec, text)).reading
        context.say("${tab.name} of ${song.display} is read as ${specWords(spec)}, as you set it: ${read.said()}")
    }

    /** harmonica_cmd.clear. */
    private fun clear(db: Db, display: String, tabName: String?, context: JobContext) {
        val overrides = LookupJobs.overrides(db, readOverrides)
        val song = LookupJobs.songNamed(parts, db, display, overrides)
        val tab = tab(db, song, tabName)
        if (LookupJobs.overrides(db, readOverrides).harmonica[song.key]?.containsKey(tab.name) != true) {
            context.say("No [harmonica] entry pins how ${tab.name} is read: caracole guesses it already.")
            return
        }
        try {
            OverrideWriters.addHarmonica(db, song.display, tab.name, null, HarpTabs::checkSpec)
        } catch (e: OverridesError) {
            throw CommandExit(1, "overrides.toml can't be written: ${e.message}")
        }
        render(db, song)
        context.say("Took ${tab.name} of ${song.display} out of [harmonica] in overrides.toml: caracole guesses how " +
                    "${tab.name} is read again.")
    }

    /** harmonica_cmd.show: each of the song's harmonica tabs, how it is read, and the readings caracole weighs. */
    private fun show(db: Db, display: String, context: JobContext) {
        val overrides = LookupJobs.overrides(db, readOverrides)
        val song = LookupJobs.songNamed(parts, db, display, overrides)
        val tabs = HarmonicaFiles.of(db, song.id)
        val texts = tabs.map { it to HarmonicaPage.tabText(db, parts.store.libraryDir, song, it) }
        if (tabs.isEmpty()) return context.say("${song.display} keeps no harmonica tab.")
        for ((tab, text) in texts) {
            if (text == null) {
                context.say("${tab.name}: can't be read")
                continue
            }
            val pin = overrides.harmonica[song.key]?.get(tab.name)
            val read = HarpTabs.parse(text, tab.harp, pin?.let { HarpTabs.pinned(it, text) }).reading
            context.say("${tab.name}: read as ${read.said().ifEmpty { "no hole read" }}, " +
                        "${HarmonicaPage.SOURCES.getValue(read.source)} (Q ${PyFormat.fixed(read.q, 2)})")
            for (other in HarpTabs.readings(text, tab.harp)) {
                val words = specWords(HarpTabs.specOf(other))
                context.say("  ${words}${" ".repeat(maxOf(0, 12 - Py.len(words)))} Q ${PyFormat.fixed(other.q, 2)}  ${other.said()}")
            }
        }
    }

    private companion object {
        val TAKES_VALUE = setOf("--tab", "--as", "--symbol")
    }
}
