package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.harmony.Harmony
import io.github.danielhp95.caracole.viewer.harmony.HarmonyTables
import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.harpfit.Choice
import io.github.danielhp95.caracole.viewer.harpfit.HarpFit
import io.github.danielhp95.caracole.viewer.harptab.Gap
import io.github.danielhp95.caracole.viewer.harptab.Group
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Hole
import io.github.danielhp95.caracole.viewer.harptab.Legend
import io.github.danielhp95.caracole.viewer.harptab.Notation
import io.github.danielhp95.caracole.viewer.harptab.Prose
import io.github.danielhp95.caracole.viewer.harptab.Reading
import io.github.danielhp95.caracole.viewer.harptab.Row
import io.github.danielhp95.caracole.viewer.harptab.Tab
import io.github.danielhp95.caracole.viewer.harptab.TabSection
import io.github.danielhp95.caracole.viewer.harptab.Words
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigInteger

/**
 * viewer/harptab_page.py: harmonica-N.html, a harmonica tab caracole kept from harptabs.com as a page in the sheet
 * viewer's look, byte for byte as `build_harmonica_viewer` writes it for the same inputs. It is sheet.html's kind of
 * page (SheetPage's frame: `_page`, `names_table`, `zh_attr`, `artist_line`, `_words`), its stylesheets viewer.css then
 * harptab.css and its scripts strum.js, overlay.js then harptab.js (ViewerAssets.Page.HARMONICA); the tab read by
 * viewer.harptab (HarpTabs.parse) and the harp it starts on chosen by HarpFit.choose. Its HTML is harptab_page.py's:
 * the bar, the bar of a tab shown as written and the pill, and its constants, are data
 * (data/caracole/viewer/harmonica_page.json's `harptab_page`, written from the module), the rest its code here. Its
 * numbers are written as Python writes them: `round(q, 2)` (Py.round, a float of PyJson's), `{share:.0%}`,
 * `{views/1000:.0f}k`, `{views/1e6:.1f}M`, `{rating:.1f}★` and `({q:.2f})` (PyFormat).
 */
object HarmonicaPage {
    private val json by lazy { ViewerData.table("harmonica_page").getValue("harptab_page").jsonObject }
    private fun text(name: String): String = json.getValue(name).jsonPrimitive.content
    private fun texts(name: String): Map<String, String> =
        json.getValue(name).jsonObject.mapValuesTo(LinkedHashMap()) { it.value.jsonPrimitive.content }

    /** A line played: a hole a beat. */
    val BPM: Int by lazy { json.getValue("BPM").jsonPrimitive.int }
    val SITE: String by lazy { text("SITE") }
    /** What the header and the bar say of the harp the page starts on, by why it was chosen (HarpFit.WHY). */
    private val SAID: Map<String, String> by lazy { texts("_SAID") }
    private val BRACKETS: Map<String, Pair<String, String>> by lazy {
        json.getValue("_BRACKETS").jsonObject.mapValuesTo(LinkedHashMap()) { (_, v) ->
            v.jsonArray[0].jsonPrimitive.content to v.jsonArray[1].jsonPrimitive.content
        }
    }
    private val JOIN: String by lazy { text("_JOIN") }
    private val SOURCE: Map<String, String> by lazy { texts("_SOURCE") }
    private val PLAY_ICON: String by lazy { text("_PLAY_ICON") }
    private val NO_SHEET: String by lazy { text("_NO_SHEET") }
    private val NO_KEY: String by lazy { text("_NO_KEY") }
    /** The bar, hidden until the script runs; a tab shown as written has the overlay's buttons, Aa and ▶ alone. */
    val BAR: String by lazy { text("_BAR") }
    val BAR_RAW: String by lazy { text("_BAR_RAW") }
    /** Scrolling by itself, as the viewer's: the pill that steers it, above the bar's place. */
    val PILL: String by lazy { text("_PILL") }

