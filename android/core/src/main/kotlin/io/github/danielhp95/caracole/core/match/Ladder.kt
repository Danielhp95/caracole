package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.KeyTables
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText

/** match._Hit: a candidate, the order its artist key was tried in, and its tabs. */
internal data class Hit(val cand: MatchCandidate, val rank: Int, val tabs: Int) {
    val score: Double get() = cand.score!!
}

/** match._Forms: a name or title as keys: its own key, its pinyin key when it has Chinese characters, and its other
 * forms (`Normalize.nameForms`), such as each part of a name written in two scripts. */
internal class Forms(val own: List<String>, val pinyin: List<String>, val parts: List<String>) {
    val keys: List<String> = own + pinyin + parts
}

/**
 * match.py's ladder (match_song and the steps it climbs), line for line: see Matcher's KDoc for the order. Each
 * score is rapidfuzz's (Fuzz), rounded as `round(score, 1)` (Py.round), each sort a stable one on Python's keys.
 */
internal object Ladder {
    /** Spanish leading articles, part of some UG artist slugs and not of the source's name, or the other way. */
    private val ARTICLES = listOf("los", "las", "el", "la")
    private const val TITLE_ONLY_TITLES = 10  // nearest titles expanded into candidates, per title form
    private const val TYPO_ARTISTS = 5  // nearest artist keys within the typo distance, per name

    fun forms(text: String): Forms {
        val own = Normalize.slugKey(text)
        val pinyin = if (Normalize.hasHan(text)) Normalize.slugKey(Normalize.romanize(text)) else ""
        val parts = Normalize.nameForms(text).filter { it != own && it != pinyin }
        return Forms(listOfNotNull(own.ifEmpty { null }), listOfNotNull(pinyin.takeIf { it.isNotEmpty() && it != own }),
                     parts)
    }

    /** song.artists or [song.artist]. */
    fun artistsOf(song: SongRow): List<String> = song.artists.ifEmpty { listOf(song.artist) }

    private fun articleForms(key: String): List<String> {
        val dash = key.indexOf('-')
        if (dash >= 0) {
            val head = key.substring(0, dash)
            val rest = key.substring(dash + 1)
            if (rest.isNotEmpty() && head in ARTICLES) return listOf(rest)
        }
        return ARTICLES.map { "$it-$key" }
    }

    /** (UG artist key, came from [alias]) for each of the song's artists, in the order they're tried. */
    fun ownArtists(song: SongRow, index: IndexView, overrides: Overrides): List<Pair<String, Boolean>> {
        val keys = LinkedHashMap<String, Boolean>()
        fun add(key: String, alias: Boolean = false) {
            if (key.isNotEmpty() && key !in keys && index.hasArtist(key)) keys[key] = alias
        }
        for (name in artistsOf(song)) {
            for (a in overrides.alias[Normalize.slugKey(name)].orEmpty()) add(a, alias = true)
            val forms = forms(name).keys
            for (form in forms) {
                add(form)
                for (a in index.compactArtists(Normalize.compact(form))) add(a)
            }
            for (form in forms) for (alt in articleForms(form)) add(alt)
        }
        return keys.toList()
    }

    /** Score every title of one artist, grouped by base key. */
    fun titleHits(index: IndexView, artistKey: String, title: Forms, rank: Int, exactStep: String,
                  fuzzyStep: String = "fuzzy_title", cap: Double? = null): List<Hit> {
        val compactPinyin = title.pinyin.map(Normalize::compact)
        return index.titlesForArtist(artistKey).map { t ->
            val base = t.baseKey
            val keys = LinkedHashSet<String>().apply { add(base); addAll(t.songKeys) }
            val compactBase = Normalize.compact(base)
            var score: Double
            val step: String
            if (title.keys.any { it in keys || Normalize.compact(it) == compactBase }) {
                score = 100.0
                step = exactStep
            } else {
                score = title.keys.maxOf { k -> keys.maxOf { u -> Fuzz.ratio(k, u) } }
                for (c in compactPinyin) score = maxOf(score, Fuzz.ratio(c, compactBase))
                step = fuzzyStep
            }
            if (cap != null) score = minOf(score, cap)
            Hit(MatchCandidate(artistKey, base, Py.round(score, 1), step), rank, t.tabs)
        }
    }

