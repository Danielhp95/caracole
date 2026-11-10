package io.github.danielhp95.caracole.server.jobs

/**
 * The phone's own job kinds, which Python never queues, their key, names, stage and words, one table that JobViews
 * reads (AGENTS.md records them as the phone's; the plan's §5.3): the render job (the phone's pages made again by a
 * new build, or after a take), a file shared to the app filed, a backup made and one restored. Each line's `{…}`
 * blanks are filled by whoever queues or runs the job ([fill]).
 */
object PhoneKinds {
    /** A kind: its job's key prefix, its [title] and [display] (JobSpec's), its one stage (name, label), and its lines
     * while it runs, once done (and [otherwise], a second way it may end well) and failed. */
    data class Kind(val kind: String, val key: String, val title: String, val display: String,
                    val stage: Pair<String, String>, val running: String, val done: String, val failed: String,
                    val otherwise: String? = null)

    val RENDER = Kind("render", "render:", "Remake the pages", "The phone's pages", "render" to "Making the pages",
                      "Remaking pages · {done} of {total}", "Pages remade · {n} songs",
                      "Pages not made: {why}")
    val INBOX = Kind("inbox", "inbox:", "File {name}", "{name}", "file" to "Filing", "Filing {name}…",
                     "Filed · {name} of {song}", "Not filed: {why}", otherwise = "Waiting for its song: {name}")
    val BACKUP = Kind("backup", "backup:", "Back up the book", "A backup ({label})", "backup" to "Backing up",
                      "Backing up the book…", "Backed up ({label})", "Not backed up: {why}")
    val RESTORE = Kind("restore", "restore:", "Restore the book of {date}", "The book of {date}",
                       "restore" to "Restoring", "Restoring the book…", "Restored the book of {date}",
                       "Not restored: {why}")

    val ALL: Map<String, Kind> = listOf(RENDER, INBOX, BACKUP, RESTORE).associateBy { it.kind }

    /** [line] with each `{name}` blank filled from [values]; a blank no value names is left as it is. */
    fun fill(line: String, vararg values: Pair<String, Any>): String =
        values.fold(line) { text, (name, value) -> text.replace("{$name}", value.toString()) }
}
