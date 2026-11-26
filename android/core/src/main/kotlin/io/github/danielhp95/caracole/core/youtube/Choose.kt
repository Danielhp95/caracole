package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs

/**
 * youtube.choose: the song's video among a search's, or none, by the data's `choose` member (its patterns, its words,
 * its lengths; the key, `key`, in its words). Function for function youtube.py's (`_Names`, `_Squeezed`, `_parts`,
 * `_official`, `_closeness`, `_ranked`), and:
 *
 * - a text's positions, lengths and slices where youtube.py counts them, in code points ([Squeezed] holds its text
 *   as code points: a letter past the BMP, 𠮷, is one);
 * - names through core.keys.Normalize (normalize.py's fold, slug_key, compact, name_forms, simplified, clean_title,
 *   title_variant), patterns through PyRegex and PyRe, `str.strip` and `str.isdigit` as Python's;
 * - a song's artists' slugs in name_forms' order where youtube.py iterates a set (`artist_slugs`, which only
 *   `_stripped_to_title` reads in an order: the vectors are the same under every PYTHONHASHSEED);
 * - the least key of (tier, -title, closeness, -official, rank), the search's order breaking every tie.
 */
object Choose {
    /** The song's names as choose reads them: songs.py's artist, title and artists. */
    data class Song(val artist: String, val title: String, val artists: List<String> = emptyList()) {
        companion object {
            fun of(row: SongRow): Song = Song(row.artist, row.title, row.artists)
        }
    }

    /** A video that fits, with the parts of its key: [tier], [title], [close], [official], [rank]. */
    data class Ranked(val video: Video, val tier: Int, val title: Int, val close: Int, val official: Int, val rank: Int)

    /** choose(song, videos, expected, skip=): the least [ranked] video, or none. */
    fun choose(song: Song, videos: List<Video>, expected: Double?, skip: Set<String> = emptySet()): Video? =
        ranked(song, videos, expected, skip).minWithOrNull(KEY)?.video

    fun choose(song: SongRow, videos: List<Video>, expected: Double?, skip: Set<String> = emptySet()): Video? =
        choose(Song.of(song), videos, expected, skip)

    private val KEY: Comparator<Ranked> =
        compareBy<Ranked>({ it.tier }, { -it.title }, { it.close }, { -it.official }, { it.rank })

    /** youtube._ranked: the videos that fit, in the search's order, each with its key. */
    fun ranked(song: Song, videos: List<Video>, expected: Double?, skip: Set<String> = emptySet()): List<Ranked> {
        val names = Names(song)
        val out = ArrayList<Ranked>()
        for ((rank, video) in videos.withIndex()) {
            if (video.id in skip || video.live || video.short) continue
            val close = closeness(video, expected)
            val title = if (close != null) names.titleIn(video.title) else 0
            if (title == 0 || close == null) continue
            if (!(names.channelIsArtist(video.channel) || names.artistIn(video.title))) continue
            var tier = if (names.unwanted(video.title, video.channel)) 1 else 0
            if (names.variant != null && PyRe.search(rules.variant(names.variant), Normalize.fold(video.title)) == null) {
                tier = maxOf(tier, 1)
            }
            out += Ranked(video, tier, title, close, official(names, video), rank)
        }
        return out
    }

    /** _closeness: 0 to 3, closest first, or none when the length doesn't fit. */
    private fun closeness(video: Video, expected: Double?): Int? {
        val duration = video.duration ?: return 3
        if (expected == null) return if (rules.shortest <= duration && duration <= rules.longest) 0 else null
        val off = abs(duration - expected)
        if (off > rules.tolerance) return null
        return if (off <= rules.synced) 0 else if (off <= rules.close) 1 else 2
    }

    /** _official: the artist's Topic channel, official audio, the artist's own channel or an official video, or none. */
    private fun official(names: Names, video: Video): Int {
        val topic = PyRe.match(rules.topic, Py.strip(video.channel))
        if (topic != null && names.channelIsArtist(video.channel)) return 3
        val folded = Normalize.fold(video.title)
        val own = names.channelIsArtist(video.channel)
        if (PyRe.search(rules.officialAudio, folded) != null && (own || names.artistIn(video.title))) return 2
        if (own || PyRe.search(rules.officialVideo, folded) != null) return 1
        return 0
    }

