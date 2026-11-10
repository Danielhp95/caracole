package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory

/** version.Swap: a chord played instead of one, its root, suffix and bass, before any move. */
data class Swap(val root: Int, val suffix: String, val bass: Int?)

/**
 * version.Version: where a song is played, as the viewer keeps it: [t] semitones from the sheet as written, [mode]
 * and [capo] (null: the sheet's), [at] a chord's chosen shape by its index, [alt] by mode a chord played instead of
 * one by its index, [inst] the instrument (null: the guitar). A value, compared by what it holds (a map's order is
 * none of it, as a dict's isn't); [Versions.query] writes [alt]'s modes in the order the map gives them, as Python
 * writes a dict's, so a version read keeps them in the order its address named them.
 */
data class Version(val t: Int = 0, val mode: String? = null, val capo: Int? = null, val at: Map<Int, Int> = emptyMap(),
                   val alt: Map<String, Map<Int, Swap>> = emptyMap(), val inst: String? = null)

/** version.Setting: a songbook's setting for a song, the one type :core's songbooks and the viewer share. */
typealias Setting = io.github.danielhp95.caracole.core.songbooks.Setting

/** version.Frets: a shape, each string's fret from the nut, low E first, null where it isn't played. */
typealias Frets = List<Int?>

/**
 * version.KeyVersion: a song's own version kept by the key it plays in, as Make this my version writes overrides.toml's
 * `[version]` (`key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6`): [key], the key of the shapes played in the
 * mode the sheet's chords were read in; [mode], a mode chosen to play it in, null for that key's own; [capo], null for
 * the sheet's; [alt] each chord as the version names it, then the chord played in its place; [at] each chord as the
 * version names it, then that shape's frets; [inst] the instrument, null for the guitar. [Versions.inKey] plays it on
 * a sheet; [query] writes it, and [Versions.keyVersion] reads it back.
 */
data class KeyVersion(val key: Key, val mode: String? = null, val capo: Int? = null,
                      val alt: List<Pair<String, String>> = emptyList(), val at: List<Pair<String, Frets>> = emptyList(),
                      val inst: String? = null) {
    /** KeyVersion.query: the entry as caracole writes it, each part left out where it says nothing; in a chord's
     * name "%", "&", "=", ",", "." and whitespace escaped ("C6%2E9"), the rest as it is. */
    fun query(): String {
        val params = listOf(
            "key" to Theory.keyName(key), "mode" to mode, "capo" to capo?.toString(),
            "alt" to alt.joinToString(",") { (a, b) -> "${Versions.escape(a)}.${Versions.escape(b)}" },
            "at" to at.joinToString(",") { (name, frets) -> "${Versions.escape(name)}.${Versions.fretsText(frets)}" },
            "inst" to inst,
        )
        return params.filter { !it.second.isNullOrEmpty() }.joinToString("&") { (name, value) -> "$name=$value" }
    }

    /** KeyVersion.label: the version in words, as [Versions.label] names it on the sheet it was made on ("G Dorian,
     * capo 0"; "G Major, capo 2, ukulele"; on an instrument with no capo, the key of the shapes: "G Major, piano"). */
    fun label(): String {
        val played = Key(key.tonic, mode?.takeIf { it.isNotEmpty() } ?: key.mode)
        var words = "${Theory.spelling(played)[played.tonic]} ${Versions.modeName(played.mode)}"
        val inst = Versions.instrumentOf(inst) ?: Versions.guitar
        if (capo != null && inst.capo) words = "$words, capo $capo"
        return if (inst.id == Versions.guitar.id) words else "$words, ${Versions.instrumentWords(inst)}"
    }
}
