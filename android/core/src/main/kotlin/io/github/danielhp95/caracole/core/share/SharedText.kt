package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl

/**
 * What a share says of its song, before read_names reads it: the music app that sent it ([app], its name as a page
 * says it; null for one caracole doesn't know), the text that names the song ([said]: "Queen - Bohemian Rhapsody";
 * null when nothing shared names one, a link alone), and the first link shared ([link]; null for none).
 */
data class Shared(val app: String?, val said: String?, val link: String?)

/**
 * A song shared to the phone from a music app (the app's share target, text alone), read with no request to any
 * site or service: the one place that knows each app's words around a song's names, before song_names.py's
 * `read_names` (SongNames.readNames, the one parser of a free text) reads the names themselves.
 *
 * [read] takes what Android's share carried, EXTRA_TEXT, EXTRA_SUBJECT and EXTRA_TITLE, and the sender's package:
 *
 * 1. **The app**: by its package ([APPS]), else by its link's host, else by the words a shape names it in.
 * 2. **The link**: the first `http(s)://` address in the text, then the subject, then the title; links are taken out
 *    of every text before the rest is read, each line's spaces folded, the marks a link leaves at its ends cut.
 * 3. **An app's words** ([SHAPES], the most particular first), tried on the text, then the subject, then the title.
 *    A shape that holds the artist and the title apart ("I used Shazam to discover {title} by {artist}.") gives
 *    "Artist - Title", the form read_names' first rule reads whoever the artist is, the title as the app wrote it
 *    ("Bohemian Rhapsody - Remastered 2011", whose version words read_names' cleaning drops). A " by " is the last
 *    one, a title's own staying in it ("Stand by Me by Ben E. King"); an uploader's title on SoundCloud that names
 *    its artist itself ("KAKE - BADADONK") is the song's whole name ([App.uploads]). A shape of one text alone
 *    (YouTube's "Watch "{title}" on YouTube") gives that text.
 * 4. **Else the text as written**: the first of them with a word of a name once its links are gone, less an app's
 *    name at its end ("… | Spotify", "… on #Deezer") or alone, for read_names to read as it reads any text; never
 *    for an app whose texts name a song only in its own words ([App.shapesOnly]: a Subsonic client's greeting).
 *
 * A share whose texts hold a link alone names no song here ([Shared.said] null): this reads no link. A link of Apple
 * Music's, Spotify's, TIDAL's, YouTube's or YouTube Music's is then read by asking its service once ([ShareLinks],
 * [ShareAsk]: the owner's choice of 2026-11-10); any other's stays a link alone.
 *
 * tests/fixtures/share/shares.jsonl holds what each app sends, where it was found, and what this reads of it.
 */
object SharedText {
    /**
     * A music app: its [name] as the page says it, its Android [packages], the [hosts] of the links it shares;
     * [uploads], its titles an uploader's, which may name the artist themselves; [shapesOnly], its texts name a song
     * only in a shape's words (else a greeting, or a link).
     */
    data class App(val name: String, val packages: Set<String>, val hosts: Set<String>, val uploads: Boolean = false,
                   val shapesOnly: Boolean = false)

