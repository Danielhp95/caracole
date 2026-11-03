package io.github.danielhp95.caracole.core

/**
 * A neutral answer, until [lane] writes the real one: what a function the running app reaches returns while its lane
 * hasn't landed (an empty list, null, a refusal), so the app and the device tests run before every lane is in. Each
 * call names its lane, so searching the sources for the word stub followed by ("lane lists what is still neutral; a
 * lane replaces its calls with the real body, and none is left once every lane has merged.
 */
@Suppress("UNUSED_PARAMETER")
inline fun <T> stub(lane: String, neutral: () -> T): T = neutral()