    // --- the data -----------------------------------------------------------------------------------------------

    private class Rules(private val data: YouTubeData) {
        private val json: JsonObject = data.choose
        private val patterns = json.getValue("patterns").jsonObject
        private fun pattern(name: String): Regex = YouTubeData.compiled(patterns.getValue(name).jsonObject)
        private fun words(name: String): Set<String> = json.getValue(name).jsonArray.map { it.jsonPrimitive.content }.toSet()
        private fun number(name: String): Double = data.number(name, json)

        val parts = pattern("parts")
        val quoted = pattern("quoted")
        val unwanted = pattern("unwanted")
        val karaokeChannel = pattern("karaoke_channel")
        val topic = pattern("topic")
        val channelSuffix = pattern("channel_suffix")
        val officialAudio = pattern("official_audio")
        val officialVideo = pattern("official_video")
        val cjkLetter = pattern("cjk_letter")
        val scriptRun = pattern("script_run")
        val decoration = words("decoration")
        val cjkDecoration = words("cjk_decoration")
        val ownChannel: List<String> = json.getValue("own_channel").jsonArray.map { it.jsonPrimitive.content }
        val cjkWidth: String = json.getValue("cjk_width").jsonPrimitive.content
        val tolerance = number("tolerance_s")
        val synced = number("synced_s")
        val close = number("close_s")
        val shortest = number("shortest_s")
        val longest = number("longest_s")
        val exact = json.getValue("exact").jsonPrimitive.int
        val alone = json.getValue("alone").jsonPrimitive.int
        private val variantTemplate = json.getValue("variant").jsonPrimitive.content
        private val variants = HashMap<String, Regex>()

        /** `_VARIANT` filled with [variant] (title_variant's "live" or "acoustic"), compiled once a variant. */
        fun variant(variant: String): Regex = synchronized(variants) {
            variants.getOrPut(variant) { PyRegex.compile(YouTubeData.fillAll(variantTemplate, mapOf("variant" to variant))) }
        }

        /** _CJK_LETTER.match of one code point. */
        fun cjk(cp: Int): Boolean = PyRe.match(cjkLetter, String(Character.toChars(cp))) != null
    }

    private val rules: Rules by lazy { Rules(YouTubeData.read()) }

    private const val SPACE = " "

    // --- names ----------------------------------------------------------------------------------------------------

    private fun compactForms(name: String): Set<String> =
        Normalize.nameForms(name).filter { it.isNotEmpty() }.mapTo(LinkedHashSet()) { Normalize.compact(it) }

    /** _parts: the title whole, each part of it, and each quoted run in it, stripped, none empty. */
    private fun parts(text: String): List<String> {
        val found = ArrayList<String?>()
        found += text
        found += PyRe.split(rules.parts, text)
        for (m in PyRe.finditer(rules.quoted, text)) found += m.groups[1]?.value?.takeIf { it.isNotEmpty() } ?: m.groups[2]?.value
        return found.filter { !it.isNullOrEmpty() && Py.strip(it).isNotEmpty() }.map { Py.strip(it!!) }
    }

    /** _cjk: a form holding a letter of East Asian width W. */
    private fun cjk(form: String): Boolean = form.codePoints().anyMatch { PyUnicode.eastAsianWidth(it) == rules.cjkWidth }

    private fun cps(s: String): IntArray = Py.codePoints(s)

    /** text.find(form, from), in code points. */
    private fun find(text: IntArray, form: IntArray, from: Int): Int {
        var i = maxOf(from, 0)
        while (i + form.size <= text.size) {
            if (startsWith(text, form, i)) return i
            i++
        }
        return -1
    }

    private fun startsWith(text: IntArray, w: IntArray, at: Int): Boolean {
        if (at > text.size || at + w.size > text.size) return false
        for (j in w.indices) if (text[at + j] != w[j]) return false
        return true
    }

