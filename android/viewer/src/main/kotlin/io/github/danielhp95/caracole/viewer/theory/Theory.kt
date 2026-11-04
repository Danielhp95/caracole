package io.github.danielhp95.caracole.viewer.theory

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyUnicode
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap

/**
 * viewer/theory.py: chord names, keys and modes, the music theory behind the sheet viewer, answering as theory.py
 * does for every chord, key and mode (vectors/viewer/theory.jsonl). Pitch classes are integers, 0 for C up to 11 for
 * B; a chord is a root, a quality and an optional bass note ([Chord]); a key a tonic and a mode ([Key]).
 *
 * Its tables and patterns are theory.py's own, read from caracole/viewer/theory.json ([TheoryData]); its patterns run
 * as Python's (core.py's PyRegex and PyRe), and a text is stripped as Python strips it ([Py.strip]), so lengths and
 * places are Python's.
 *
 * As in Python, the answers asked most are kept (map_chord's and alternatives' 4,096 last, every key's spelling,
 * name and capo hints), Chord and Key are frozen, and every list handed out is a copy of the one kept.
 */
object Theory {
    /** Quality to intervals above the root, in semitones, in theory.py's order. */
    val QUALITIES: Map<String, Set<Int>> get() = TheoryData.qualities

    /** How a made-up chord's quality is written, where that differs from its name ("mmaj7" is "m(maj7)"). */
    val DISPLAY: Map<String, String> get() = TheoryData.display
    val MODES: List<String> get() = TheoryData.modes
    val SCALES: Map<String, List<Int>> get() = TheoryData.scales
    val SHARPS: List<String> get() = TheoryData.sharps
    val FLATS: List<String> get() = TheoryData.flats

    /** "CDEFGAB": a letter's index is its place in a key's letters. */
    val LETTERS: String get() = TheoryData.letters

    /** Each letter's pitch class, unaltered. */
    val NATURAL: Map<String, Int> get() = TheoryData.natural

    /** The scale degree (0–6) each interval above the tonic is written as, in a "major" mode and a "minor" one. */
    val DEGREES: Map<String, List<Int>> get() = TheoryData.degrees
    val MAX_CAPO: Int get() = TheoryData.maxCapo

    /** A note's pitch class: its letter ("C"…"B") moved by its accidental ("", "#", "♯", "b", "♭"). */
    fun notePc(letter: String, accidental: String = ""): Int =
        Math.floorMod(TheoryData.natural.getValue(letter) + TheoryData.accidental.getValue(accidental), 12)

    // --- chord names -------------------------------------------------------------------------------------------------

    /**
     * The chord a name stands for, or null when it is none ("N.C.", "x2", "H").
     *
     * With [strict] false a chord whose suffix isn't understood ("Cfoo") still gives its root and bass, sounding as a
     * major or (suffix "m…") minor triad: the viewer can still transpose it.
     */
    fun parseChord(text: String, strict: Boolean = true): Chord? {
        val name = Py.strip(text)
        val m = PyRe.match(TheoryData.root, name) ?: return null
        val root = notePc(m.groupValues[1], m.groupValues[2])
        var rest = name.substring(m.range.last + 1)
        var bass: Int? = null
        val b = PyRe.search(TheoryData.bass, rest)
        if (b != null) {
            bass = notePc(b.groupValues[1], b.groupValues[2])
            rest = rest.substring(0, b.range.first)
        }
        val normalized = normalize(rest)
        val tones = intervals(normalized)
        if (tones == null) {
            if (strict || "/" in rest) return null
            val minor = normalized.startsWith("m") && !normalized.startsWith("maj")
            return Chord(root, normalized, bass, rest, TheoryData.qualities.getValue(if (minor) "m" else ""))
        }
        val quality = TheoryData.byIntervals[tones] ?: return Chord(root, normalized, bass, rest, tones)
        return Chord(root, quality, bass, rest)
    }

