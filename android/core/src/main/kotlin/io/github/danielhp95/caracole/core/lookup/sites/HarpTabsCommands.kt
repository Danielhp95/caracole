package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.lookup.CommandContext

/** `caracole harptabs --artist` on the phone (lane harptabs). Neutral: says it isn't yet. */
object HarpTabsCommands {
    fun artist(c: CommandContext, path: String): String = NotYet.COMMAND
}