    val APPS: List<App> = listOf(
        App("Spotify", setOf("com.spotify.music", "com.spotify.lite"),
            setOf("open.spotify.com", "play.spotify.com", "spotify.link", "spotify.app.link")),
        App("Deezer", setOf("deezer.android.app"),
            setOf("deezer.com", "www.deezer.com", "deezer.page.link", "link.deezer.com", "dzr.page.link")),
        App("Apple Music", setOf("com.apple.android.music"), setOf("music.apple.com", "itunes.apple.com")),
        App("TIDAL", setOf("com.aspiro.tidal"), setOf("tidal.com", "www.tidal.com", "listen.tidal.com", "tidal.link")),
        App("YouTube Music", setOf("com.google.android.apps.youtube.music"), setOf("music.youtube.com")),
        App("YouTube", setOf("com.google.android.youtube"),
            setOf("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")),
        App("Shazam", setOf("com.shazam.android"), setOf("shazam.com", "www.shazam.com", "shz.am")),
        App("SoundHound", setOf("com.melodis.midomiMusicIdentifier.freemium"), setOf("soundhound.com", "www.soundhound.com")),
        App("Musixmatch", setOf("com.musixmatch.android.lyrify"), setOf("musixmatch.com", "www.musixmatch.com")),
        App("SoundCloud", setOf("com.soundcloud.android"),
            setOf("soundcloud.com", "m.soundcloud.com", "on.soundcloud.com"), uploads = true),
        App("Audile", setOf("com.mrsep.musicrecognizer"), emptySet()),
        App("Navic", setOf("paige.navic"), emptySet(), shapesOnly = true),
        App("Ultrasonic", setOf("org.moire.ultrasonic"), emptySet(), shapesOnly = true),
        App("DSub", setOf("github.daneren2005.dsub"), emptySet(), shapesOnly = true),
    )

    private const val TEXT = 0
    private const val SUBJECT = 1
    private const val TITLE = 2

    /**
     * One app's words around a song's names: [pattern], a Python pattern, with `(?P<artist>…)` and `(?P<title>…)`, or
     * `(?P<said>…)` for a text that is the song's whole name, and `(?P<app>…)` for the app it names; matched whole
     * against a text with its links taken out (its lines joined by a space; [lines]: as they are, and found anywhere
     * in it), in the [fields] it names, of [only] that app's shares alone when it names one. [app]: whose words.
     * [nameless]: words that name no song (an app's greeting), which leave their text out of the rest.
     */
    private class Shape(val app: String?, pattern: String, val fields: Set<Int> = setOf(TEXT, SUBJECT, TITLE),
                        val lines: Boolean = false, val only: String? = null, val nameless: Boolean = false) {
        val regex: Regex = PyRegex.compile(pattern)

        fun match(text: String): MatchResult? = if (lines) regex.find(text) else regex.matchEntire(text)
    }

    /** Every app's name, for a pattern: the longest first ("YouTube Music" before "YouTube"). */
    private val NAMES = APPS.map { it.name }.sortedByDescending { it.length }.joinToString("|") { escape(it) }