    /** theory.py's `_normalize`: a suffix with each of `_REWRITES` applied in order. */
    fun normalize(suffix: String): String {
        var s = suffix
        for ((pattern, template) in TheoryData.rewrites) s = PyRe.sub(pattern, s) { expand(template, it) }
        return s
    }

    /** A replacement template whose escapes are `\<digit>`, a group's text ("" where it took no part). */
    private fun expand(template: String, m: MatchResult): String {
        if ('\\' !in template) return template
        val out = StringBuilder()
        var i = 0
        while (i < template.length) {
            val c = template[i]
            if (c == '\\' && i + 1 < template.length && template[i + 1] in '1'..'9') {
                out.append(m.groups[template[i + 1] - '0']?.value ?: "")
                i += 2
            } else {
                out.append(c)
                i++
            }
        }
        return out.toString()
    }

    /**
     * theory.py's `_intervals`: the intervals a normalized suffix spells, or null when it spells none. A suffix is a
     * triad (minor "m", "dim", "aug", else major), an extension ("6", "7", "maj7", "9", "11", "13", "69"), a
     * suspension ("sus2", "sus4") and alterations ("b5", "#9", "add9", "no3"), each optional, in that order.
     */
    fun intervals(s: String): Set<Int>? {
        if (s == "5") return TheoryData.qualities.getValue("5")
        var third: Int? = 4
        var fifth: Int? = 7
        var seventh: Int? = null
        val extra = HashSet<Int>()
        var dim = false
        var pos = 0
        if (s.startsWith("dim")) {
            third = 3; fifth = 6; dim = true; pos = 3
        } else if (s.startsWith("aug")) {
            fifth = 8; pos = 3
        } else if (s.startsWith("m") && !s.startsWith("maj")) {
            third = 3; pos = 1
        }
        val m = TheoryData.extension.matchAt(s, pos)!!  // every part optional: it always matches
        val maj = m.groups[1]?.value
        var ext = m.groups[2]?.value
        pos = m.range.last + 1
        if (maj != null && ext == null && third == 3) ext = "7"  // "mmaj" is the minor-major seventh
        if (maj != null && (ext == "6" || ext == "69")) return null
        when (ext) {
            "7", "9", "11", "13" -> {
                seventh = if (maj != null) 11 else if (dim && ext == "7") 9 else 10
                extra += when (ext) {
                    "9" -> listOf(2)
                    "11" -> listOf(2, 5)
                    "13" -> listOf(2, 9)
                    else -> emptyList()
                }
            }
            "6" -> extra += 9
            "69" -> extra += listOf(2, 9)
        }
        val sus = TheoryData.sus.matchAt(s, pos)
        if (sus != null) {
            third = if (sus.groups[1]?.value == "2") 2 else 5
            pos = sus.range.last + 1
        }
        while (pos < s.length) {
            val alt = TheoryData.alteration.matchAt(s, pos) ?: return null
            val token = alt.value
            val altered = TheoryData.altered[token]
            when {
                token.startsWith("add") -> extra += TheoryData.added.getValue(token.substring(3))
                token == "b5" -> fifth = 6
                token == "#5" -> fifth = 8
                token == "no3" -> third = null
                token == "no5" -> fifth = null
                altered != null -> {
                    if (token == "b9" || token == "#9") extra -= 2  // an altered ninth replaces the natural one
                    extra += altered
                }
                else -> return null  // read by the pattern but not known: the suffix spells no chord
            }
            pos = alt.range.last + 1
        }
        val tones = HashSet<Int>(extra)
        tones += 0
        listOfNotNull(third, fifth, seventh).forEach { tones += it }
        return Chord.frozen(tones)
    }

    // --- keys and modes ----------------------------------------------------------------------------------------------

    private val spellings = ConcurrentHashMap<Key, List<String>>()
    private val names = ConcurrentHashMap<Key, String>()

    /**
     * The name of each pitch class (index) in [key]: Bb in F major, A# in E major. With no key, the names chord sheets
     * use most (C#, Eb, F#, Ab, Bb). A copy: changing it changes nothing kept.
     */
    fun spelling(key: Key?): List<String> = ArrayList(kept(key))

