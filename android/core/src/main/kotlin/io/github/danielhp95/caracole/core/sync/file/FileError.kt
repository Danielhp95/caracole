package io.github.danielhp95.caracole.core.sync.file

/**
 * peer_file.FileError on the phone: a `.caracole` file refused, or one that can't be written, said in the owner's
 * words, the same on both sides (the sync redesign's §3.3).
 */
class FileError(message: String) : Exception(message) {
    companion object {
        const val NOT_A_FILE =
            "That isn't a file caracole exported: a .caracole file, or an index from caracole index export."
        const val OWN_EXPORT = "That file is this library's own export: a library takes nothing from itself. " +
            "caracole backup keeps copies of the computer's database to go back to."

        /** Why a song is left out of an export (Made.left). */
        const val CHANGED = "a file it keeps changed, or is gone, since caracole kept it"
        const val TOO_BIG = "a file it keeps is bigger than a file carries (64 MiB)"

        fun otherFormat(format: String) =
            "That file was made by another version of caracole (format $format): export it again with this one."

        fun older(name: String, day: String) = "Nothing in this file is newer than your sync with $name on $day."

        fun unreadable(why: String) = "That file can't be read whole ($why): export it again."
    }
}