    /** _Squeezed: a title's words as slug_key reads them, each run of one script apart, run together, in code points. */
    private class Squeezed(text: String) {
        val text: IntArray
        val ends = LinkedHashMap<Int, Int>() // each word's start, and its end
        val endSet: Set<Int>

        init {
            val words = Normalize.slugKey(text).split("-").filter { it.isNotEmpty() }
                .flatMap { token -> PyRe.findall(rules.scriptRun, token) }
            val all = ArrayList<Int>()
            var at = 0
            for (word in words) {
                val w = Py.codePoints(word)
                ends[at] = at + w.size
                at += w.size
                all.addAll(w.toList())
            }
            this.text = all.toIntArray()
            endSet = ends.values.toSet()
        }

        /** Where the words holding text[start:end] start and end. */
        fun wordAround(start: Int, end: Int): Pair<Int, Int> =
            ends.keys.filter { it <= start }.max() to ends.values.filter { it >= end }.min()
    }

    private class Names(song: Song) {
        val artists: Set<String>
        val artistSlugs: List<String>
        val titles: Set<String>
        val cjkTitles: List<String>
        val cjkWords: Set<String>
        val latinArtists: Set<String>
        val whole: String
        val variant: String? = Normalize.titleVariant(song.title)

        init {
            val named = (song.artists.ifEmpty { listOf(song.artist) }).filter { it.isNotEmpty() && Py.strip(it).isNotEmpty() }
                .ifEmpty { listOf(song.artist) }
            artists = named.flatMapTo(LinkedHashSet()) { compactForms(it) }
            artistSlugs = named.flatMap { a -> Normalize.nameForms(a).filter { it.isNotEmpty() } }.distinct()
            titles = compactForms(Normalize.cleanTitle(song.title))
            cjkTitles = titles.filter { PyRe.search(rules.cjkLetter, it) != null }
            cjkWords = artists.filterTo(LinkedHashSet()) { PyRe.search(rules.cjkLetter, it) != null } + rules.cjkDecoration
            latinArtists = artists - cjkWords
            whole = Normalize.fold(listOf(song.title, *named.toTypedArray()).joinToString(SPACE))
        }

        private val cjkWordCps: List<IntArray> = cjkWords.map { Py.codePoints(it) }
        private val latinArtistCps: List<IntArray> = latinArtists.map { Py.codePoints(it) }

        /** Whether a part of [text] is one of [forms], or, for one in Chinese, Japanese or Korean, whether it holds it. */
        fun names(forms: Set<String>, text: String): Boolean {
            if (parts(text).any { part -> compactForms(part).any { it in forms } }) return true
            val squeezed = listOf(text, Normalize.simplified(text)).map { Normalize.compact(Normalize.slugKey(it)) }.toSet()
            return forms.any { f -> cjk(f) && squeezed.any { f in it } }
        }

        /** title_in: EXACT, ALONE or 0. */
        fun titleIn(title: String): Int {
            if (parts(title).any { part -> compactForms(part).any { it in titles } } || strippedToTitle(title)) return rules.exact
            return cjkTitleIn(title)
        }

        private fun cjkTitleIn(title: String): Int {
            if (cjkTitles.isEmpty()) return 0
            var found = 0
            for (text in linkedSetOf(title, Normalize.simplified(title))) {
                val squeezed = Squeezed(text)
                for (form in cjkTitles) {
                    val f = Py.codePoints(form)
                    var start = find(squeezed.text, f, 0)
                    while (start >= 0) {
                        val end = start + f.size
                        if (covered(squeezed, 0, start) && covered(squeezed, end, squeezed.text.size)) return rules.exact
                        val (first, last) = squeezed.wordAround(start, end)
                        if (covered(squeezed, first, start, latin = false) && covered(squeezed, end, last, latin = false)) {
                            found = rules.alone
                        }
                        start = find(squeezed.text, f, start + 1)
                    }
                }
            }
            return found
        }