    private fun kept(key: Key?): List<String> {
        if (key == null) return TheoryData.defaultSpelling
        return spellings.getOrPut(key) {
            val tonicLetter = tonicLetter(key)
            val degrees = TheoryData.degrees.getValue(if (4 in scaleSteps(key.mode)) "major" else "minor")
            val out = Array(12) { "" }
            for (interval in 0 until 12) {
                val pc = Math.floorMod(key.tonic + interval, 12)
                val letter = TheoryData.letters[Math.floorMod(tonicLetter + degrees[interval], 7)].toString()
                out[pc] = spell(letter, Math.floorMod(pc - TheoryData.natural.getValue(letter) + 6, 12) - 6)
            }
            Collections.unmodifiableList(out.toList())
        }
    }

    /** The letter (index into "CDEFGAB") of the key's tonic: that degree of its relative major. */
    private fun tonicLetter(key: Key): Int {
        val degree = modeIndex(key.mode)
        val relative = Math.floorMod(key.tonic - scaleSteps("ionian")[degree], 12)
        return Math.floorMod(TheoryData.letters.indexOf(TheoryData.majorTonics[relative][0]) + degree, 7)
    }

    private fun spell(letter: String, accidental: Int): String {
        if (accidental == 0) return letter
        if (Math.abs(accidental) == 1) {
            return TheoryData.rare[letter to accidental] ?: (letter + if (accidental > 0) "#" else "b")
        }
        val pc = Math.floorMod(TheoryData.natural.getValue(letter) + accidental, 12)  // a double sharp or flat
        return (if (accidental > 0) TheoryData.sharps else TheoryData.flats)[pc]
    }

    /** "G", "Am", "D dorian": the key as a chord sheet writes it. */
    fun keyName(key: Key): String = names.getOrPut(key) {
        val tonic = pyIndex(kept(key), key.tonic)
        when (key.mode) {
            "ionian" -> tonic
            "aeolian" -> tonic + "m"
            else -> "$tonic ${key.mode}"
        }
    }

    /**
     * The key a tab or a tag names ("Am", "F#m", "Bb", "C minor", "A dorian"), or null: a letter alone ("A", "F#") is
     * its major key, which [namedKey] reads again with the chords the sheet plays. Anything but a String names none.
     */
    fun parseKey(text: Any?): Key? {
        if (text !is String) return null
        val m = PyRe.fullmatch(TheoryData.key, text) ?: return null
        val letter = m.groupValues[1]
        val accidental = m.groupValues[2]
        val word = m.groups[3]?.value ?: "M"
        val lower = PyUnicode.lower(word)
        val mode = TheoryData.modeWords[word] ?: TheoryData.modeWords[lower] ?: lower
        return Key(notePc(PyUnicode.upper(letter), accidental), mode)
    }

    /**
     * The key a tab, a tag or a sheet's `{key}` names ([parseKey]), its sheet's chords [played] with the capo on fret
     * [capo]: a letter alone ("A", "F#") is its parallel minor where they say so ([bareKey]), and a key named with
     * its mode ("A", "Am", "A major", "A minor", "A dorian") is as named. Still the key the tab named, the shapes' or
     * the sound's: [shapesKey] tells which. Null when [text] names no key.
     */
    fun namedKey(text: Any?, capo: Int, played: List<Chord>): Key? {
        val named = parseKey(text) ?: return null
        val m = PyRe.fullmatch(TheoryData.key, text as String)
        if (m == null || m.groups[3] != null) return named
        return bareKey(named, capo, played)
    }