    /**
     * build_harmonica_viewer: the page of the harmonica tab [text] (a `harmonica-N.txt`'s body, its bytes decoded as
     * render.py's `.decode("utf-8", errors="replace")`, core.py.PyCodec.utf8Replace) of the song [title] by
     * [artist]. [tabFile] names the text beside the page, which its foot links; [url] is the tab's page on
     * harptabs.com, [pageKey] the key it names, [harp] the harp ("Diatonic", "Chromatic": HarpTabs.parse reads the tab
     * for it), [pin] how the owner has it read (overrides.toml's `[harmonica]`: a preset's name, "legend" or a table;
     * one HarpTabs.pinned refuses, or a legend the tab hasn't got, is read as guessed), [facts] what else it says (the
     * version's raw: `difficulty`, `views`, `rating`). [cho] is the song's chord sheet (its human one, else its auto
     * one), with [key] and [keySource], its key as keys.py found it. [back] names the song's sheet viewer beside the
     * page, which ‹ Chord sheet opens; with none, ‹ Library.
     */
    fun build(text: String, title: String, artist: String = "", tabFile: String, url: String? = null,
              pageKey: String? = null, harp: String? = null, pin: JsonElement? = null, facts: JsonObject? = null,
              cho: String? = null, key: String? = null, keySource: String? = null, back: String? = null): String {
        val tab = HarpTabs.parse(text, harp = harp, notation = pinned(pin, text))
        val choice = HarpFit.choose(tab, cho = cho, key = key, keySource = keySource, pageKey = pageKey)
        val data = Data(tab, choice)
        data.overlay = overlayData(choice, cho, key, keySource)
        val named = title.ifEmpty { "Untitled" }
        val pageTitle = "$named · harmonica tab"
        // The song's names in the characters its viewer shows its Chinese in, for a song whose sheet is Chinese
        val names = SheetPage.namesTable(cho != null && SheetPage.isChinese(cho), listOf(named, artist, pageTitle))
        val readable = tab.readable
        val head = header(title, artist, tab, choice, facts ?: JsonObject(emptyMap()), back, names)
        val article = if (readable) tabHtml(tab, data) else rawHtml(text)
        val placed = readable && tab.rows().any { it.trusted && !it.lyric.isNullOrEmpty() }
        val body = StringBuilder()
            .append("<aside class=\"necks\" id=\"necks\" hidden aria-label=\"Chord necks\"></aside>\n")
            .append("<div class=\"page\">\n")
            .append(head)
            .append(article)
            .append(footer(tabFile, url, placed = placed, change = !readable || tab.reading.standard))
            .append("</div>\n")
            .append(if (readable) BAR else BAR_RAW)
            .append(PILL)
            .append(Inline.jsonBlock("harp-data", data.json()))
            .append(if (!names.isNullOrEmpty()) Inline.jsonBlock("song-names", namesJson(names)) else "")
            .toString()
        return SheetPage.page(pageTitle, body, ViewerAssets.styles(ViewerAssets.Page.HARMONICA),
                          ViewerAssets.scripts(ViewerAssets.Page.HARMONICA), names)
    }

    // --- the data ------------------------------------------------------------------------------------------------

    /** The page's `harp-data`, its members in Python's order; [groups] and [rows] filled as the tab is written. */
    private class Data(tab: Tab, choice: Choice) {
        val head = LinkedHashMap<String, JsonElement>()
        val groups: MutableList<JsonElement>? = if (tab.readable) ArrayList() else null
        val rows: MutableList<JsonElement>? = if (tab.readable) ArrayList() else null
        var overlay: JsonElement = JsonNull

