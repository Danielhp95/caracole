package io.github.danielhp95.caracole.viewer.harpfit

import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PySequence
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.harptab.Group
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Tab
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/** harpfit.Fit: a harp's fit with the record, its key (a pitch class), the share of the sung notes on a chord tone,
 * of how many. */
data class Fit(val harp: Int, val share: Double, val notes: Int)

/** harpfit.Choice: the harp a tab's page starts on ([harp], a pitch class) and why ([why], one of [HarpFit.WHY]); the
 * fit with the record, best first ([fits], none without a sheet that matches); the harp the tab's words name
 * ([named]) and the key its page names ([page]), pitch classes or null; and the tonic the song sounds in, or null. */
data class Choice(val harp: Int, val why: String, val fits: List<Fit> = emptyList(), val named: Int? = null,
                  val page: Int? = null, val tonic: Int? = null) {
    /** Choice.tabs_harp: the harp the tab is played on, as far as caracole can tell: the one that plays with the
     * record, else the one its words name; null where the page's harp is a guess (harptabs.com's key, the song's key,
     * a C harp). The overlay marks it "the tab's", and a chord sheet's starts on it (page.py `harpTabs`). */
    val tabsHarp: Int? get() = if (why == "record" || why == "tab") harp else null
}

/** One harmonica tab a song keeps, as render.py's `_tab_harps` reads it: its file's [name] ("harmonica-1.txt"), its
 * [text] (the file's bytes decoded as render.py's `.decode("utf-8", errors="replace")`, core.py.PyCodec.utf8Replace;
 * null where it can't be read: no harp then), the page's harp chip
 * ([harp], harptab.py `parse`'s), the key its page names ([pageKey]) and how overrides.toml's `[harmonica]` has it read
 * ([pin], or null). */
data class HarmonicaTab(val name: String, val text: String?, val harp: String? = null, val pageKey: String? = null,
                        val pin: JsonElement? = null)

/**
 * viewer/harpfit.py: the harp a harmonica tab (viewer.harptab) is played on, for its page (HarmonicaPage): the one that
 * plays along with the record, from the song's chord sheet, else the one the tab's words name, else the key
 * harptabs.com's page names, else Harp.choices' first for the song's key, else a C harp. Its constants are harpfit.py's
 * own (data/caracole/viewer/harmonica_page.json's `harpfit`); [words]' three patterns are its code, through
 * core.py.PyRegex, so `\w` is Python's.
 */
object HarpFit {
    private val json by lazy { ViewerData.table("harmonica_page").getValue("harpfit").jsonObject }

    /** The sung notes on a chord of the sheet the fit needs before it names a harp. */
    val MIN_NOTES: Int by lazy { json.getValue("MIN_NOTES").jsonPrimitive.int }

    /** How alike a tab's row and a sheet's line read, word by word, to be the same line. */
    val LINE_MATCH: Double by lazy { json.getValue("LINE_MATCH").jsonPrimitive.double }

    /** Where a choice comes from: "record", "tab", "page", "song", "usual". */
    val WHY: List<String> by lazy {
        Collections.unmodifiableList(json.getValue("WHY").jsonArray.map { it.jsonPrimitive.content })
    }

    private val PITCH: Map<String, Int> by lazy {
        json.getValue("_PITCH").jsonObject.mapValues { (_, v) -> v.jsonPrimitive.int }
    }

    private val HYPHEN by lazy { PyRegex.compile("(?<=\\w)-+(?=\\w)") }
    private val BRACKETED by lazy { PyRegex.compile("\\([^)]*\\)") }
    private val WORD by lazy { PyRegex.compile("[^\\W_]+(?:'[^\\W_]+)*") }

    /** pitch: a key's name as a tab or harptabs.com writes it ("A", "Bb", "F#") as a pitch class; null for none. */
    fun pitch(name: String?): Int? = PITCH[PyText.strip(name ?: "").replace("♭", "b").replace("♯", "#")]

    /** words: [text]'s words as the fit compares them: lower case, a hyphen inside a word gone ("des-ert" is
     * "desert"), what is in brackets left out ("(background)"). */
    fun words(text: String): List<String> {
        val joined = PyRe.sub(HYPHEN, PyUnicode.lower(text).replace("’", "'")) { "" }
        return PyRe.findall(WORD, PyRe.sub(BRACKETED, joined) { " " })
    }

    /** _sheet_lines: each sung line of a ChordPro sheet, its words, each with the pitch classes of the chord sounding
     * there (the capo added; null before the first chord of its section, or for a chord caracole can't read). */
    fun sheetLines(cho: String): List<List<Pair<String, Set<Int>?>>> {
        val sheet = Sheets.parse(cho)
        val capo = sheet.capo ?: 0
        val out = ArrayList<List<Pair<String, Set<Int>?>>>()
        for (section in sheet.sections) {
            var soundingNow: Set<Int>? = null
            for (line in section.lines) {
                if (line !is Lyrics) continue
                val found = ArrayList<Pair<String, Set<Int>?>>()
                for ((chord, text) in line.parts) {
                    if (chord is Item.Chord) {
                        val read = Theory.parseChord(sheet.chords[chord.index], strict = false)
                        soundingNow = read?.pitchClasses?.mapTo(sortedSetOf()) { Math.floorMod(it + capo, 12) }
                    }
                    for (w in words(text)) found += w to soundingNow
                }
                if (found.isNotEmpty()) out += found
            }
        }
        return out
    }

    private fun firstNote(group: Group): Int? {
        val hole = group.holes.firstOrNull() ?: return null  // what the tab's notation couldn't read
        return if (hole.button) null else Harp.holeNote(0, hole.hole, hole.breath, hole.bend, hole.over)
    }