    /**
     * The key a tab names by its letter alone, [named] (read as major), its sheet's chords [played] with the capo on
     * fret [capo]: its parallel minor when their key ([estimateKey]) has the notes of that minor, or of the minor a
     * capo lower, and those of neither major key, and they never play that minor's tonic as a major chord; and the
     * relative minor of the letter's major when their key is it (theory.py's docstring has the cases).
     */
    fun bareKey(named: Key, capo: Int, played: List<Chord>): Key {
        if (named.mode != "ionian") return named
        val found = estimateKey(played) ?: return named

        fun playsMajor(tonic: Int): Boolean = played.any { it.root == tonic && 4 in it.intervals }

        if (found.tonic == named.tonic) {  // the chords' own tonic is the letter's: the shapes' key, in their mode
            return if (found.mode == "aeolian" && !playsMajor(named.tonic)) Key(named.tonic, "aeolian") else named
        }
        if (found.mode == "aeolian" && scale(found) == scale(named)) {  // the relative minor of the letter's major
            return if (playsMajor(found.tonic)) named else found
        }
        val notes = scale(found)
        val lowered = Math.floorMod(named.tonic - capo, 12)
        if (notes == scale(named) || notes == scale(Key(lowered, "ionian"))) return named
        for (tonic in listOf(named.tonic, lowered)) {
            if (notes == scale(Key(tonic, "aeolian"))) return if (playsMajor(tonic)) named else Key(named.tonic, "aeolian")
        }
        return named
    }

    /** The key's pitch classes. */
    fun scale(key: Key): Set<Int> {
        val out = java.util.TreeSet<Int>()
        for (i in scaleSteps(key.mode)) out += Math.floorMod(key.tonic + i, 12)
        return Collections.unmodifiableSet(out)
    }

    /**
     * The major or minor key the chords (in the order the sheet plays them) are most likely in, or null without
     * chords: each chord whose notes are all in a key counts for it (in a minor key a dominant or leading-note chord
     * may raise the seventh), one with only its root in the key a little, the tonic chord again, and more when the
     * song starts or ends on it; a major chord on the fifth, a little. The first of the best, ionian before aeolian,
     * C before C#.
     */
    fun estimateKey(chords: List<Chord>): Key? {
        if (chords.isEmpty()) return null
        var best: Key? = null
        var bestScore = 0.0
        for (mode in listOf("ionian", "aeolian")) {
            for (tonic in 0 until 12) {
                val key = Key(tonic, mode)
                val score = keyScore(chords, key)
                if (best == null || score > bestScore) {
                    best = key
                    bestScore = score
                }
            }
        }
        return best
    }

    private fun keyScore(chords: List<Chord>, key: Key): Double {
        val notes = scale(key)
        val third = if (key.mode == "aeolian") 3 else 4
        val dominant = Math.floorMod(key.tonic + 7, 12)
        val leading = Math.floorMod(key.tonic + 11, 12)

        fun isTonic(chord: Chord): Boolean = chord.root == key.tonic && third in chord.intervals

        var score = 0.0
        for (chord in chords) {
            val allowed = if (key.mode == "aeolian" && (chord.root == dominant || chord.root == leading)) notes + leading
            else notes
            if (allowed.containsAll(chord.pitchClasses)) score += 1
            else if (chord.root in notes) score += 0.25
            if (isTonic(chord)) score += 0.5
            if (chord.root == dominant && 4 in chord.intervals) score += 0.25
        }
        if (isTonic(chords.first())) score += 1.25
        if (isTonic(chords.last())) score += 1.25  // tabs often end on an outro or a fade, so no more than the start
        return score
    }

    private val mapped = Lru<Triple<Chord, Key, String>, Chord>(4096)

    /**
     * The chord in [mode] on the same tonic: each note moves to the same scale degree there (C minor's Ab becomes C
     * major's Am). A note outside the key's scale stays where it is. When the notes make no chord of [QUALITIES], the
     * new mode's own triad or seventh chord on the new root stands in. A chord the change leaves alone is returned as
     * it is.
     */
    fun mapChord(chord: Chord, key: Key, mode: String): Chord {
        if (mode == key.mode) return chord
        return mapped.getOrPut(Triple(chord, key, mode)) {
            val src = scaleSteps(key.mode)
            val dst = scaleSteps(mode)

            fun move(pc: Int): Int {
                val interval = Math.floorMod(pc - key.tonic, 12)
                val at = src.indexOf(interval)
                return if (at >= 0) Math.floorMod(key.tonic + dst[at], 12) else pc
            }

            val root = move(chord.root)
            val moved = HashSet<Int>()
            for (i in chord.intervals) moved += Math.floorMod(move(Math.floorMod(chord.root + i, 12)) - root, 12)
            val intervals = Chord.frozen(moved)
            val bass = chord.bass?.let(::move)
            if (root == chord.root && intervals == chord.intervals && bass == chord.bass) {
                chord
            } else {
                val quality = TheoryData.byIntervals[intervals]
                    ?: diatonicQuality(root, Key(key.tonic, mode), if (chord.intervals.size > 3) 4 else 3)
                Chord(root, quality, bass, if (quality == chord.quality) chord.shown else null)
            }
        }
    }