        init {
            val why = LinkedHashMap<String, JsonElement>()
            for ((pc, reason) in listOf(choice.harp to choice.why, choice.named to "tab", choice.page to "page")) {
                if (pc != null && SAID.getValue(reason).isNotEmpty() && pc.toString() !in why) {
                    why[pc.toString()] = JsonPrimitive(SAID.getValue(reason))
                }
            }
            head["harpKeys"] = JsonArray(Harp.HARP_KEYS.map(::JsonPrimitive))
            head["start"] = JsonPrimitive(choice.harp)
            head["why"] = JsonObject(why)
            head["positions"] = choice.tonic?.let { tonic ->
                JsonArray((0 until 12).map { JsonPrimitive(Harp.positionText(tonic, it)) })
            } ?: JsonNull
            head["names"] = JsonArray((0 until 12).map { h -> JsonArray(Theory.spelling(Key(h, "ionian")).map(::JsonPrimitive)) })
            head["holes"] = Harp.holeTables()
            head["bpm"] = JsonPrimitive(BPM)
            val reading = tab.reading
            head["reading"] = JsonObject(linkedMapOf(
                "name" to JsonPrimitive(reading.notation.name), "source" to JsonPrimitive(reading.source),
                "q" to PyJson.float(Py.round(reading.q, 2)), "margin" to PyJson.float(Py.round(reading.margin, 2)),
                "said" to JsonPrimitive(reading.said())))
        }

        fun json(): JsonObject {
            val out = LinkedHashMap<String, JsonElement>(head)
            if (groups != null) out["groups"] = JsonArray(groups)
            if (rows != null) out["rows"] = JsonArray(rows)
            out["overlay"] = overlay
            return JsonObject(out)
        }
    }

    // --- the overlay: Harmonica and Guitar -----------------------------------------------------------------------

    /** _overlay_data: what the page's overlay draws, the song's chord sheet [cho] as written, in its key ([key],
     * [keySource]: keys.py's, as its viewer reads them), with the harp [choice] the page starts on: `guitar`, the Guitar
     * tab, or null for a song with no sheet; `harp`, the Harmonica tab, with the sheet's key as it sounds, or with none
     * the line that says so and each harp's notes. */
    fun overlayData(choice: Choice, cho: String?, key: String?, keySource: String?): JsonObject {
        val holes = JsonArray((0 until 12).map { Harp.holes(it) })
        val sheet = if (!cho.isNullOrEmpty()) Sheets.parse(cho) else null
        val shapes = if (!cho.isNullOrEmpty()) SheetView.viewerKey(cho, key, keySource) else null
        if (sheet == null || shapes == null) {
            return JsonObject(linkedMapOf(
                "guitar" to (if (sheet != null) guitarData(sheet, null) else JsonNull),
                "harp" to JsonObject(linkedMapOf("key" to JsonNull,
                                                 "none" to JsonPrimitive(if (sheet != null) NO_KEY else NO_SHEET),
                                                 "holes" to holes))))
        }
        val sounds = Theory.sounding(shapes, sheet.capo ?: 0)
        val names = Theory.spelling(sounds)
        val capo = Math.floorMod(sounds.tonic - shapes.tonic, 12)
        val found = Harp.tables(shapes, mapOf(shapes.mode to sheet.chords.map { Theory.parseChord(it, strict = false) }))
        val chords = ArrayList<JsonElement>()
        for ((i, name, chord) in once(sheet)) {
            val form = found.getValue("harpChords").jsonObject.getValue(shapes.mode).jsonArray[i]
            val notes = found.getValue("harpNotes").jsonObject.getValue(shapes.mode).jsonArray[i]
            val sound = if (capo == 0) name else HarmonyTables.pageName(chord, names, capo)
            chords += JsonObject(linkedMapOf(
                "name" to JsonPrimitive(sound), "shape" to JsonPrimitive(if (sound == name) "" else name),
                "root" to JsonPrimitive(names[Math.floorMod(chord.root + capo, 12)]),
                "entries" to found.getValue("harpForms").jsonArray[form.jsonPrimitive.int], "notes" to notes))
        }
        val tabs = choice.tabsHarp?.let { listOf(JsonPrimitive(Math.floorMod(it - sounds.tonic, 12))) } ?: emptyList()
        return JsonObject(linkedMapOf(
            "guitar" to guitarData(sheet, shapes),
            "harp" to JsonObject(linkedMapOf(
                "key" to JsonPrimitive(Theory.keyName(sounds)), "tonic" to JsonPrimitive(sounds.tonic),
                "names" to JsonArray(names.map(::JsonPrimitive)), "ring" to found.getValue("harpRing"),
                "holes" to holes, "scales" to found.getValue("harpScales").jsonObject.getValue(shapes.mode),
                "outside" to found.getValue("harpOutside").jsonObject.getValue(shapes.mode),
                "choices" to found.getValue("harps").jsonObject.getValue(shapes.mode),
                "chords" to JsonArray(chords), "tabs" to JsonArray(tabs)))))
    }

