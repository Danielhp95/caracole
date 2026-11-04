package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.testing.WebJson
import kotlinx.serialization.json.JsonElement

// What the search routes' tests share, now :server's testFixtures' (server.testing's SearchApp, PageCards and WebJson,
// which WebReplay replays the web vectors with on the JVM and the device), under the names these tests know.

/** server.testing.PageCards: a song's card with the members the vectors mask. */
internal val PageCards: SongCards get() = io.github.danielhp95.caracole.server.testing.PageCards

/** server.testing.SearchApp: the search routes over a fixture of the search corpus. */
internal typealias SearchApp = io.github.danielhp95.caracole.server.testing.SearchApp

/** WebJson.masked: what a song's card says of its folder's files, `"*"`. */
internal fun masked(value: JsonElement): JsonElement = WebJson.masked(value)

/** WebJson.difference: where [actual] first differs from [expected], as the corpus compares JSON. */
internal fun difference(expected: JsonElement, actual: JsonElement, at: String = "$"): String? =
    WebJson.difference(expected, actual, at)