    /** Each app's words around a song's names, the most particular first. */
    private val SHAPES: List<Shape> = listOf(
        // Ultrasonic, a song shared as text alone: its greeting, then "Title: …", "Artist: …", "Album: …", each label
        // in the phone's language (ShareHandler.kt; res/values*/strings.xml's common.title and common.artist).
        Shape("Ultrasonic", "(?m)^(?:Title|Título|Titel|Titre|Tytuł|Заголовок|タイトル|标题): (?P<title>.+)\\n" +
                  "(?:Artist|Artista|Künstler|Artiste|Artiest|Wykonawca|Артист|アーティスト|艺术家): (?P<artist>.+)$",
              fields = setOf(TEXT), lines = true),
        // Audile: "{title} - {artist}", the album and the year after them only when ticked, the lyrics and the
        // services' links under a blank line (ResultNotificationHelper.kt, ShareBottomSheet.kt).
        Shape("Audile", "(?s)^(?P<title>[^\\n]+) - (?P<artist>[^\\n]+?)(?: \\((?:19|20)\\d\\d\\))?(?:\\n.*)?$",
              fields = setOf(TEXT), lines = true, only = "Audile"),
        // Deezer: "I've found a song for you... {title} by {artist} 🔥 Listen now on #Deezer {link}".
        Shape("Deezer", "(?i)^I[’']ve found a song for you(?:\\.\\.\\.|…)?\\s*(?P<title>.+)\\s+by\\s+" +
                  "(?P<artist>.+?)\\s*(?:\\U0001F525\\s*)?Listen now on #?Deezer\\W*$"),
        // Shazam: "I used Shazam to discover {title} by {artist}. {link}" (once "I just used …").
        Shape("Shazam", "(?i)^I (?:just )?used Shazam to discover (?P<title>.+)\\s+by\\s+(?P<artist>.+?)\\.?$"),
        // SoundHound: "I found {title} by {artist} with SoundHound and thought you'd enjoy it too! {link}".
        Shape("SoundHound", "(?i)^I found (?P<title>.+)\\s+by\\s+(?P<artist>.+?)\\s+with SoundHound\\b.*$"),
        // Musixmatch: "I got the #lyrics for "{title}" by {artist} on Musixmatch {link}".
        Shape("Musixmatch", "(?i)^I got the #?lyrics for [\"“](?P<title>.+)[\"”]\\s+by\\s+(?P<artist>.+?)\\s+on " +
                  "#?Musixmatch\\W*$"),
        // YouTube's subject: "Watch "{the video's title}" on YouTube".
        Shape("YouTube", "^Watch [\"“](?P<said>.+)[\"”] on YouTube$", fields = setOf(SUBJECT, TITLE)),
        // Spotify's page title: "{title} - song by {artist} | Spotify" ("song and lyrics by" too).
        Shape("Spotify", "(?i)^(?P<title>.+) - song(?: and lyrics)? by (?P<artist>.+?) \\| Spotify$"),
        // "Listen to {title} by {artist} on #SoundCloud" (SoundCloud's), and as any app may word it.
        Shape(null, "(?i)^(?:Listen to|Check out) (?P<title>.+)\\s+by\\s+(?P<artist>.+?)\\s+on #?(?P<app>$NAMES)\\W*$"),
        // "{title} by {artist} on {app}", as TIDAL's and Apple Music's pages title a song.
        Shape(null, "(?i)^(?P<title>.+)\\s+by\\s+(?P<artist>.+?)\\s+on #?(?P<app>$NAMES)\\W*$"),
        // Shazam's subject: "{title} - {artist}", of Shazam's shares alone (its text says it first).
        Shape("Shazam", "^(?P<title>.+) - (?P<artist>.+)$", fields = setOf(SUBJECT), only = "Shazam"),
        // SoundHound's subject, which names no song.
        Shape("SoundHound", "(?i)^Check out what I just discovered on SoundHound!?$", nameless = true),
    )

    /** An app whose texts name a song only in its own words, named in a text (Ultrasonic's greeting, "Check out this
     * music I shared from Ultrasonic", in any language). */
    private val MENTIONED = PyRegex.compile(
        "(?i)\\b(?:" + APPS.filter { it.shapesOnly }.joinToString("|") { escape(it.name) } + ")\\b",
    )

    /** An address: `http(s)://` and what follows to a space; the marks a sentence ends with are no part of it. */
    private val LINK = PyRegex.compile("""(?i)\bhttps?://\S+""")
    private const val LINK_END = ".,;:!?)]}>»”’\"'"

    /** What links leave at a text's ends: spaces, separators, a colon, a dash. */
    private const val ENDS = " \t:;,-–—|·•"

    private const val QUOTES = "\"'“”‘’«»「」『』"

    /** A mark that splits "Artist - Title" (song_names.py's first rule's), in an uploader's title. */
    private val MARK = PyRegex.compile("""\s(?:-|–|—)\s""")

    /** What the share names: [read]'s steps. */
    fun read(text: String?, subject: String?, title: String?, sender: String?): Shared {
        val fields = listOf(text, subject, title).map { Py.strip(it.orEmpty()) }
        val link = fields.firstNotNullOfOrNull { f -> LINK.find(f)?.value?.trimEnd(*LINK_END.toCharArray())?.ifEmpty { null } }
        var app = byPackage(sender) ?: link?.let { byHost(it) }
        val bare = fields.map { unlinked(it) }.toMutableList()
        for ((field, lines) in bare.withIndex()) {
            if (lines.isEmpty()) continue
            val flat = lines.replace('\n', ' ')
            for (shape in SHAPES) {
                if (field !in shape.fields || (shape.only != null && shape.only != app)) continue
                val m = shape.match(if (shape.lines) lines else flat) ?: continue
                if (shape.nameless) {
                    bare[field] = ""
                    if (app == null) app = shape.app
                    break
                }
                val said = said(m, app) ?: continue
                if (app == null) app = shape.app ?: m.groups["app"]?.value?.let { named(it) }
                return Shared(app, said, link)
            }
        }
        if (app == null) app = bare.firstNotNullOfOrNull { b -> MENTIONED.find(b)?.value?.let { named(it) } }
        if (APPS.firstOrNull { it.name == app }?.shapesOnly == true) return Shared(app, null, link)
        val said = bare.map { withoutAppName(it.replace('\n', ' ')) }.firstOrNull { Normalize.nameWords(it).isNotEmpty() }
        return Shared(app, said, link)
    }