    /** _once: the sheet's chords as its viewer's rail lists them: each it can read, once a name, in the order they
     * come, with its place among the sheet's chords. */
    private fun once(sheet: Sheet): List<Triple<Int, String, Chord>> {
        val out = ArrayList<Triple<Int, String, Chord>>()
        val seen = HashSet<String>()
        sheet.chords.forEachIndexed { i, name ->
            val chord = Theory.parseChord(name, strict = false)
            if (chord != null && seen.add(name)) out += Triple(i, name, chord)
        }
        return out
    }

    /** _guitar_data: the Guitar tab: each chord of the sheet as written with its positions on the guitar (the sheet's
     * own first: `mine`), and the key's neck (none for a sheet with no key). */
    private fun guitarData(sheet: Sheet, shapes: Key?): JsonObject {
        val given = SheetView.shapesOf(sheet)
        val guitar = Instruments.GUITAR
        val chords = once(sheet).map { (_, name, chord) ->
            val bass = chord.bass?.toString() ?: ""
            val mine = (given["${chord.root},${chord.suffix},$bass"] as? JsonObject)?.get("mine") ?: JsonPrimitive(0)
            JsonObject(linkedMapOf("name" to JsonPrimitive(name), "list" to Instruments.chordShapes(guitar, chord, 0, given),
                                   "mine" to mine))
        }
        val neck: JsonElement = if (shapes == null) JsonNull else {
            val box = Harmony.pentatonic(shapes).map { Math.floorMod(it - shapes.tonic, 12) }
            JsonObject(linkedMapOf(
                "name" to JsonPrimitive(Theory.keyName(shapes)), "tonic" to JsonPrimitive(shapes.tonic),
                "tonicName" to JsonPrimitive(Theory.spelling(shapes)[shapes.tonic]),
                "scale" to JsonArray(Harmony.keyScale(shapes).map { JsonPrimitive(Math.floorMod(it - shapes.tonic, 12)) }),
                "pentatonic" to JsonArray(box.map(::JsonPrimitive)),
                "pentaName" to JsonPrimitive(if (4 in box) "major pentatonic" else "minor pentatonic"),
                "tuning" to JsonArray(guitar.tuning.map(::JsonPrimitive))))
        }
        return JsonObject(linkedMapOf("name" to JsonPrimitive(guitar.name), "strings" to JsonPrimitive(guitar.tuning.size),
                                      "chords" to JsonArray(chords), "key" to neck))
    }

    // --- the header ----------------------------------------------------------------------------------------------

    /** _a: "a D harp", "an A harp", "an F harp", "an Eb harp". */
    fun a(name: String): String = (if (name[0] in "AEF") "an " else "a ") + name + " harp"

    private fun header(title: String, artist: String, tab: Tab, choice: Choice, facts: JsonObject, back: String?,
                       names: Map<String, Map<String, String>>?): String {
        val link = if (!back.isNullOrEmpty()) {
            "<a class=\"back\" href=\"${PyText.escape(PyUrl.quote(back))}\" data-sheet>‹ Chord sheet</a>\n"
        } else {
            "<a class=\"back\" href=\"${SheetPage.LIBRARY_PAGE}\">‹ Library</a>\n"
        }
        val named = title.ifEmpty { "Untitled" }
        val readable = tab.readable
        return "<header class=\"head\">\n" + link +
            "<h1${SheetPage.zhAttr(named, names)}>${PyText.escape(named)}</h1>\n" +
            SheetPage.artistLine(artist, names) +
            (if (readable) harpLines(choice) else
                "<p class=\"facts\" id=\"facts\">Harmonica tab, as its tabber wrote it: caracole can't read its notation.</p>\n") +
            (if (readable) readAs(tab.reading, facts) else "") +
            "</header>\n"
    }

