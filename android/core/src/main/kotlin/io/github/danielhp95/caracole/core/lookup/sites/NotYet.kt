package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.StageEnd

/** A site's stage or lookup command before its lane lands: skipped, and said so. */
internal object NotYet {
    const val WORDS = "not on the phone yet"
    const val COMMAND = "Not on the phone yet."
    val STAGE = StageEnd("skipped", WORDS)
}
