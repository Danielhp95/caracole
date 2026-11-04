package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonElement

/** overrides.Overrides, field for field: the phone's overrides.toml (`phone_overrides`) read as Python reads it. */
data class Overrides(
    val alias: Map<String, List<String>> = emptyMap(),
    val match: Map<String, Pair<String, String>> = emptyMap(),
    val artistUrl: Map<String, String> = emptyMap(),
    val pin: Map<String, List<Long>> = emptyMap(),
    val transpose: Map<String, Int> = emptyMap(),
    val ignore: Set<String> = emptySet(),
    val block: Set<Long> = emptySet(),
    val pinUrls: Map<String, List<String>> = emptyMap(),
    val reject: Map<String, Set<Pair<String, String>>> = emptyMap(),
    val artistUrlNames: Map<String, String> = emptyMap(),
    val youtube: Map<String, String?> = emptyMap(),
    val lacuerda: Map<String, LaCuerdaPick> = emptyMap(),
    val harptabs: Map<String, HarpTabsPick> = emptyMap(),
    val gametabs: Map<String, GameTabsPick> = emptyMap(),
    val azlyrics: Map<String, String> = emptyMap(),
    val version: Map<String, String> = emptyMap(),
    val harmonica: Map<String, Map<String, JsonElement>> = emptyMap(),
    val tables: Set<String> = emptySet(),
) {
    companion object {
        fun read(db: Db): Overrides = TODO("lane overrides-model")
    }
}
