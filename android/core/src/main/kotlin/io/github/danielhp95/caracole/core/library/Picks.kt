package io.github.danielhp95.caracole.core.library

/** overrides.LaCuerdaPick: a LaCuerda page picked for a song ([version] its `-N` page, null its first). */
data class LaCuerdaPick(val artist: String, val song: String, val version: Int? = null)

/** overrides.HarpTabsPick: a harptabs.com tab picked. */
data class HarpTabsPick(val tabId: Long, val slug: String)

/** overrides.GameTabsPick: a gametabs.net tab picked. */
data class GameTabsPick(val game: String, val slug: String)