    /** Best first (score, then the artist tried first, then the most tabs), one hit per UG song. */
    fun ranked(hits: List<Hit>): List<Hit> {
        val best = LinkedHashMap<Pair<String, String>, Hit>()
        for (h in hits.sortedWith(compareByDescending<Hit> { it.score }.thenBy { it.rank }.thenByDescending { it.tabs })) {
            best.putIfAbsent(h.cand.artistKey to h.cand.songKey, h)
        }
        return best.values.toList()
    }

    fun decide(hits: List<Hit>, policy: MatchPolicy): String {
        if (hits.isEmpty()) return "not_found"
        val best = hits[0].cand
        val rival = hits.drop(1).firstOrNull { it.cand.songKey != best.songKey }?.score ?: 0.0
        val score = best.score!!
        if (score >= policy.accept && score - rival >= policy.margin) return "accept"
        return if (score >= policy.review) "review" else "not_found"
    }

    /** For each of the song's artists, the closest artist key not tried yet, if it scores [gate] or more; a Chinese
     * name's pinyin also compared without hyphens. */
    fun nearestArtists(song: SongRow, index: IndexView, tried: Set<String>, gate: Double): List<Pair<String, Double>> {
        val artists = index.artistKeys()
        val found = LinkedHashMap<String, Double>()
        for (name in artistsOf(song)) {
            val forms = forms(name)
            val queries = forms.keys.map { it to artists } + forms.pinyin.map { Normalize.compact(it) to index.compactArtistKeys() }
            var best: Pair<String, Double>? = null
            for ((query, choices) in queries) {
                val skip = tried + found.keys
                // At most skip.size of these are skipped, so one is left whenever any artist passes the gate.
                val near = Fuzz.extract(query, choices, gate, skip.size + 1)
                val hit = near.firstOrNull { artists[it.index] !in skip } ?: continue
                if (best == null || hit.score > best.second) best = artists[hit.index] to hit.score
            }
            if (best != null) found[best.first] = Py.round(best.second, 1)
        }
        return found.toList()
    }

    /** Step 5; [rank] puts its hits behind every other step's of the same score. */
    fun titleOnly(index: IndexView, title: Forms, policy: MatchPolicy, rank: Int = 0): List<Hit> {
        val titles = index.titleKeys()
        val scores = LinkedHashMap<String, Double>()
        for (query in title.own) {
            for (e in Fuzz.extract(query, titles, policy.review, TITLE_ONLY_TITLES)) {
                val key = titles[e.index]
                scores[key] = maxOf(scores[key] ?: 0.0, e.score)
            }
        }
        // Across every artist, pinyin counts only when it matches exactly (hyphens aside); so do the parts of a
        // title written in two scripts, whose romanizations are just as short.
        for (query in title.pinyin + title.parts) {
            for (key in index.titlesReading(Normalize.compact(query))) scores[key] = 100.0
        }
        val hits = ArrayList<Hit>()
        for ((key, score) in scores) {
            for ((a, n) in index.artistsForTitle(key)) {
                hits += Hit(MatchCandidate(a, key, Py.round(score, 1), "title_only"), rank, n)
            }
        }
        return ranked(hits)
    }

    // --- names that aren't quite UG's (step 4) ----------------------------------------------------------------

    /** Where [part] first runs, whole words in order, inside [words]. */
    private fun find(words: List<String>, part: List<String>): Int? {
        val n = part.size
        for (i in 0..words.size - n) if (words.subList(i, i + n) == part) return i
        return null
    }

    /** Whether words could name a song or an artist on their own: three letters or more besides GENERIC_WORDS and
     * numbers, or any Chinese. */
    fun namesSomething(words: List<String>): Boolean {
        val kept = words.filter { it !in KeyTables.genericWords && !PyText.allDigits(it) }
        return kept.any(Normalize::hasHan) || kept.sumOf(Py::len) >= 3
    }

