package io.github.danielhp95.caracole.viewer.theory

import java.util.Collections
import java.util.TreeSet

/**
 * A chord, theory.py's frozen `Chord`: [root] and [bass] are pitch classes (0 for C up to 11 for B), [quality] a
 * key of [Theory.QUALITIES] (or the normalized suffix of a chord outside it, whose intervals are then in [tones]).
 *
 * [shown] is the suffix as the sheet wrote it ("M7" for a maj7), kept for display; null for a chord the viewer made
 * up, which shows its quality.
 *
 * Frozen as Python's: every field is a `val`, and [tones] is a copy of the set given, which nothing can change. It
 * compares and hashes by its five fields, as the dataclass does, so it keys a cache; `copy` and the components are
 * a data class's.
 */
class Chord(
    val root: Int,
    val quality: String,
    val bass: Int? = null,
    val shown: String? = null,
    tones: Set<Int>? = null,
) {
    val tones: Set<Int>? = tones?.let(::frozen)

    /** Its intervals above the root: [tones], else its quality's. */
    val intervals: Set<Int> by lazy(LazyThreadSafetyMode.PUBLICATION) {
        this.tones ?: Theory.QUALITIES[quality] ?: throw NoSuchElementException("no quality $quality")
    }

    /** Its notes' pitch classes, its bass among them. */
    val pitchClasses: Set<Int> by lazy(LazyThreadSafetyMode.PUBLICATION) {
        val pcs = TreeSet<Int>()
        for (i in intervals) pcs += Math.floorMod(root + i, 12)
        if (bass != null) pcs += bass
        Collections.unmodifiableSet(pcs)
    }

    /** The suffix to show: as written, or the quality's usual spelling. */
    val suffix: String get() = shown ?: Theory.DISPLAY[quality] ?: quality

    fun copy(
        root: Int = this.root,
        quality: String = this.quality,
        bass: Int? = this.bass,
        shown: String? = this.shown,
        tones: Set<Int>? = this.tones,
    ): Chord = Chord(root, quality, bass, shown, tones)

    operator fun component1(): Int = root
    operator fun component2(): String = quality
    operator fun component3(): Int? = bass
    operator fun component4(): String? = shown
    operator fun component5(): Set<Int>? = tones

    override fun equals(other: Any?): Boolean =
        this === other || other is Chord && root == other.root && quality == other.quality && bass == other.bass &&
            shown == other.shown && tones == other.tones

    override fun hashCode(): Int {
        var h = root
        h = 31 * h + quality.hashCode()
        h = 31 * h + (bass ?: -1)
        h = 31 * h + (shown?.hashCode() ?: 0)
        return 31 * h + (tones?.hashCode() ?: 0)
    }

    override fun toString(): String = "Chord(root=$root, quality=$quality, bass=$bass, shown=$shown, tones=$tones)"

    internal companion object {
        /** A set no one can change, in order (a copy of [of]). */
        fun frozen(of: Collection<Int>): Set<Int> = Collections.unmodifiableSet(TreeSet(of))
    }
}

/** A key, theory.py's frozen `Key`: a [tonic] (a pitch class) and a [mode], one of [Theory.MODES]: C major is
 * `Key(0, "ionian")`. */
data class Key(val tonic: Int, val mode: String)