    /** record_fit: how well each of the 12 harps plays [tab] with the record the chord sheet [cho] (as caracole writes
     * one) charts, best first (by share, then by harp); none counted (a sheet with no line like the tab's), none. */
    fun recordFit(tab: Tab, cho: String): List<Fit> {
        val lines = sheetLines(cho)
        if (lines.isEmpty()) return emptyList()
        val pairs = ArrayList<Pair<Int, Set<Int>>>()  // each note on a C harp, and the chord sounding there
        for (row in tab.rows()) {
            if (row.lyric == null) continue
            val sung = ArrayList<Pair<String, MutableList<Int>>>()
            for ((groups, text) in row.parts) {
                val notes = groups.mapNotNullTo(ArrayList()) { firstNote(it) }
                val said = words(text)
                if (said.isEmpty()) {
                    if (sung.isNotEmpty()) sung.last().second.addAll(notes)
                    continue
                }
                said.forEachIndexed { k, w -> sung += w to (if (k == 0) notes else ArrayList()) }
            }
            val mine = sung.map { it.first }
            if (mine.isEmpty()) continue
            var best: List<Pair<String, Set<Int>?>>? = null
            var ratio = 0.0
            for (line in lines) {
                val alike = PySequence.SequenceMatcher(mine, line.map { it.first }).ratio()
                if (alike > ratio) {
                    best = line
                    ratio = alike
                }
            }
            if (best == null || ratio < LINE_MATCH) continue
            val matcher = PySequence.SequenceMatcher(mine, best.map { it.first })
            for ((a, b, size) in matcher.matchingBlocks()) {
                for (k in 0 until size) {
                    val chord = best[b + k].second
                    if (!chord.isNullOrEmpty()) for (n in sung[a + k].second) pairs += n to chord
                }
            }
        }
        if (pairs.isEmpty()) return emptyList()
        val fits = (0 until 12).map { t ->
            Fit(t, pairs.count { (n, chord) -> Math.floorMod(n + t, 12) in chord }.toDouble() / pairs.size, pairs.size)
        }
        return fits.sortedWith(compareBy<Fit>({ -it.share }, { it.harp }))
    }

    /** _song_key: the key the song sounds in (the sheet's, as its viewer names it, the capo added), and its chords as
     * they sound; null and none for a sheet with no key. */
    private fun songKey(cho: String, key: String?, keySource: String?): Pair<Key?, List<Chord>> {
        val shapes = SheetView.viewerKey(cho, key, keySource) ?: return null to emptyList()
        val sheet = Sheets.parse(cho)
        val capo = sheet.capo ?: 0
        val chords = sheet.chords.mapNotNull { name ->
            Theory.parseChord(name, strict = false)?.let { chord ->
                chord.copy(root = Math.floorMod(chord.root + capo, 12), bass = chord.bass?.let { Math.floorMod(it + capo, 12) })
            }
        }
        return Theory.sounding(shapes, capo) to chords
    }

    /** choose: the harp [tab]'s page starts on: [cho] is the song's chord sheet (its ChordPro as caracole writes it),
     * [key] and [keySource] its key as keys.py found it, [pageKey] the key harptabs.com's page names. */
    fun choose(tab: Tab, cho: String? = null, key: String? = null, keySource: String? = null,
               pageKey: String? = null): Choice {
        val named = pitch(tab.key)
        val page = pitch(pageKey)
        val (song, chords) = if (!cho.isNullOrEmpty()) songKey(cho, key, keySource) else null to emptyList()
        val tonic = song?.tonic
        val fits = if (!cho.isNullOrEmpty() && tab.readable) recordFit(tab, cho) else emptyList()
        if (fits.isNotEmpty() && fits[0].notes >= MIN_NOTES) return Choice(fits[0].harp, "record", fits, named, page, tonic)
        if (named != null) return Choice(named, "tab", fits, named, page, tonic)
        if (page != null) return Choice(page, "page", fits, named, page, tonic)
        if (song != null) {
            val found = Harp.choices(song, chords)
            if (found.isNotEmpty()) return Choice(found[0].harp, "song", fits, named, page, tonic)
        }
        return Choice(0, "usual", fits, named, page, tonic)
    }

    /**
     * render._tab_harps: the harp each harmonica tab the song keeps is played on, by its file's name, as its page
     * chooses it with the song's chord sheet [cho] (in [key], keys.py's, and where it came from), the tab read as its
     * page reads it (its pin: HarpTabs.pinned): [Choice.tabsHarp]. A tab with neither, whose text can't be read, or
     * that can't be read at all (a pin overrides.toml would refuse among them, as render.py's `except Exception`
     * skips it, a RecursionError too: here a StackOverflowError), has none: its sheet's overlay starts on
     * Harp.choices' first harp.
     */
    fun tabHarps(tabs: List<HarmonicaTab>, cho: String, key: String? = null, keySource: String? = null): Map<String, Int> {
        val out = LinkedHashMap<String, Int>()
        for (tab in tabs) {
            val text = tab.text ?: continue
            val found = try {
                val notation = tab.pin?.takeIf { it !is JsonNull }?.let { HarpTabs.pinned(it, text) }
                choose(HarpTabs.parse(text, harp = tab.harp, notation = notation), cho, key, keySource, tab.pageKey)
            } catch (e: Exception) {  // a tab the overlay can't read must never cost the sheet's viewer
                continue
            } catch (e: StackOverflowError) {  // Python's RecursionError is an Exception
                continue
            }
            found.tabsHarp?.let { out[tab.name] = it }
        }
        return out
    }
}