    private fun coverage(short: List<String>, long: List<String>): Double =
        Py.len(short.joinToString("")).toDouble() / Py.len(long.joinToString("")).toDouble()

    /** 80 to 90 when one key's words run inside the other's, by how much of the longer the shorter covers; else 0. */
    fun wordScore(a: String, b: String): Double {
        val x = a.split("-")
        val y = b.split("-")
        val (short, long) = if (y.size < x.size) y to x else x to y
        if (short.size == long.size || !namesSomething(short) || find(long, short) == null) return 0.0
        return 80 + 10 * coverage(short, long)
    }

    /** A title against one UG title key, as step 2 scores it, or as a `word_title`. */
    fun titleScore(title: Forms, key: String): Double {
        val compactKey = Normalize.compact(key)
        if (title.keys.any { it == key || Normalize.compact(it) == compactKey }) return 100.0
        return title.keys.maxOf { k -> maxOf(Fuzz.ratio(k, key), wordScore(k, key)) }
    }

    /** The artist's titles that hold yours word for word, or that yours holds. */
    private fun wordHits(index: IndexView, artistKey: String, title: Forms, rank: Int, step: String,
                         cap: Double? = null): List<Hit> {
        val hits = ArrayList<Hit>()
        for (t in index.titlesForArtist(artistKey)) {
            val keys = LinkedHashSet<String>().apply { add(t.baseKey); addAll(t.songKeys) }
            var score = title.keys.maxOf { k -> keys.maxOf { u -> wordScore(k, u) } }
            if (score != 0.0) {
                if (cap != null) score = minOf(score, cap)
                hits += Hit(MatchCandidate(artistKey, t.baseKey, Py.round(score, 1), step), rank, t.tabs)
            }
        }
        return hits
    }

    /** The artist keys an edit or so from one of the song's names (two letters swapped count as one): one edit for
     * a name of four to seven letters, two from eight, compared without hyphens, Latin names only; nearest first,
     * then the most tabs. */
    private fun typoArtists(song: SongRow, index: IndexView, tried: Set<String>): List<String> {
        val artists = index.artistKeys()
        val compacts = index.compactArtistKeys()
        val found = LinkedHashSet<String>()
        for (name in artistsOf(song)) {
            val forms = forms(name)
            for (form in LinkedHashSet((forms.own + forms.parts).filter(PyText::isAscii))) {
                val query = Normalize.compact(form)
                if (Py.len(query) < 4) continue
                val edits = if (Py.len(query) < 8) 1 else 2
                // Every neighbour (few, an edit or two away), not the first in the alphabet.
                val keys = Fuzz.extractDistance(query, compacts, edits)
                    .map { it.distance to artists[it.index] }
                    .filter { (_, a) -> a !in tried && a !in found }
                    .sortedWith(compareBy<Pair<Int, String>> { it.first }
                                    .thenByDescending { index.artistTabs(it.second) }
                                    .thenComparing({ it.second }, Py.CODE_POINT_ORDER))
                for ((_, key) in keys.take(TYPO_ARTISTS)) found += key
            }
        }
        return found.toList()
    }

    /** What a catch-all title holds besides the name, wherever the name runs in it: the words after it, before it,
     * or both, each also without the words next to the name that only say what the name is (SHOW_WORDS). */
    private fun rests(words: List<String>, name: List<String>): List<List<String>> {
        val i = find(words, name) ?: return emptyList()
        val before = words.subList(0, i)
        val after = words.subList(i + name.size, words.size)
        val bareBefore = before.toMutableList()
        while (bareBefore.isNotEmpty() && bareBefore.last() in Match.SHOW_WORDS) bareBefore.removeAt(bareBefore.size - 1)
        val bareAfter = after.toMutableList()
        while (bareAfter.isNotEmpty() && bareAfter.first() in Match.SHOW_WORDS) bareAfter.removeAt(0)
        val parts = mutableListOf<List<String>>(after, bareAfter, before, bareBefore)
        if (before.isNotEmpty() && after.isNotEmpty()) {
            parts += before + after
            parts += bareBefore + bareAfter
        }
        return parts.filter { it.isNotEmpty() }
    }