    /** The quality of the key's own chord of [size] notes (3 or 4), stacked in thirds on [root]; "" for a root
     * outside its scale or notes that name no quality. */
    fun diatonicQuality(root: Int, key: Key, size: Int): String {
        val steps = scaleSteps(key.mode)
        val interval = Math.floorMod(root - key.tonic, 12)
        val degree = steps.indexOf(interval)
        if (degree < 0) return ""
        val notes = HashSet<Int>()
        for (k in 0 until size) notes += Math.floorMod(steps[Math.floorMod(degree + 2 * k, 7)] - interval, 12)
        return TheoryData.byIntervals[Chord.frozen(notes)] ?: ""
    }

    private val alternativesKept = Lru<Triple<Chord, Key, Int>, List<Chord>>(4096)

    /**
     * Chords to play instead of [chord] that keep to [key], to change the feel: colours on the same root first, then
     * an inversion (or, for a slash chord, its root position), then chords on other roots that share the most notes,
     * a third below first. A copy: changing it changes nothing kept.
     */
    fun alternatives(chord: Chord, key: Key, limit: Int = 8): List<Chord> =
        ArrayList(alternativesKept.getOrPut(Triple(chord, key, limit)) { computeAlternatives(chord, key, limit) })

    private fun computeAlternatives(chord: Chord, key: Key, limit: Int): List<Chord> {
        val allowed = scale(key) + chord.pitchClasses
        val core = chord.intervals.mapTo(HashSet()) { Math.floorMod(chord.root + it, 12) }

        fun fits(candidate: Chord): Boolean {
            val pcs = candidate.pitchClasses
            return allowed.containsAll(pcs) && pcs != core && pcs.count { it in core } >= 2
        }

        val colours = TheoryData.colours.map { Chord(chord.root, it) }.filter(::fits).take(4)
        val turned = if (chord.bass != null) {
            listOf(Chord(chord.root, chord.quality, null, null, chord.tones))
        } else {
            val third = listOf(4, 3, 7, 5, 2).firstOrNull { it in chord.intervals }
            if (third == null) emptyList()
            else listOf(Chord(chord.root, chord.quality, Math.floorMod(chord.root + third, 12), null, chord.tones))
        }
        val others = ArrayList<Chord>()
        for (root in 0 until 12) {
            if (root == chord.root || root !in allowed) continue
            for (q in TheoryData.standIns) {
                val c = Chord(root, q)
                if (fits(c)) others += c
            }
        }
        others.sortWith(
            compareBy<Chord>(
                { c -> -c.pitchClasses.count { it in core } },
                { c -> c.intervals.size > 3 },
                { c -> TheoryData.thirds[Math.floorMod(c.root - chord.root, 12)] ?: 4 },
                { c -> TheoryData.standIns.indexOf(c.quality) },
            ),
        )
        val chosen = ArrayList(colours + turned)
        for (candidate in others) {
            if (chosen.size >= limit) break
            if (chosen.none { soundsAlike(candidate, it) }) chosen += candidate
        }
        return Collections.unmodifiableList(chosen)
    }

    /** Same notes, and the same lowest one, or both a symmetric chord: G#dim7 and Ddim7. */
    private fun soundsAlike(a: Chord, b: Chord): Boolean {
        if (a.pitchClasses != b.pitchClasses) return false
        if (a.quality in TheoryData.symmetric && b.quality in TheoryData.symmetric) return true
        return (a.bass ?: a.root) == (b.bass ?: b.root)
    }