    /** _harp_lines: the header's harp: which, why, the position it plays the song in; with the record, how well it
     * fits. */
    fun harpLines(choice: Choice): String {
        val name = Harp.HARP_KEYS[choice.harp]
        val where = choice.tonic?.let { " (${PyText.escape(Harp.positionText(it, choice.harp))})" } ?: ""
        val said = when (choice.why) {
            "record" -> "<b>$name harp</b> with the record$where"
            "tab" -> "<b>$name harp</b>, as the tab says$where"
            "page" -> "<b>$name harp</b>, as harptabs.com's key says$where"
            "song" -> "<b>$name harp</b> for the song's key$where"
            "usual" -> "<b>$name harp</b>, as tabs are written when they name none$where"
            else -> throw NoSuchElementException(choice.why)
        }
        val bits = mutableListOf("Harmonica tab", said)
        if (choice.why == "record" && choice.named != null && choice.named != choice.harp) {
            bits += "the tab says ${Harp.HARP_KEYS[choice.named]} harp"
        }
        var html = "<p class=\"facts\" id=\"facts\">${bits.joinToString(" · ")}</p>\n"
        if (choice.why == "record" && choice.fits.size > 1) {
            val best = choice.fits[0]
            val runner = choice.fits[1]
            html += "<p class=\"why\">${PyFormat.percent(best.share, 0)} of the sung notes fall on the sheet's chords on " +
                "${a(Harp.HARP_KEYS[best.harp])}, ${PyFormat.percent(runner.share, 0)} on ${a(Harp.HARP_KEYS[runner.harp])}</p>\n"
        }
        return html
    }

    /** _read_as: how the tab was read (its symbols as it writes them, and whether its own legend said so or caracole
     * guessed, how surely), and what harptabs.com says of the tab ([facts]: its difficulty, its views, its rating, each
     * only where it is a value Python's isinstance takes). */
    fun readAs(reading: Reading, facts: JsonObject): String {
        val said = ArrayList<String>()
        val difficulty = facts["difficulty"]
        if (difficulty is JsonPrimitive && difficulty.isString && PyText.strip(difficulty.content).isNotEmpty()) {
            said += PyText.escape(PyText.strip(difficulty.content))
        }
        val views = pyInt(facts["views"])
        if (views != null && views.signum() > 0) {
            said += when {
                views < THOUSAND -> "$views views"
                views < BigInteger.valueOf(999_500) -> PyFormat.fixed(views.toDouble() / 1000, 0) + "k views"
                else -> PyFormat.fixed(pyFloat(views) / 1e6, 1) + "M views"
            }
        }
        val rating = facts["rating"]
        val ratingInt = pyInt(rating)
        if (ratingInt != null) {
            if (ratingInt.signum() > 0) said += PyFormat.fixed(pyFloat(ratingInt), 1) + "★"  // int.__format__'s float()
        } else {
            val number = pyFloatOf(rating)
            if (number != null && number > 0) said += PyFormat.fixed(number, 1) + "★"
        }
        val factsSaid = if (said.isNotEmpty()) " · " + said.joinToString(" · ") else ""
        if (reading.standard) {  // harptabs.com's own key, guessed: its familiar legend says enough (the owner's choice)
            return "<p class=\"legend\" aria-label=\"How to read the holes\">" +
                "<span class=\"h\"><span class=\"b\">4</span></span> blow " +
                "<span class=\"h\"><span class=\"d\"><span class=\"sg\">−</span>4</span></span> draw " +
                "<span class=\"h\"><span class=\"d\"><span class=\"sg\">−</span>3<span class=\"bd\">′</span></span></span> bent " +
                "<span class=\"h\">(<span class=\"b\">4</span> <span class=\"b\">5</span>)</span> together" +
                factsSaid + "</p>\n"
        }
        val symbols = reading.symbols().joinToString(" · ") { (text, word) ->
            "<code class=\"sy\">${PyText.escape(text)}</code> ${PyText.escape(word)}"
        }
        val source = SOURCE[reading.source] ?: "guessed (${PyFormat.fixed(reading.q, 2)})"
        // served, harptab.js makes its source a link to caracole serve's page that changes it
        return "<p class=\"legend\" aria-label=\"How the tab was read\">Read as: $symbols, " +
            "<span class=\"src\" id=\"reading-src\">${PyText.escape(source)}</span>" + factsSaid + "</p>\n"
    }

