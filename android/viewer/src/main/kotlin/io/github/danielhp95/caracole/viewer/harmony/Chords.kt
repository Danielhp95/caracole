package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory

/**
 * harmony.py's chord half, line for line: how a chord is read in its key (`_read`: in it, secondary, a secondary
 * leading-tone chord, borrowed or outside), its numeral, relation and family, the explanation and the glossary's
 * lines in harmony.py's own words, a chord's notes spelled one letter a degree and the scale for a solo over it.
 * [Harmony] is its public face; harmony.py's module docstring holds the rules (B♭ in C is borrowed from C minor; D in
 * C is V/V only going to G; C7 in C is V7/IV only going to an F that is no dominant seventh), and each function here
 * is the one of the same name there.
 *
 * Its tables are harmony.py's ([HarmonyData]) and theory.py's ([Theory]); a token's number is read as Python's `int`
 * reads it ([PyInt]), a mode capitalized as `str.capitalize` does ([PyUnicode]). The answers asked most are kept as
 * Python's `functools` caches keep them, each one nothing can change; [Harmony] hands out copies.
 */
internal object HarmonyChords {
    private val ionian: List<Int> get() = Theory.SCALES.getValue("ionian")

    // --- words ---------------------------------------------------------------------------------------------------

    fun ordinal(n: Int): String = n.toString() + when (n) {
        1 -> "st"
        2 -> "nd"
        3 -> "rd"
        else -> "th"
    }

    /** _mode_word: "major", "minor", else the mode capitalized ("Dorian"). */
    fun modeWord(mode: String): String = HarmonyData.modeWords[mode] ?: PyUnicode.capitalize(mode)

    /** _key_words: "C major", "A minor", "C Mixolydian"; a key on [home]'s tonic spells it as [home] does. */
    fun keyWords(key: Key, home: Key? = null): String = Theory.spelling(home ?: key)[key.tonic] + " " + modeWord(key.mode)

    /** _degree: the degree (0–6) a pitch class is written as in [key], and its accidental against the tonic's major
     * scale. */
    fun degree(pc: Int, key: Key): Pair<Int, String> {
        val interval = Math.floorMod(pc - key.tonic, 12)
        val degree = Theory.DEGREES.getValue(if (4 in steps(key.mode)) "major" else "minor")[interval]
        val accidental = when (Math.floorMod(interval - ionian[degree] + 6, 12) - 6) {
            0 -> ""
            -1 -> "♭"
            1 -> "♯"
            else -> throw NoSuchElementException("no accidental for $interval")
        }
        return degree to accidental
    }

    /** SCALES[mode]; a mode no key has is Python's KeyError. */
    fun steps(mode: String): List<Int> = Theory.SCALES[mode] ?: throw NoSuchElementException("no mode $mode")

    // --- what a chord is -----------------------------------------------------------------------------------------

    private val shapes = Kept<Chord, HarmonyData.Shape>(4096)

    /** _shape: (lower case, sign, extension) of a chord's numeral. */
    fun shape(chord: Chord): HarmonyData.Shape = HarmonyData.shapes[chord.quality] ?: shapes.getOrPut(chord) {
        val q = chord.quality
        if (chord.tones == null || Theory.intervals(q) != chord.tones) {  // a suffix theory.py couldn't read
            HarmonyData.Shape(3 in chord.intervals && 4 !in chord.intervals, "", "")
        } else {
            val (lower, sign, rest) = when {
                q.startsWith("dim") -> Triple(true, "°", q.substring(3))
                q.startsWith("aug") -> Triple(false, "+", q.substring(3))
                q.startsWith("m") && !q.startsWith("maj") -> Triple(true, "", q.substring(1))
                else -> Triple(false, "", q)
            }
            HarmonyData.Shape(lower, sign, rest.replace("b", "♭").replace("#", "♯"))
        }
    }

    fun dominant(chord: Chord): Boolean {
        val iv = chord.intervals
        return 4 in iv && 11 !in iv && (8 !in iv || 10 in iv)
    }

