package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.viewer.shapes.Instrument
import io.github.danielhp95.caracole.viewer.theory.Key

/** version.Swap: a chord played instead of one, its root, suffix and bass, before any move. */
data class Swap(val root: Int, val suffix: String, val bass: Int?)

/**
 * version.Version: where a song is played, as the viewer keeps it: [t] semitones from the sheet as written, [mode]
 * and [capo] (null: the sheet's), [at] a chord's chosen shape by its index, [alt] by mode a chord played instead of
 * one by its index, [inst] the instrument (null: the guitar). A value, compared by what it holds.
 */
data class Version(val t: Int = 0, val mode: String? = null, val capo: Int? = null, val at: Map<Int, Int> = emptyMap(),
                   val alt: Map<String, Map<Int, Swap>> = emptyMap(), val inst: String? = null)

/** version.Setting: a songbook's setting for a song, the one type :core's songbooks and the viewer share. */
typealias Setting = io.github.danielhp95.caracole.core.songbooks.Setting

/** version.Frets: a shape, each string's fret from the nut, low E first, null where it isn't played. */
typealias Frets = List<Int?>

/** version.KeyVersion: a `[version]` kept by its key, its swaps and shapes by their chords' names. */
data class KeyVersion(val key: Key, val mode: String? = null, val capo: Int? = null,
                      val alt: List<Pair<String, String>> = emptyList(), val at: List<Pair<String, Frets>> = emptyList(),
                      val inst: String? = null)

/** viewer/version.py's page side and render.own_version (lane version-progressions). */
object Versions {
    fun fromQuery(q: String): Version = TODO("lane version-progressions")
    fun query(v: Version): String = TODO("lane version-progressions")
    fun keyVersion(text: String): KeyVersion? = TODO("lane version-progressions")
    fun inKey(kept: KeyVersion, cho: String, key: Key?, capoSheet: Int?): Version = TODO("lane version-progressions")
    fun entry(v: Version, cho: String, key: Key?, capoSheet: Int?): String? = TODO("lane version-progressions")
    fun inSetting(own: Version, setting: Setting?, shapes: Key?, capoSheet: Int?): Version =
        TODO("lane version-progressions")
    /** version.setting_problem: what is wrong with a setting's parts as given (any type, as a form or a file gives
     * them), or null. */
    fun settingProblem(key: Any? = null, mode: Any? = null, capo: Any? = null, instrument: Any? = null): String? =
        TODO("lane version-progressions")
    fun playedKey(v: Version, key: Key?, capoSheet: Int?): Pair<Key?, Int> = TODO("lane version-progressions")
    /** version.version_label. */
    fun label(v: Version, key: Key?, capoSheet: Int?): String = TODO("lane version-progressions")
    fun playedLabel(v: Version, key: Key?, capoSheet: Int?): String = TODO("lane version-progressions")
    fun forInstrument(v: Version, inst: Instrument): Version = TODO("lane version-progressions")
    /** render.own_version: the song's own version on its sheet [cho]. */
    fun ownVersion(overrides: Overrides, song: SongRow, cho: String, key: String?, keySource: String? = null): Version =
        TODO("lane version-progressions")
}