    private fun open(key: Key): Boolean {
        TheoryData.open[key.mode]?.let { return key.tonic in it }
        val relative = Math.floorMod(key.tonic - scaleSteps("ionian")[modeIndex(key.mode)], 12)
        return relative in TheoryData.openNotes
    }

    private val hints = ConcurrentHashMap<Triple<Key, Int, Int>, List<Pair<Int, Key>>>()

    /**
     * Where to put a capo to play chords in [key] with open shapes: (fret, shapes' key), 0 for no capo; [key] is the
     * key of the chords as played with the capo on fret [capo] (0 for none). Nothing when the chords are open shapes
     * already; otherwise up to [limit] frets, lowest first, up to [MAX_CAPO] above the sheet's or lower. A copy.
     */
    fun capoHints(key: Key, limit: Int = 2, capo: Int = 0): List<Pair<Int, Key>> =
        ArrayList(hints.getOrPut(Triple(key, limit, capo)) {
            if (open(key)) emptyList()
            else {
                val sounds = sounding(key, capo).tonic
                val found = (0 until capo + TheoryData.maxCapo + 1).filter { it != capo }
                    .map { fret -> fret to Key(Math.floorMod(sounds - fret, 12), key.mode) }
                    .filter { open(it.second) }
                Collections.unmodifiableList(pySliceTo(found, limit))
            }
        })

    /** The key a song sounds in, played in [shapes] with the capo on fret [capo] (0 for none): E minor shapes with
     * capo 2 sound in F# minor. */
    fun sounding(shapes: Key, capo: Int): Key = Key(Math.floorMod(shapes.tonic + capo, 12), shapes.mode)

    /**
     * The key of the shapes played, from the key a tab names ([named], in its mode as [namedKey] reads it) for a sheet
     * with the capo on fret [capo], whose chords are [played]: when their key has the notes of the named key lowered
     * by the capo, the tab named the sound; otherwise, and with no capo or no chords to go by, the named key is the
     * shapes'.
     */
    fun shapesKey(named: Key, capo: Int, played: List<Chord>): Key {
        if (Math.floorMod(capo, 12) == 0) return named
        val lowered = Key(Math.floorMod(named.tonic - capo, 12), named.mode)
        val found = estimateKey(played)
        return if (found != null && scale(found) == scale(lowered)) lowered else named
    }

    // --- helpers ------------------------------------------------------------------------------------------------------

    /** A mode's steps; a mode no key has is Python's KeyError. */
    private fun scaleSteps(mode: String): List<Int> =
        TheoryData.scales[mode] ?: throw NoSuchElementException("no mode $mode")

    /** MODES.index(mode); a mode no key has is Python's ValueError. */
    private fun modeIndex(mode: String): Int =
        TheoryData.modes.indexOf(mode).takeIf { it >= 0 } ?: throw IllegalArgumentException("no mode $mode")

    /** list[i] as Python indexes: a negative [i] from the end. */
    private fun <T> pyIndex(list: List<T>, i: Int): T = list[if (i < 0) list.size + i else i]

    /** list[:n] as Python slices: a negative [n] all but the last -n. */
    private fun <T> pySliceTo(list: List<T>, n: Int): List<T> =
        if (n >= 0) list.take(n) else list.dropLast(minOf(-n, list.size))

    /** A least-recently-used cache of at most [size] answers, as functools.lru_cache keeps them. */
    private class Lru<K, V>(private val size: Int) {
        private val map = object : LinkedHashMap<K, V>(256, 0.75f, true) {
            override fun removeEldestEntry(eldest: MutableMap.MutableEntry<K, V>?): Boolean = this.size > this@Lru.size
        }

        fun getOrPut(key: K, make: () -> V): V {
            synchronized(map) { map[key]?.let { return it } }
            val value = make()
            synchronized(map) { map[key] = value }
            return value
        }
    }
}
