package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.CommandContext

/** `caracole versions --keep` and `--keep-more` on the phone (lane ug-fetch-artist). Neutral: says it isn't yet. */
object VersionsCommands {
    fun keep(c: CommandContext, song: SongRow, tab: Long): String = NotYet.COMMAND
    fun keepMore(c: CommandContext, song: SongRow): String = NotYet.COMMAND
}