    fun dominantSeventh(chord: Chord?): Boolean = chord != null && dominant(chord) && 10 in chord.intervals

    fun leading(chord: Chord): Boolean {
        val iv = chord.intervals
        return 3 in iv && 6 in iv && 4 !in iv && 7 !in iv
    }

    /** _holds: every note of the chord is in the key; in a minor key a chord on the fifth or seventh degree may raise
     * the sixth and seventh, and one on the tonic the seventh (i(maj7)). */
    fun holds(key: Key, chord: Chord): Boolean {
        var notes: Set<Int> = Theory.scale(key)
        if (key.mode == "aeolian") {
            val degree = Math.floorMod(chord.root - key.tonic, 12)
            if (degree == 7 || degree == 11) {
                notes = notes + setOf(Math.floorMod(key.tonic + 9, 12), Math.floorMod(key.tonic + 11, 12))
            } else if (degree == 0) {
                notes = notes + Math.floorMod(key.tonic + 11, 12)
            }
        }
        return notes.containsAll(chord.pitchClasses)
    }

    /** _borrows: the modes a key borrows from, the first asked first. */
    fun borrows(key: Key): List<String> {
        HarmonyData.borrows[key.mode]?.let { return it }
        val own = steps(key.mode).toSet()
        val others = Theory.MODES.filter { it != key.mode && it != "locrian" }
        return others.sortedWith(compareBy({ (own - steps(it).toSet()).size }, { Theory.MODES.indexOf(it) }))
    }

    /** _target: the chord of the key on [pc] a secondary chord can belong to, as (its numeral, its name): a major or
     * minor triad of the key, not the tonic's; a minor key's fifth degree is V, its dominant. */
    fun target(pc: Int, key: Key): Pair<String, String>? {
        if (pc == key.tonic || Math.floorMod(pc - key.tonic, 12) !in steps(key.mode)) return null
        var quality = Theory.diatonicQuality(pc, key, 3)
        if (quality != "" && quality != "m") return null
        val (degree, accidental) = degree(pc, key)
        if (key.mode == "aeolian" && degree == 4) quality = ""
        val roman = if (quality == "m") PyUnicode.lower(HarmonyData.romans[degree]) else HarmonyData.romans[degree]
        return (accidental + roman) to (Theory.spelling(key)[pc] + quality)
    }

    /** _Reading: how a chord is read; [target] is the pitch class of a secondary chord's target. */
    data class Reading(val kind: String, val source: Key? = null, val target: Int? = null)

    private val reads = Kept<Triple<Chord, Key, Chord?>, Reading>(8192)

    fun read(chord: Chord, key: Key, next: Chord?): Reading = reads.getOrPut(Triple(chord, key, next)) {
        reading(chord, key, next)
    }

    private fun reading(chord: Chord, key: Key, next: Chord?): Reading {
        val fifthBelow = Math.floorMod(chord.root + 5, 12)
        val resolves = next != null && next.root == fifthBelow
        if (holds(key, chord)) {
            // A dominant seventh of the key (not its own V, not on its tonic) going a fifth down to a chord of the
            // key: G7 C in A minor is V7/♭III.
            if (resolves && dominantSeventh(chord) && Math.floorMod(chord.root - key.tonic, 12) !in listOf(0, 7) &&
                target(fifthBelow, key) != null
            ) return Reading("secondary", null, fifthBelow)
            return Reading("in")
        }
        val source = borrows(key).map { Key(key.tonic, it) }.firstOrNull { holds(it, chord) }
        if (chord.root == key.tonic) {
            // A tonic dominant seventh going to IV (iv) is its V7, unless that is a dominant seventh too: C7 F is
            // V7/IV, a blues's C7 F7 stays I7 IV7.
            if (resolves && dominantSeventh(chord) && !dominantSeventh(next) && target(fifthBelow, key) != null) {
                return Reading("secondary", null, fifthBelow)
            }
        } else {
            for ((kind, step) in listOf("secondary" to 5, "leading" to 1)) {
                val fits = if (kind == "secondary") dominant(chord) else leading(chord)
                val at = Math.floorMod(chord.root + step, 12)
                if (fits && target(at, key) != null) {
                    val goes = next != null && next.root == at
                    if (goes || source == null) return Reading(kind, null, at)
                }
            }
        }
        if (source != null) return Reading("borrowed", source)
        return Reading("outside")
    }

