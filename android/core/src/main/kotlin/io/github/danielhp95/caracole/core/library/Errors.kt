package io.github.danielhp95.caracole.core.library

/**
 * library.SharedFolder: a file `keep_file` won't write, as another song keeps a file at its place (two songs whose
 * names make one folder). Nothing is written or recorded: the [other] song's file stays, and the [song] waits.
 */
class SharedFolder(val song: SongRow, val other: SongRow, val name: String) :
    Exception("${song.display}'s $name isn't kept: ${other.display} shares its folder (their names make one), and " +
                  "its $name is there")

/** overrides.OverridesError: an entry that can't be read or written; the message says why. */
class OverridesError(message: String) : Exception(message)
