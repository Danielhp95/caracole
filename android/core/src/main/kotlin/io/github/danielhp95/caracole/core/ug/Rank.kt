package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.ug.internal.rank.PyOrder

/** rank.Rated: anything UG rates by votes, a [Candidate] or a tab an artist page lists. */
interface Rated {
    val rating: Double
    val votes: Int
}

/** rank.Candidate: a version weighed; [score] is set by the rankings, as Python sets it on the very object. */
data class Candidate(val provider: String, val tabId: String, val kind: String, override val rating: Double,
                     override val votes: Int, val version: Int, val label: String? = null,
                     val coverage: Double? = null, var score: Double = 0.0, val versionId: Long? = null) : Rated

/**
 * rank.py, and versions.py's `complete` and `replaces_sheet`: lyric completeness first for sheets, then a Bayesian
 * rating, `(v·R + m·C) / (v + m)` with m = [RankPolicy.priorVotes] and C the vote-weighted mean of the song's
 * versions ([priorMean], Python's builtin sum of floats: Py.fsum), so a 5.0 from one vote doesn't beat a 4.8 from 270
 * (vectors/sites/ug_rank.jsonl, tests/test_conformance_rank.py).
 *
 * Every ranking is a stable sort on Python's tuple keys: a score compared as Python compares floats (−0.0 is 0.0),
 * ties broken on `(version, len(tab_id), tab_id)`, a length in code points and a tab id in code-point order.
 */
object Rank {
    /** rank.PARTIAL_LABELS: a version of a part of the song, penalized by [RankPolicy.labelPenalty]. */
    val PARTIAL_LABELS: Set<String> = setOf("intro", "solo", "outro", "riff", "lesson")

    /** rank.bayes: the rating shrunk toward [prior] by [m] votes; 0.0 when there is nothing to weigh. */
    fun bayes(rating: Double, votes: Int, prior: Double, m: Double): Double {
        val weight = votes + m
        return if (weight != 0.0) (votes * rating + m * prior) / weight else 0.0
    }

    fun bayes(rating: Double, votes: Int, prior: Double, m: Int): Double = bayes(rating, votes, prior, m.toDouble())

    /** rank.prior_mean: the vote-weighted mean rating of a song's versions, 0.0 when nobody voted. */
    fun priorMean(cands: List<Rated>): Double {
        var total = 0L
        for (c in cands) total += c.votes
        return if (total != 0L) Py.fsum(cands.map { it.votes * it.rating }) / total.toDouble() else 0.0
    }

    /** rank.rank_by_rating: by score alone (which sheets are worth scoring for coverage). */
    fun rankByRating(cands: List<Candidate>, policy: RankPolicy, variant: String? = null): List<Candidate> {
        val listed = cands.toList()
        score(listed, policy, variant)
        return listed.sortedWith(BY_SCORE)
    }

    /** rank.rank_guitar: text tabs rank by score alone, the partial labels' penalty in every score. */
    fun rankGuitar(cands: List<Candidate>, policy: RankPolicy, variant: String? = null): List<Candidate> =
        rankByRating(cands, policy, variant)

    /** rank.is_complete. */
    fun isComplete(c: Candidate, policy: RankPolicy): Boolean = complete(c.coverage, policy.coverageThreshold)

    /** versions.complete: a coverage known and at least [threshold]. */
    fun complete(coverage: Double?, threshold: Double): Boolean = coverage != null && coverage >= threshold

    /** rank.rank_sheets: complete sheets first, then by score; an unknown coverage is incomplete. */
    fun rankSheets(cands: List<Candidate>, policy: RankPolicy, variant: String? = null): List<Candidate> {
        val listed = cands.toList()
        score(listed, policy, variant)
        return listed.sortedWith(Comparator<Candidate> { a, b ->
            (!isComplete(a, policy)).compareTo(!isComplete(b, policy))
        }.then(BY_SCORE))
    }

    /**
     * versions.replaces_sheet: whether a sheet covering [new] of the lyrics replaces a kept one covering [kept]. A
     * complete sheet beats an incomplete one; of two incomplete ones the one covering more wins; an unknown coverage
     * never displaces a known one, nor a partial one an unknown one; a tie keeps the kept sheet.
     */
    fun replacesSheet(new: Double?, kept: Double?, threshold: Double): Boolean {
        if (complete(kept, threshold)) return false
        if (complete(new, threshold)) return true
        return new != null && kept != null && new > kept
    }

    /** rank._score: each candidate's Bayesian score, less the penalty of a partial label, plus the bonus of the
     * song's variant (an unplugged version is an acoustic one). */
    private fun score(cands: List<Candidate>, policy: RankPolicy, variant: String?) {
        val prior = priorMean(cands)
        val want = variant?.let(Normalize::canonicalVariant)
        for (c in cands) {
            var s = bayes(c.rating, c.votes, prior, policy.priorVotes)
            if (c.label in PARTIAL_LABELS) s -= policy.labelPenalty
            if (!want.isNullOrEmpty() && c.label?.let(Normalize::canonicalVariant) == want) s += policy.variantBonus
            c.score = s
        }
    }

    /** `(-c.score, c.version, len(c.tab_id), c.tab_id)`. */
    private val BY_SCORE: Comparator<Candidate> = Comparator { a, b ->
        PyOrder.floats(-a.score, -b.score).takeIf { it != 0 } ?: PyOrder.tiebreak(a, b)
    }
}