    private fun secondary(reading: Reading): Boolean = reading.kind == "secondary" || reading.kind == "leading"

    // --- numerals and relations ----------------------------------------------------------------------------------

    /** _bass: the bass's degree above the chord's root, as a numeral writes it, for a slash chord. */
    fun bass(chord: Chord): String? {
        val b = chord.bass ?: return null
        if (b == chord.root) return null
        val interval = Math.floorMod(b - chord.root, 12)
        if (interval in chord.intervals) {
            val name = toneNames(chord).getValue(interval)
            return HarmonyData.inOctave[name] ?: name
        }
        return HarmonyData.bassDegrees[interval]
    }

    private val numerals = Kept<Triple<Chord, Key, Chord?>, Numeral>(8192)

    fun numeral(chord: Chord, key: Key, next: Chord?): Numeral = numerals.getOrPut(Triple(chord, key, next)) {
        val shape = shape(chord)
        val reading = read(chord, key, next)
        val bass = bass(chord)
        if (secondary(reading)) {
            val of = target(reading.target!!, key)!!.first
            Numeral("", if (reading.kind == "secondary") "V" else "vii", shape.sign, shape.extension, bass, of)
        } else {
            val (degree, accidental) = degree(chord.root, key)
            val roman = if (shape.lower) PyUnicode.lower(HarmonyData.romans[degree]) else HarmonyData.romans[degree]
            Numeral(accidental, roman, shape.sign, shape.extension, bass, null)
        }
    }

    fun relation(chord: Chord, key: Key, next: Chord?): Relation {
        val reading = read(chord, key, next)
        return when {
            secondary(reading) -> Relation(reading.kind, null, target(reading.target!!, key)!!.second)
            reading.kind == "borrowed" -> Relation("borrowed", keyWords(reading.source!!, key), null)
            else -> Relation(reading.kind, null, null)
        }
    }

    fun family(chord: Chord, key: Key): String? =
        if (!holds(key, chord)) null else HarmonyData.families[degree(chord.root, key).first]

    // --- words ---------------------------------------------------------------------------------------------------

    /** _tokens: an extension's parts ("maj7", "♭9", "sus4", "add9", "6"...). */
    fun tokens(extension: String): List<String> = PyRe.findall(HarmonyData.tokens, extension)

    fun tokenWords(token: String): String {
        HarmonyData.extensionWords[token]?.let { return it }
        val first = Py.slice(token, 0, 1)
        val rest = Py.slice(token, 1, null)
        if ((first == "♭" || first == "♯") && PyUnicode.allDigit(rest)) {
            return "a ${if (first == "♭") "lowered" else "raised"} ${ordinal(int(rest))}"
        }
        if (PyUnicode.allDigit(token)) return "a ${ordinal(int(token))}"
        return token
    }

    private fun qualityWords(chord: Chord, numeral: Numeral): String {
        val sign = numeral.quality
        var tokens = tokens(numeral.extension)
        val triad = if ((sign == "ø" || sign == "°") && tokens.take(1) == listOf("7")) {
            tokens = tokens.drop(1)
            if (sign == "ø") "half-diminished (ø7: diminished with a minor 7th)" else "diminished 7th (°7)"
        } else if (sign == "°") {
            "diminished (°)"
        } else if (sign == "+") {
            "augmented (+)"
        } else if (4 in chord.intervals) {
            "major (upper case)"
        } else if (3 in chord.intervals) {
            "minor (lower case)"
        } else {
            ""
        }
        val parts = tokens.joinToString(" and ") { "${tokenWords(it)} ($it)" }
        if (triad.isNotEmpty() && parts.isNotEmpty()) return "$triad with $parts"
        return triad.ifEmpty { if (parts.isNotEmpty()) "with $parts" else "" }
    }