    /** _pinned: the notation [pin] names for the tab [text], or null (no pin, a legend the tab hasn't got, or a pin
     * overrides.toml would refuse: read as caracole guesses). */
    private fun pinned(pin: JsonElement?, text: String): Notation? {
        if (pin == null || pin is JsonNull) return null
        return try {
            HarpTabs.pinned(pin, text)
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    // --- the tab -------------------------------------------------------------------------------------------------

    private fun tabHtml(tab: Tab, data: Data): String {
        val out = StringBuilder("<article class=\"sheet harp-tab\" id=\"sheet\">\n").append(notesHtml(tab.notes))
        tab.sections.forEachIndexed { n, s -> out.append(sectionHtml(n, s, data)) }
        return out.append("</article>\n").toString()
    }

    private fun rawHtml(text: String): String =
        "<article class=\"sheet harp-tab raw\" id=\"sheet\">\n<pre class=\"tab\">${PyText.escape(rstrip(text))}</pre>\n</article>\n"

    /** _notes_html: the tabber's notes before the first row, as sheet.html shows a tab's: folded after two lines. */
    private fun notesHtml(notes: List<String>): String {
        val lines = notes.filter { PyText.strip(it).isNotEmpty() }
        if (lines.isEmpty()) return ""
        val body = lines.joinToString("\n") { "<p class=\"l\">${PyText.escape(it)}</p>" }
        if (lines.size <= 2) return "<div class=\"pre\">\n$body\n</div>\n"
        val peek = lines.take(2).joinToString("<br>") { PyText.escape(it) }
        return "<details class=\"pre\">\n<summary><span class=\"peek\">$peek</span><span class=\"named\">Notes</span>" +
            "<span class=\"more\">More</span><span class=\"less\">Less</span></summary>\n" +
            "<div class=\"pre-body\">\n$body\n</div>\n</details>\n"
    }

    private fun sectionHtml(n: Int, section: TabSection, data: Data): String {
        val out = ArrayList<String>()
        out += "<section class=\"sec${if (section.chorus) " chorus" else ""}\" id=\"sec-$n\">"
        if (!section.label.isNullOrEmpty()) out += "<h2 class=\"lbl\">${PyText.escape(section.label)}</h2>"
        for (item in section.items) {
            when (item) {
                is Row -> out += if (item.trusted) rowHtml(item, data) else writtenHtml(item)
                is Legend -> out += "<div class=\"tab-legend\"><p class=\"lgh\">The tab's legend</p>" +
                    item.lines.joinToString("") { "<p class=\"l\">${PyText.escape(PyText.strip(it))}</p>" } + "</div>"
                is Words -> item.lines.filter { PyText.strip(it).isNotEmpty() }.forEach {
                    out += "<p class=\"l words\">${PyText.escape(PyText.strip(it))}</p>"
                }
                is Prose -> out += "<p class=\"note\">${PyText.escape(PyText.strip(item.text))}</p>"
                Gap -> out += "<div class=\"gap\"></div>"
            }
        }
        out += "</section>\n"
        return out.joinToString("\n")
    }

    /** _written_html: a row read with low confidence: its line as written, and its words under it (above it, where
     * the tab writes them so), in the tab's own columns. */
    private fun writtenHtml(row: Row): String {
        val words = if (row.lyric != null) listOf(rstrip(row.lyric)) else emptyList()
        val lines = if (row.above) words + rstrip(row.text) else listOf(rstrip(row.text)) + words
        return "<pre class=\"tab asw\">${PyText.escape(lines.joinToString("\n"))}</pre>"
    }

    private fun rowHtml(row: Row, data: Data): String {
        val groups = data.groups!!
        val first = groups.size
        val line = if (row.lyric == null) {
            val lead = if (!row.label.isNullOrEmpty()) "<i class=\"m\">${PyText.escape(row.label)}</i> " else ""
            "<p class=\"l holes\">$lead${cells(row.groups, data, " ")}"
        } else {
            val out = StringBuilder()
            for ((partGroups, text) in row.parts) {
                val words = SheetPage.words(text).toMutableList()
                if (partGroups.isNotEmpty()) {
                    val top = "<span class=\"hg\">" + cells(partGroups, data, "") + "</span>"
                    val lead = if (words.isNotEmpty()) PyText.escape(words.removeAt(0)) else ""
                    out.append("<span class=\"s\">$top<span class=\"y\">$lead</span></span>")
                }
                words.forEach { out.append("<span class=\"w\">${PyText.escape(it)}</span>") }
            }
            "<p class=\"l hl\">$out"
        }
        val rows = data.rows!!
        rows.add(JsonArray((first until groups.size).map(::JsonPrimitive)))
        return "$line<button type=\"button\" class=\"rp\" data-row=\"${rows.size - 1}\" " +
            "aria-label=\"Play this line\" aria-pressed=\"false\">$PLAY_ICON</button></p>"
    }

    /** _cells: a row's groups in their order, [space] between two, none between two run together; in a row played
     * alone, each a cell with its hold and its tie, which a line never parts. */
    private fun cells(groups: List<Group>, data: Data, space: String): String {
        val out = StringBuilder()
        groups.forEachIndexed { n, group ->
            if (n > 0 && !groups[n - 1].join) out.append(space)
            val cell = groupHtml(group, data) + (if (group.join && n + 1 < groups.size) JOIN else "")
            out.append(if (space.isNotEmpty()) "<span class=\"cell\">$cell</span>" else cell)
        }
        return out.toString()
    }

    /** _group_html: a group of holes as the page shows it before its script runs; `data-i`, its place in the data's
     * `groups`. What the notation couldn't read is its text, as written; the tabber's words in the row are text. */
    private fun groupHtml(group: Group, data: Data): String {
        if (group.kind == "unread") return "<span class=\"u\">${PyText.escape(group.text)}</span>"
        if (group.kind == "words") return "<span class=\"tw\">${PyText.escape(group.text)}</span>"
        val groups = data.groups!!
        val i = groups.size
        val more = LinkedHashMap<String, JsonElement>()
        if (group.effects.isNotEmpty()) more["fx"] = JsonArray(group.effects.map(::JsonPrimitive))
        if (group.join) more["join"] = JsonPrimitive(1)
        val holes = JsonArray(group.holes.map { h ->
            JsonArray(listOf(JsonPrimitive(h.hole), JsonPrimitive(h.breath.substring(0, 1)), JsonPrimitive(h.bend),
                             JsonPrimitive(if (h.over) 1 else 0)))
        })
        groups.add(JsonArray(listOf(JsonPrimitive(group.kind), holes) + (if (more.isNotEmpty()) listOf(JsonObject(more)) else emptyList())))
        val (a, b) = BRACKETS.getValue(group.kind)
        val inner = group.holes.joinToString(" ") { holeHtml(it) }
        val effects = group.effects.joinToString("") { "<small class=\"fx\">${PyText.escape(it)}</small>" }
        val held = if (group.hold) "<span class=\"hold\" aria-hidden=\"true\">…</span>" else ""
        return "<b class=\"h\" data-i=\"$i\" tabindex=\"0\" role=\"button\" aria-label=\"${PyText.escape(said(group))}\">" +
            "$a$inner$b$effects</b>$held"
    }

    private fun holeHtml(hole: Hole): String {
        val sign = if (hole.breath == "draw") "<span class=\"sg\">−</span>" else ""
        val bend = if (hole.bend != 0) "<span class=\"bd\">${"′".repeat(hole.bend)}</span>" else ""
        val over = if (hole.over) "<span class=\"bd\">°</span>" else ""
        return "<span class=\"${hole.breath.substring(0, 1)}\">$sign${hole.hole}$bend$over</span>"
    }

    /** _said: a group in words, for a screen reader: "draw 3 bent 1", "blow 4 and blow 5", "draw 1, wah". */
    private fun said(group: Group): String =
        group.holes.joinToString(" and ") { h ->
            "${h.breath} ${h.hole}" + (if (h.bend != 0) " bent ${h.bend}" else "") + (if (h.over) " overblown" else "")
        } + group.effects.joinToString("") { ", $it" }

    // --- the foot ------------------------------------------------------------------------------------------------

    /** _footer: the foot: the tab's text beside the page, where it came from (its page on harptabs.com, else the
     * site), and a word on keeping the page private; with [change] (a tab read by harptabs.com's own key, or one shown
     * as written), a link that changes how it is read, which harptab.js shows served alone. */
    fun footer(tabFile: String, url: String?, placed: Boolean, change: Boolean = false): String {
        val site = if (url != null && url.startsWith(SITE)) url else SITE
        return "<footer class=\"foot\">\n" +
            "<p><a class=\"pdf\" href=\"${PyText.escape(PyUrl.quote(tabFile))}\">The tab as text</a></p>\n" +
            "<p>Tab from <a href=\"${PyText.escape(site)}\">harptabs.com</a>, as its tabber wrote it" +
            (if (placed) "; caracole placed each hole over its syllable.</p>\n" else ".</p>\n") +
            "<p>Keep this page private: the lyrics and the tab are other people's work.</p>\n" +
            (if (change) "<p class=\"reading\" id=\"reading-foot\" hidden><a href=\"#\">Change how it's read</a></p>\n" else "") +
            "</footer>\n"
    }

    // --- Python's values ----------------------------------------------------------------------------------------

    private val THOUSAND = BigInteger.valueOf(1000)

    /** A JSON value Python's `isinstance(value, int) and not isinstance(value, bool)` holds: an integer; else null. */
    private fun pyInt(value: JsonElement?): BigInteger? {
        val p = value as? JsonPrimitive ?: return null
        if (p is JsonNull || p.isString) return null
        val c = p.content
        val digits = c.removePrefix("-")
        return if (digits.isNotEmpty() && digits.all { it in '0'..'9' }) BigInteger(c) else null
    }

    private fun isBool(value: JsonElement?): Boolean =
        value is JsonPrimitive && !value.isString && (value.content == "true" || value.content == "false")

    /** A JSON number that is no integer, as Python's json reads it (a float, NaN and the infinities among them). */
    private fun pyFloatOf(value: JsonElement?): Double? {
        val p = value as? JsonPrimitive ?: return null
        if (p is JsonNull || p.isString || isBool(p)) return null
        return when (p.content) {
            "NaN" -> Double.NaN
            "Infinity" -> Double.POSITIVE_INFINITY
            "-Infinity" -> Double.NEGATIVE_INFINITY
            else -> p.content.toDoubleOrNull()
        }
    }

    /** float(n) of a Python int: the nearest double, or Python's OverflowError past the largest. */
    private fun pyFloat(n: BigInteger): Double {
        val d = n.toDouble()  // correctly rounded, as Python's
        if (d.isInfinite()) throw ArithmeticException("int too large to convert to float")
        return d
    }

    /** str.rstrip(): Python's whitespace off its end. */
    private fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyText.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }

    private fun namesJson(names: Map<String, Map<String, String>>): JsonObject =
        JsonObject(names.mapValuesTo(LinkedHashMap()) { (_, table) ->
            JsonObject(table.mapValuesTo(LinkedHashMap()) { (_, v) -> JsonPrimitive(v) })
        })
}