    /** What a shape's match names: its text, else "Artist - Title" (an uploader's title naming both, alone); null
     * for a part with no word of a name. */
    private fun said(m: MatchResult, app: String?): String? {
        val whole = runCatching { m.groups["said"] }.getOrNull()?.value
        if (whole != null) return part(whole).takeIf { Normalize.nameWords(it).isNotEmpty() }
        val artist = part(m.groups["artist"]?.value)
        val songTitle = part(m.groups["title"]?.value)
        if (Normalize.nameWords(artist).isEmpty() || Normalize.nameWords(songTitle).isEmpty()) return null
        val sender = APPS.firstOrNull { it.name == (app ?: runCatching { m.groups["app"] }.getOrNull()?.value?.let(::named)) }
        if (sender?.uploads == true && MARK.containsMatchIn(songTitle)) return songTitle
        return "$artist - $songTitle"
    }

    /** The app of [sender], a package; null for none caracole knows. */
    fun byPackage(sender: String?): String? = sender?.let { p -> APPS.firstOrNull { p in it.packages }?.name }

    /** The app whose links are at [link]'s host; null for none caracole knows. */
    fun byHost(link: String): String? {
        val host = try {
            PyUnicode.lower(PyUrl.urlsplit(link).netloc.substringAfterLast('@').substringBefore(':'))
        } catch (e: PyUrl.Invalid) {
            return null
        }
        return APPS.firstOrNull { host in it.hosts }?.name
    }

    /** The app a shape's words name, as [APPS] writes it. */
    private fun named(name: String): String? =
        APPS.firstOrNull { PyUnicode.casefold(it.name) == PyUnicode.casefold(name) }?.name

    /** [text] with its links taken out, each line's spaces folded and what they leave at its ends cut, the lines
     * with nothing left dropped. */
    private fun unlinked(text: String): String = LINK.replace(text, " ").split('\n')
        .map { cut(Py.split(it).joinToString(" ")) }.filter { it.isNotEmpty() }.joinToString("\n")

    /** A shape's part: its spaces folded, its ends cut, its quotes gone. */
    private fun part(text: String?): String {
        var t = cut(Py.split(text.orEmpty()).joinToString(" "))
        while (t.length > 1 && t[0] in QUOTES && t[t.length - 1] in QUOTES) t = cut(t.substring(1, t.length - 1))
        return t
    }

    private fun cut(text: String): String = text.trim(*ENDS.toCharArray())

    /** [text] less an app's name at its end, after a mark or "on" ("… | Spotify", "… on #Deezer"), or alone. */
    private fun withoutAppName(text: String): String {
        val m = APP_AT_END.find(text) ?: return text
        return cut(text.substring(0, m.range.first))
    }

    private val APP_AT_END: Regex = PyRegex.compile(
        "(?i)(?:^|\\s+(?:on|en|sur|auf|su|em|op|in|\\||·|•|-|–|—)\\s+|\\s*[|·•]\\s*)#?(?:$NAMES)\\s*[.!]?$",
    )

    /** [s] with every mark Python's re reads as one escaped (a space is itself). */
    private fun escape(s: String): String = buildString {
        for (c in s) {
            if (c in 'a'..'z' || c in 'A'..'Z' || c in '0'..'9' || c == '_' || c == ' ') append(c) else append('\\').append(c)
        }
    }
}