    /** _chord_name: the chord as the glossary's example names it, its root spelled as its notes are. */
    private fun chordName(chord: Chord, key: Key, next: Chord?): String {
        val bass = chord.bass?.let { "/" + Theory.spelling(key)[it] } ?: ""
        return rootName(chord, key, read(chord, key, next)) + chord.suffix + bass
    }

    private val explained = Kept<Triple<Chord, Key, Chord?>, String>(8192)

    fun explain(chord: Chord, key: Key, next: Chord?): String = explained.getOrPut(Triple(chord, key, next)) {
        explanation(chord, key, next)
    }

    private fun explanation(chord: Chord, key: Key, next: Chord?): String {
        val found = numeral(chord, key, next)
        val reading = read(chord, key, next)
        val words = keyWords(key)
        val (degree, accidental) = degree(chord.root, key)
        val ordinal = ordinal(degree + 1)
        val where = when {
            reading.kind == "secondary" -> "the V of ${found.of} in $words"
            reading.kind == "leading" -> "the leading-tone chord of ${found.of} in $words"
            reading.kind == "in" -> "the $ordinal chord of $words"
            accidental.isNotEmpty() ->
                "on the ${if (accidental == "♭") "lowered" else "raised"} $ordinal degree of $words"
            else -> "on the $ordinal degree of $words"
        }
        val line = StringBuilder("${found.text}: $where")
        val quality = qualityWords(chord, found)
        if (quality.isNotEmpty()) line.append(", ").append(quality)
        val bass = chord.bass
        if (found.bass != null && bass != null) {
            val name = Theory.spelling(key)[bass]
            val interval = Math.floorMod(bass - chord.root, 12)
            if (interval in chord.intervals) {
                line.append("; $name in the bass, its ${ordinal(number(toneNames(chord).getValue(interval)))}")
            } else {
                line.append("; $name in the bass, the ${degreeWords(found.bass)} above its root, outside the chord")
            }
        }
        val target = reading.target?.let { target(it, key)!!.second }
        when {
            secondary(reading) -> {
                val goes = next != null && next.root == reading.target
                line.append("; ${if (goes) "leads" else "points"} to $target")
            }
            reading.kind == "borrowed" -> line.append("; borrowed from ${keyWords(reading.source!!, key)}")
            reading.kind == "outside" -> line.append("; outside $words")
        }
        return line.toString()
    }

    /** _degree_words: "3" is "3rd", "♭7" "lowered 7th", "♯4" "raised 4th". */
    fun degreeWords(label: String): String {
        val way = when (Py.slice(label, 0, 1)) {
            "♭" -> "lowered "
            "♯" -> "raised "
            else -> ""
        }
        return way + ordinal(int(label.trimStart('♭', '♯')))
    }

    /** _goes_to: the chord each one goes to, the next on another root (D D7 G: both D chords go to G). */
    fun goesTo(chords: List<Chord>): List<Chord?> {
        val after = ArrayList<Chord?>(chords.size)
        var upcoming: Chord? = null
        for (chord in chords.asReversed()) {
            after.add(if (upcoming != null && upcoming.root == chord.root) after[after.size - 1] else upcoming)
            upcoming = chord
        }
        after.reverse()
        return after
    }

    private val glossaries = Kept<Pair<List<Chord>, Key>, List<Triple<String, String, String>>>(1024)

    fun glossary(chords: List<Chord>, key: Key): List<Triple<String, String, String>> {
        val frozen = ArrayList(chords)
        return glossaries.getOrPut(frozen to key) { lines(frozen, key) }
    }

