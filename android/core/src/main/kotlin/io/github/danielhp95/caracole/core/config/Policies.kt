package io.github.danielhp95.caracole.core.config

/**
 * config.py's policies, field for field (data/caracole/config/config.json holds their defaults): a site's two paces
 * ([ProviderPolicy]: bulk work's `budget` and `delay`, a lookup's `lookupDelay`, `lookupRequests` and
 * `lookupPerHour`, a day's `perDay`), the matcher's thresholds ([MatchPolicy]) and the ranking's ([RankPolicy]).
 */
data class ProviderPolicy(val budget: Long, val delay: Pair<Double, Double>, val enabled: Boolean = true,
                          val lookupDelay: Pair<Double, Double> = 0.125 to 0.375, val lookupRequests: Int = 6,
                          val lookupPerHour: Int = 60, val perDay: Int? = null)

data class MatchPolicy(val accept: Double = 90.0, val margin: Double = 8.0, val review: Double = 75.0,
                       val artistGate: Double = 90.0)

data class RankPolicy(val coverageThreshold: Double = 0.8, val lineMatch: Int = 85, val priorVotes: Int = 10,
                      val scoredSheets: Int = 3, val labelPenalty: Double = 0.5, val variantBonus: Double = 0.25)
