package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.CommandContext

/** `caracole lacuerda --artist` and `--search` on the phone (lane lacuerda-sheets). Neutral: says it isn't yet. */
object LaCuerdaCommands {
    fun artist(c: CommandContext, artist: String, first: String?): String = NotYet.COMMAND
    fun search(c: CommandContext, query: String, auto: Boolean): String = NotYet.COMMAND
}