    private fun lines(chords: List<Chord>, key: Key): List<Triple<String, String, String>> {
        val tonic = Theory.spelling(key)[key.tonic]
        val words = keyWords(key)
        val found = LinkedHashMap<Pair<Int, String>, Triple<String, String, String>>()

        fun note(rank: Int, symbol: String, meaning: String, example: String) {
            found.putIfAbsent(rank to symbol, Triple(symbol, meaning, example))
        }

        for ((chord, after) in chords.zip(goesTo(chords))) {
            val n = numeral(chord, key, after)
            val example = "${chordName(chord, key, after)} = ${n.text}"
            note(0, "I–VII", "Roman numerals: the chord's root counted up the scale of $words, from its tonic, $tonic (I)",
                 example)
            if (n.of == null && n.quality != "+" && 4 in chord.intervals && !isLower(n.roman)) {
                note(1, "I", "upper case: a major chord", example)
            }
            if (isLower(n.roman) && n.quality == "") note(2, "i", "lower case: a minor chord", example)
            if (n.accidental.isNotEmpty()) {
                val way = if (n.accidental == "♭") "lower" else "higher"
                note(if (n.accidental == "♭") 3 else 4, n.accidental,
                     "a root a half step $way than that degree of $tonic major's scale", example)
            }
            if (n.quality == "°") note(5, "°", "diminished: a minor 3rd and a lowered 5th (°7: with a diminished 7th)", example)
            if (n.quality == "ø") note(6, "ø", "half-diminished: a diminished chord with a minor 7th (m7♭5)", example)
            if (n.quality == "+") note(7, "+", "augmented: a major 3rd and a raised 5th", example)
            for (token in tokens(n.extension)) {
                val meaning = HarmonyData.symbolMeanings[token]?.takeIf { it.isNotEmpty() } ?: ("with " + tokenWords(token))
                note(8, token, meaning, example)
            }
            if (n.bass != null) {
                note(9, "/" + n.bass, "a number after a slash: the bass note, the ${degreeWords(n.bass)} above the chord's root",
                     example)
            }
            if (n.of != null && n.roman == "V") {
                note(10, "V/x", "the V of x: a dominant leading to the chord x of the key (V/V leads to the V)", example)
            }
            if (n.of != null && n.roman == "vii") {
                note(11, "vii°/x", "the leading-tone chord of x, a half step below the chord x of the key", example)
            }
        }
        // stable: first seen first; kept as Python's _glossary keeps its tuple, so nothing changes what is kept
        return java.util.Collections.unmodifiableList(found.entries.sortedBy { it.key.first }.map { it.value })
    }

    /** str.islower of a numeral's roman, whose letters are ROMANS' ASCII ones (the generator checks they are): a cased
     * letter, none upper case. */
    private fun isLower(s: String): Boolean = s.any { it in 'a'..'z' } && s.none { it in 'A'..'Z' }

    // --- notes and scales ----------------------------------------------------------------------------------------

    private val names = Kept<Chord, Map<Int, String>>(4096)

    /** _tone_names: each interval of the chord by its name: "R", "♭3", "5", "♭7", "9"... */
    fun toneNames(chord: Chord): Map<Int, String> = names.getOrPut(chord) {
        val iv = chord.intervals
        val seventh = 10 in iv || 11 in iv
        val third = 3 in iv || 4 in iv
        val diminished = 3 in iv && 6 in iv && 7 !in iv && !seventh

        fun name(i: Int): String = when (i) {
            0 -> "R"
            1 -> if (seventh) "♭9" else "♭2"
            2 -> if (seventh || third) "9" else "2"
            3 -> if (4 in iv) "♯9" else "♭3"
            4 -> "3"
            5 -> if (third) "11" else "4"
            6 -> if (7 in iv) "♯11" else "♭5"
            7 -> "5"
            8 -> if (7 in iv) "♭13" else "♯5"
            9 -> if (diminished) "♭♭7" else if (seventh) "13" else "6"
            10 -> "♭7"
            11 -> "7"
            else -> throw NoSuchElementException("no interval $i")
        }

        val out = LinkedHashMap<Int, String>()
        for (i in iv) out[i] = name(i)
        java.util.Collections.unmodifiableMap(out)
    }