    /** The songs of UG's catch-all artists whose titles name the song's artist and hold its title (match.py's
     * `_catch_all_hits`). */
    private fun catchAllHits(song: SongRow, index: IndexView, title: Forms, rank: Int): List<Hit> {
        val names = artistsOf(song).flatMap { forms(it).keys }.filter { namesSomething(it.split("-")) }
        val endings = title.own.filter { k -> k.count { it == '-' } >= 1 && namesSomething(k.split("-")) }
        val hits = ArrayList<Hit>()
        // Only a title that holds a name, or ends in an ending, can score.
        for (s in index.catchAllHolding(names.map { "-$it-" } + endings.map { "-$it-\n" })) {
            val padded = "-${s.baseKey}-"
            val held = if (s.artistKey in Match.PERFORMER_CATCH_ALLS) names.filter { padded.startsWith("-$it-") }
                       else names.filter { "-$it-" in padded }
            val score = when {
                held.isNotEmpty() -> {
                    val words = s.baseKey.split("-")
                    val rests = held.flatMap { rests(words, it.split("-")) }
                    rests.maxOfOrNull { titleScore(title, it.joinToString("-")) } ?: 0.0
                }
                s.artistKey in Match.SHOW_CATCH_ALLS ->
                    if (endings.any { e -> padded.endsWith("-$e-") && e != s.baseKey }) Match.CATCH_ALL_ENDING else 0.0
                else -> 0.0
            }
            if (score != 0.0) hits += Hit(MatchCandidate(s.artistKey, s.baseKey, Py.round(score, 1), "catch_all"), rank, s.tabs)
        }
        return hits
    }

    /** Step 4: the `word_title`, `typo_artist` and `catch_all` hits that reach `review`. [routes] are the artist keys
     * steps 2 and 3 tried, in order, each with the score its titles are capped at (null for the song's own); [own]
     * says whether any of them is the song's own. */
    private fun tolerantHits(song: SongRow, index: IndexView, title: Forms, routes: List<Pair<String, Double?>>,
                             own: Boolean, policy: MatchPolicy): List<Hit> {
        val hits = ArrayList<Hit>()
        routes.forEachIndexed { rank, (artistKey, cap) ->
            hits += wordHits(index, artistKey, title, rank, step = "word_title", cap = cap)
        }
        var rank = routes.size
        if (!own) {
            for (artistKey in typoArtists(song, index, routes.map { it.first }.toSet())) {
                hits += titleHits(index, artistKey, title, rank, exactStep = "typo_artist", fuzzyStep = "typo_artist")
                hits += wordHits(index, artistKey, title, rank, step = "typo_artist")
                rank += 1
            }
        }
        hits += catchAllHits(song, index, title, rank)
        return hits.filter { it.score >= policy.review }
    }

    /** The hits that aren't UG songs you rejected for the song. */
    private fun allowed(hits: List<Hit>, rejected: Set<Pair<String, String>>): List<Hit> =
        hits.filter { (it.cand.artistKey to it.cand.songKey) !in rejected }

    /** [hits] with the best of each of KEPT_STEPS (score, then tabs) among the first MAX_CANDIDATES, in place of the
     * last of the others there; the rest keep their order. */
    private fun keepingNearNames(hits: List<Hit>): List<Hit> {
        var top = hits.take(Match.MAX_CANDIDATES)
        val kept = Match.KEPT_STEPS.mapNotNull { step ->
            hits.filter { it.cand.step == step }.minWithOrNull(
                compareByDescending<Hit> { it.score }.thenByDescending { it.tabs }.thenBy { it.rank })
        }
        val missing = kept.filter { it !in top }
        if (missing.isEmpty()) return hits
        val dropped = top.filter { it !in kept }.takeLast(missing.size)
        top = top.filter { it !in dropped } + missing
        return top + hits.filter { it !in top }
    }

