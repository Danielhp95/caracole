package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key

/** harmony.Numeral: a chord's Roman numeral in its key, in parts; [text] puts them together. */
data class Numeral(val accidental: String, val roman: String, val quality: String, val extension: String,
                   val bass: String?, val of: String?) {
    /** "♭VII", "vii°7", "V7/V", "I/3", "V/V/3": a secondary chord's target first, then its bass. */
    val text: String get() = buildString {
        append(accidental).append(roman).append(quality).append(extension)
        if (of != null) append('/').append(of)
        if (bass != null) append('/').append(bass)
    }
}

/** harmony.Relation: what a chord does in its key: [kind] "in", "borrowed", "secondary", "leading" (a secondary
 * leading-tone chord) or "outside"; [source] the key a borrowed chord comes from ("C minor", "C Mixolydian"); [target]
 * the chord of the key a secondary chord belongs to, as named there ("G"). */
data class Relation(val kind: String, val source: String?, val target: String?)

/** harmony.Contained: a progression of CATALOGUE played within a longer section. */
data class Contained(val name: String, val times: Int, val numerals: List<String>, val key: String)

/** harmony.Progression: a section's progression, one cycle, its repeats folded. */
data class Progression(val numerals: List<String>, val repeats: Int, val name: String?, val ending: String?,
                       val variations: Int = 0, val contains: List<Contained> = emptyList())

/**
 * viewer/harmony.py: what each chord does in its key, on top of viewer.theory, answering as harmony.py does for
 * every chord, key and next chord (vectors/viewer/harmony_chords.jsonl): numerals, relations, families, the
 * explanation (the numeral's tooltip line), the glossary's lines, a chord's notes, the scale for a solo over it, the
 * key's scale and its pentatonic box ([HarmonyChords]); each section's progression, its key for searching and its name
 * from the catalogue, and numerals typed ([HarmonyProgressions], vectors/viewer/harmony_progressions.jsonl).
 *
 * harmony.py's docstring holds its rules, where music theory reads a chord two ways: B♭ in C is borrowed from C minor,
 * not C Mixolydian's ♭VII; D in C is V/V only going to G (C Lydian's II otherwise); C7 in C is V7/IV only going to an
 * F that is no dominant seventh (a blues's C7 F7 stays I7 IV7). A chord is read with the chord it goes to
 * ([goesTo]: the next on another root). Its tables are harmony.py's own, read from caracole/viewer/harmony.json.
 *
 * As in Python the answers are kept, chords, keys and these answers are frozen, and every list handed out is a copy.
 */
object Harmony {
    /** The chord's Roman numeral in [key]; [nextChord], the chord it goes to, tells a secondary chord. */
    fun numeral(chord: Chord, key: Key, nextChord: Chord? = null): Numeral = HarmonyChords.numeral(chord, key, nextChord)

    /** How the chord stands to [key]: in it, borrowed (and from where), a secondary dominant or leading-tone chord
     * (and the chord of the key it belongs to), or outside it. */
    fun relation(chord: Chord, key: Key, nextChord: Chord? = null): Relation =
        HarmonyChords.relation(chord, key, nextChord)

    /** "home", "away" or "pull" for a chord in the key, by its degree; null for one outside it. */
    fun family(chord: Chord, key: Key): String? = HarmonyChords.family(chord, key)

    /** The numeral's one line, naming the key it is read in: "vi: the 6th chord of C major, minor (lower case)". */
    fun explain(chord: Chord, key: Key, nextChord: Chord? = null): String = HarmonyChords.explain(chord, key, nextChord)

    /** (symbol, meaning, example) for each symbol the numerals of [chords] use, the notation's order, each with the
     * first of the song's chords that shows it ("G7 = V7"); [chords] in the order the sheet plays them. A copy. */
    fun glossary(chords: List<Chord>, key: Key): List<Triple<String, String, String>> =
        ArrayList(HarmonyChords.glossary(chords, key))

    /** The chord's notes with their intervals, low to high by degree: C7 is (C, R), (E, 3), (G, 5), (Bb, ♭7). A copy. */
    fun chordTones(chord: Chord, key: Key?): List<Pair<String, String>> = ArrayList(HarmonyChords.chordTones(chord, key))

    /** The scale for a solo over [chord] and its notes: ("D Dorian", [D, E, F, …]). A copy. */
    fun soloScale(chord: Chord, key: Key): Pair<String, List<String>> =
        HarmonyChords.soloScale(chord, key).let { (name, notes) -> name to ArrayList(notes) }

    /** The key's pitch classes, from its tonic up. */
    fun keyScale(key: Key): List<Int> = HarmonyChords.keyScale(key)

    /** The key's pentatonic box, from its tonic up: major (1 2 3 5 6) with a major third, else minor (1 ♭3 4 5 ♭7). */
    fun pentatonic(key: Key): List<Int> = HarmonyChords.pentatonic(key)

    /** harmony._goes_to: the chord each one goes to, the next on another root (D D7 G: both D chords go to G), null
     * for the last. */
    fun goesTo(chords: List<Chord>): List<Chord?> = HarmonyChords.goesTo(chords)

    /** Each section's progression, by its name, in the sheet's order: its chords as numerals, each read with the
     * next chord on the sheet (across sections), a chord held once, its cycle folded, its name from the catalogue,
     * the catalogue's progressions played within it and how it ends; a chord caracole can't read (null: N.C.) is left
     * out, and a section with no chord it can read has none. A copy. */
    fun progressions(sections: List<Pair<String, List<Chord?>>>, key: Key): List<Pair<String, Progression>> =
        ArrayList(HarmonyProgressions.progressions(sections, key))

    /** A progression's key for searching, the same in every key, turn and repeat: the numerals' roots ("Imaj7" is
     * "I", "V7/V" "V/V", "V7/IV" "I"), a chord held twice once, the cycle once, turned to start where its numerals
     * sort first: "vi IV I V" and "IV I V vi IV I V vi" are both "I V vi IV". */
    fun progressionKey(numerals: List<String>): String = HarmonyProgressions.progressionKey(numerals)

    /** [progressionKey] of numerals typed in one string ("vi IV I V", "vi–IV–I–V"). */
    fun progressionKey(text: String): String = HarmonyProgressions.progressionKey(text)

    /** The catalogue's name for numerals typed ("vi IV I V", "i VII VI V": [readTyped]), played whole, read in a major
     * key or in a minor one, as a section's is; null for none. */
    fun nameOf(numerals: List<String>): String? = HarmonyProgressions.nameOf(numerals)

    /** [nameOf] numerals typed in one string. */
    fun nameOf(text: String): String? = HarmonyProgressions.nameOf(HarmonyProgressions.typed(text))

    /** Numerals as typed, in harmony.py's notation: written in a minor key's own way ("i VII VI V"), a major III, VI or
     * VII is its ♭III, ♭VI or ♭VII; others as typed. A copy. */
    fun readTyped(text: String): List<String> = ArrayList(HarmonyProgressions.readTyped(HarmonyProgressions.typed(text)))

    /** [readTyped] of numerals already cut. A copy. */
    fun readTyped(numerals: List<String>): List<String> = ArrayList(HarmonyProgressions.readTyped(numerals))

    /** harmony.catalogue_keys: each reading of the catalogue's progressions by its progression key, every row on its
     * own tonic first, then read in a major key and in a minor one ({"I V vi IV": "the pop progression", "i ♭VI ♭III
     * ♭VII": "the pop progression", …}). A copy. */
    fun catalogue(): Map<String, String> = LinkedHashMap(HarmonyProgressions.catalogueKeys())
}