    /** _named: [letter] with the sharps or flats that make it sound [pc]: E# and Cb stay, a double one is "##" or
     * "bb". */
    private fun named(letter: Char, pc: Int): String {
        val step = Math.floorMod(pc - Theory.NATURAL.getValue(letter.toString()) + 6, 12) - 6
        return letter + if (step > 0) "#".repeat(step) else "b".repeat(-step)
    }

    private fun letterIndex(letter: Char): Int =
        Theory.LETTERS.indexOf(letter).takeIf { it >= 0 } ?: throw IllegalArgumentException("no letter $letter")

    /** _letter_name: the note [number] letters up from [rootName] (1 is the root), sounding [pc]. */
    private fun letterName(rootName: String, number: Int, pc: Int): String =
        named(Theory.LETTERS[Math.floorMod(letterIndex(rootName[0]) + number - 1, 7)], pc)

    /** _doubles: how many double sharps or flats the chord's notes, then the scale's ([steps], a scale of seven),
     * need when spelled up from [rootName]. */
    private fun doubles(rootName: String, chord: Chord, steps: List<Int>): Pair<Int, Int> {
        val tones = toneNames(chord).count { (i, label) ->
            Py.len(letterName(rootName, number(label), Math.floorMod(chord.root + i, 12))) > 2
        }
        val notes = if (steps.size != 7) 0 else steps.withIndex().count { (n, s) ->
            Py.len(letterName(rootName, n + 1, Math.floorMod(chord.root + s, 12))) > 2
        }
        return tones to notes
    }

    /** _root_name: the chord's root as its notes are spelled from (harmony.py's docstring: "Notes"). */
    private fun rootName(chord: Chord, key: Key?, reading: Reading?, steps: List<Int> = emptyList()): String {
        val spelled = Theory.spelling(key)
        var first = spelled[chord.root]
        if (key != null && reading != null && secondary(reading)) {
            val target = spelled[reading.target!!][0]
            val letter = Theory.LETTERS[Math.floorMod(letterIndex(target) + if (reading.kind == "secondary") 4 else 6, 7)]
            val name = named(letter, chord.root)
            if (Py.len(name) <= 2) first = name
        }
        val candidates = listOf(first) + listOf(Theory.SHARPS[chord.root], Theory.FLATS[chord.root]).filter { it != first }
        var best = candidates[0]
        var fewest = doubles(best, chord, steps)
        for (candidate in candidates.drop(1)) {  // the first of the best, as min() keeps it
            val count = doubles(candidate, chord, steps)
            if (compareValuesBy(count, fewest, { it.first }, { it.second }) < 0) {
                best = candidate
                fewest = count
            }
        }
        return best
    }

    fun number(label: String): Int = if (label == "R") 1 else int(label.trimStart('♭', '♯'))

    /** int() of a token's or a label's digits, as Python reads them; where Python raises ValueError, so does this. */
    private fun int(digits: String): Int =
        (PyInt.parse(digits) ?: throw NumberFormatException("invalid literal for int(): '$digits'")).intValueExact()

    private val tones = Kept<Pair<Chord, Key?>, List<Pair<String, String>>>(4096)

    fun chordTones(chord: Chord, key: Key?): List<Pair<String, String>> = tones.getOrPut(chord to key) {
        val root = if (key == null) {
            rootName(chord, null, null)
        } else {
            rootName(chord, key, read(chord, key, null), intervalsOf(scaleFor(chord, key)))
        }
        val found = toneNames(chord).map { (interval, label) -> label to interval }.toMutableList()
        val bass = chord.bass
        if (bass != null) {
            val interval = Math.floorMod(bass - chord.root, 12)
            if (interval !in chord.intervals) found.add(HarmonyData.bassDegrees[interval] to interval)
        }
        found.sortWith(compareBy({ number(it.first) }, { it.second }))
        java.util.Collections.unmodifiableList(found.map { (label, interval) ->
            letterName(root, number(label), Math.floorMod(chord.root + interval, 12)) to label
        })
    }