    private fun review(hits: List<Hit>): MatchResult = result("review", keepingNearNames(ranked(hits)))

    private fun result(decision: String, hits: List<Hit>): MatchResult {
        val best = hits[0].cand
        return MatchResult(decision, best.step, best.score, best.artistKey, best.songKey,
                           candidates = hits.take(Match.MAX_CANDIDATES).map { it.cand })
    }

    /** Whether the LaCuerda sheet you picked for the song leaves a review of [hits] nothing to ask: they are other
     * artists' songs alone (NO_ALIAS_STEPS). */
    private fun settledOnLaCuerda(ident: String, hits: List<Hit>, overrides: Overrides): Boolean =
        ident in overrides.lacuerda && hits.all { it.cand.step in Match.NO_ALIAS_STEPS }

    private fun pinnedKeys(index: IndexView, pins: List<Long>): Pair<String?, String?> {
        for (tabId in pins) {
            val keys = index.tabKeys(tabId) ?: continue
            return keys.first to Normalize.splitVariant(keys.second).first
        }
        return null to null
    }

    /** match.match_song: the ladder for one song. */
    fun matchSong(song: SongRow, index: IndexView, overrides: Overrides, policy: MatchPolicy): MatchResult {
        val ident = song.key
        if (ident in overrides.ignore) return MatchResult("ignored", "override", null, null, null)
        overrides.pin[ident]?.let { pins ->
            val (artistKey, songKey) = overrides.match[ident]?.let { it.first to it.second } ?: pinnedKeys(index, pins)
            return MatchResult("pinned", "pin", null, artistKey, songKey, pinned = pins)
        }
        overrides.match[ident]?.let { (artistKey, songKey) ->
            return MatchResult("accept", "override", 100.0, artistKey, songKey,
                               candidates = listOf(MatchCandidate(artistKey, songKey, 100.0, "override")))
        }

        val title = forms(Normalize.cleanTitle(song.title))
        if (title.keys.isEmpty()) return MatchResult("not_found", null, null, null, null)
        val rejected = overrides.reject[ident].orEmpty()
        val own = ownArtists(song, index, overrides)
        val hits = ArrayList<Hit>()
        own.forEachIndexed { rank, (artistKey, viaAlias) ->
            hits += allowed(titleHits(index, artistKey, title, rank, exactStep = if (viaAlias) "alias" else "exact"),
                            rejected)
        }
        var ranked = ranked(hits)
        val exact = ranked.firstOrNull { it.cand.step == "exact" || it.cand.step == "alias" }
        if (exact != null) return result("accept", listOf(exact) + ranked.filter { it !== exact })

        var decision = decide(ranked, policy)
        if (decision == "accept") return result(decision, ranked)
        val routes = own.map { it.first to null as Double? }.toMutableList()
        nearestArtists(song, index, routes.map { it.first }.toSet(), policy.artistGate).forEachIndexed { i, (artistKey, score) ->
            hits += allowed(titleHits(index, artistKey, title, own.size + i, exactStep = "fuzzy_artist",
                                      fuzzyStep = "fuzzy_artist", cap = score), rejected)
            routes += artistKey to score
        }
        ranked = ranked(hits)
        decision = decide(ranked, policy)
        if (decision == "accept") return result(decision, ranked)

        // Names that aren't quite UG's: never an accept.
        val tolerant = allowed(tolerantHits(song, index, title, routes, own.isNotEmpty(), policy), rejected)
        if (decision == "review") return review(hits + tolerant)
        val behind = (tolerant.maxOfOrNull { it.rank } ?: routes.size) + 1
        val found = tolerant + allowed(titleOnly(index, title, policy, behind), rejected)
        if (found.isNotEmpty() && !settledOnLaCuerda(ident, found, overrides)) return review(found)
        return MatchResult("not_found", null, ranked.firstOrNull()?.cand?.score, null, null,
                           candidates = ranked.take(Match.MAX_CANDIDATES).map { it.cand })
    }
}
