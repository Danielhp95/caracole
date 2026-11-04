package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy

/** rank.Candidate: a version weighed. */
data class Candidate(val provider: String, val tabId: String, val kind: String, val rating: Double, val votes: Int,
                     val version: Int, val label: String? = null, val coverage: Double? = null, var score: Double = 0.0,
                     val versionId: Long? = null)

/** rank.py, and versions.replaces_sheet. */
object Rank {
    fun bayes(rating: Double, votes: Int, prior: Double, m: Int): Double = TODO("lane rank-coverage")
    fun priorMean(cands: List<Candidate>): Double = TODO("lane rank-coverage")
    fun rankByRating(cands: List<Candidate>, policy: RankPolicy, variant: String? = null): List<Candidate> =
        TODO("lane rank-coverage")
    fun isComplete(c: Candidate, policy: RankPolicy): Boolean = TODO("lane rank-coverage")
    fun rankSheets(cands: List<Candidate>, policy: RankPolicy, variant: String? = null): List<Candidate> =
        TODO("lane rank-coverage")
    fun replacesSheet(new: Double?, kept: Double?, threshold: Double): Boolean = TODO("lane rank-coverage")
}