    /** _by_quality: the scales for a chord by its quality, best first. */
    private fun byQuality(chord: Chord): List<String> {
        val iv = chord.intervals
        return when {
            3 in iv && 6 in iv && 7 !in iv ->
                if (9 in iv) listOf("diminished (whole-half)", "locrian") else listOf("locrian", "diminished (whole-half)")
            4 in iv && 8 in iv && 7 !in iv -> listOf("whole-tone")
            4 in iv && 10 in iv -> listOf("mixolydian", "diminished (half-whole)", "whole-tone")
            4 in iv -> listOf("ionian", "lydian", "mixolydian", "diminished (half-whole)")
            3 in iv -> listOf("dorian", "aeolian", "phrygian", "melodic minor")
            else -> listOf("mixolydian", "ionian", "lydian")
        }
    }

    fun intervalsOf(name: String): List<Int> =
        Theory.SCALES[name] ?: HarmonyData.otherScales[name] ?: throw NoSuchElementException("no scale $name")

    private val scales = Kept<Pair<Chord, Key>, Pair<String, List<String>>>(4096)

    fun soloScale(chord: Chord, key: Key): Pair<String, List<String>> = scales.getOrPut(chord to key) {
        val name = scaleFor(chord, key)
        val steps = intervalsOf(name)
        val root = rootName(chord, key, read(chord, key, null), steps)
        val notes = if (steps.size == 7) {
            steps.mapIndexed { i, s -> letterName(root, i + 1, Math.floorMod(chord.root + s, 12)) }
        } else {  // no letter a degree: in sharps from a sharp root, in flats from a flat one
            val spelled = if ("#" in root) Theory.SHARPS else if ("b" in root) Theory.FLATS else Theory.spelling(key)
            listOf(root) + steps.drop(1).map { spelled[Math.floorMod(chord.root + it, 12)] }
        }
        "$root ${if (name in Theory.SCALES) modeWord(name) else name}" to java.util.Collections.unmodifiableList(notes)
    }

    private val scaleNames = Kept<Pair<Chord, Key>, String>(4096)

    /** _scale_for: the name of the scale [soloScale] gives: a mode or one of _OTHER_SCALES. */
    private fun scaleFor(chord: Chord, key: Key): String = scaleNames.getOrPut(chord to key) {
        val reading = read(chord, key, null)
        val candidates = ArrayList<String>()
        val home = if (reading.kind == "in") key else reading.source
        if (home != null) {
            val interval = Math.floorMod(chord.root - home.tonic, 12)
            val index = steps(home.mode).indexOf(interval)
            if (index >= 0) candidates.add(Theory.MODES[Math.floorMod(Theory.MODES.indexOf(home.mode) + index, 7)])
            if (home.mode == "aeolian" && interval == 7) candidates.add("Phrygian dominant")
        }
        if (reading.kind == "secondary") candidates.add("mixolydian")
        candidates += byQuality(chord)
        val pcs = chord.pitchClasses.map { Math.floorMod(it - chord.root, 12) }.toSet()
        candidates.firstOrNull { intervalsOf(it).containsAll(pcs) } ?: candidates[0]
    }

    fun keyScale(key: Key): List<Int> = steps(key.mode).map { Math.floorMod(key.tonic + it, 12) }

    fun pentatonic(key: Key): List<Int> {
        val degrees = if (4 in steps(key.mode)) listOf(0, 1, 2, 4, 5) else listOf(0, 2, 3, 4, 6)
        val scale = keyScale(key)
        return degrees.map { scale[it] }
    }
}

/** A least-recently-used cache of at most [size] answers, as functools.lru_cache keeps them. */
internal class Kept<K, V>(private val size: Int) {
    private val map = object : LinkedHashMap<K, V>(256, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<K, V>?): Boolean = this.size > this@Kept.size
    }

    fun getOrPut(key: K, make: () -> V): V {
        synchronized(map) { map[key]?.let { return it } }
        val value = make()
        synchronized(map) { map[key] = value }
        return value
    }
}
