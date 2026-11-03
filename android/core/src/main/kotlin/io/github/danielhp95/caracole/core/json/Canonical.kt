package io.github.danielhp95.caracole.core.json

import kotlinx.serialization.json.JsonElement

/** Canonical JSON, its digest and the stored-JSON hash (docs/superpowers/specs/2026-11-03-canonical-json.md; lane canonical). */
object Canonical {
    /** Object keys by code point. */
    val KEY_ORDER: Comparator<String> get() = TODO("lane canonical")

    /** C(v). */
    fun write(value: JsonElement): String = TODO("lane canonical")

    /** D(v): the lowercase hex SHA-256 of C(v)'s UTF-8. */
    fun digest(value: JsonElement): String = TODO("lane canonical")

    /** H(text), for versions.raw and songs.lyrics_json. */
    fun hashStoredJson(text: String?): String? = TODO("lane canonical")

    /** The strict reading: literals kept, the last duplicate wins; CanonicalError when not JSON. */
    fun parse(text: String): JsonElement = TODO("lane canonical")
    fun sha256Hex(bytes: ByteArray): String = TODO("lane canonical")
}

class CanonicalError(message: String) : Exception(message)