        /** _covered: whether text[start:end] is only the artist's names and words such as 官方 (and, with [latin], whole
         * Latin words such as "official" and numbers); never a run that ends inside a Latin word. */
        private fun covered(squeezed: Squeezed, start: Int, end: Int, latin: Boolean = true): Boolean {
            val text = squeezed.text
            val ends = squeezed.ends
            if (start < end && ((start !in ends && !rules.cjk(text[start])) ||
                    (end !in squeezed.endSet && !rules.cjk(text[end - 1])))) return false
            val reached = hashSetOf(start)
            val todo = ArrayDeque<Int>().apply { add(start) }
            while (todo.isNotEmpty()) {
                val at = todo.removeLast()
                if (at == end) return true
                val steps = ArrayList<Int>()
                for (w in cjkWordCps) if (startsWith(text, w, at)) steps += at + w.size
                if (latin && at in ends && !rules.cjk(text[at])) {
                    val wordEnd = ends.getValue(at)
                    val word = Py.string(text, at, wordEnd)
                    if (word in rules.decoration || PyText.allDigits(word)) steps += wordEnd
                    for (a in latinArtistCps) {
                        if (startsWith(text, a, at) && (at + a.size) in squeezed.endSet) steps += at + a.size
                    }
                }
                for (step in steps) {
                    if (step <= end && reached.add(step)) todo.addLast(step)
                }
            }
            return false
        }

        /** _stripped_to_title: the title, its artist and the words around it taken off its ends, is the song's. */
        private fun strippedToTitle(title: String): Boolean {
            var tokens: List<String> = Normalize.slugKey(title).split("-")
            val slugs = artistSlugs.map { it.split("-") }
            while (tokens.isNotEmpty()) {
                if (Normalize.compact(tokens.joinToString("")) in titles) return true
                var stripped = false
                for (a in slugs) {
                    if (a.size < tokens.size && tokens.subList(0, a.size) == a) {
                        tokens = tokens.subList(a.size, tokens.size)
                        stripped = true
                        break
                    }
                    if (a.size < tokens.size && tokens.subList(tokens.size - a.size, tokens.size) == a) {
                        tokens = tokens.subList(0, tokens.size - a.size)
                        stripped = true
                        break
                    }
                }
                if (stripped) continue
                tokens = when {
                    tokens.last() in rules.decoration || PyText.allDigits(tokens.last()) -> tokens.dropLast(1)
                    tokens.first() in rules.decoration || PyText.allDigits(tokens.first()) -> tokens.drop(1)
                    else -> return false
                }
            }
            return false
        }

        fun channelIsArtist(channel: String): Boolean {
            val stripped = Py.strip(channel)
            if (stripped.isEmpty()) return false
            val topic = PyRe.match(rules.topic, stripped)
            val bare = PyRe.sub(rules.channelSuffix, topic?.groups?.get(1)?.value ?: stripped) { "" }
            if (bare.isNotEmpty() && names(artists, bare)) return true
            val squeezed = Normalize.compact(Normalize.slugKey(channel))
            return artists.any { a -> rules.ownChannel.any { suffix -> squeezed == a + suffix } }
        }

        fun artistIn(title: String): Boolean {
            if (names(artists, title)) return true
            val tokens = Normalize.slugKey(title).split("-")
            return artistSlugs.map { it.split("-") }.any { a ->
                (a.size <= tokens.size && tokens.subList(0, a.size) == a) ||
                    (a.size <= tokens.size && tokens.subList(tokens.size - a.size, tokens.size) == a)
            }
        }

        /** Whether the video is a version other than the song's own, by its title or its channel. */
        fun unwanted(title: String, channel: String): Boolean {
            if (PyRe.search(rules.karaokeChannel, Normalize.fold(channel)) != null &&
                PyRe.search(rules.karaokeChannel, whole) == null) return true
            return listOf(title, channel).any { text ->
                PyRe.finditer(rules.unwanted, Normalize.fold(text)).any { it.value !in whole }
            }
        }
    }
}
