package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.sites.HarpArtistPage
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * `caracole harptabs --artist` on the phone (commands/lyrics.py's `_harptabs_artist`): one artist's page read into
 * harptabs.com's index now, at the lookup pace, once in 30 days, then what it lists said. Its index (`--index`) and
 * the bulk pass are the computer's.
 *
 * [artist] is the command's argument, its whitespace folded as the runner gives it: the artist's name, their page's
 * path (`artist/1178/billy-joel`, what caracole serve's Songs queue) or address, which HarpTabsFetch.artistPaths reads.
 * It returns its one line, which starts as `caracole lacuerda --artist`'s does and caracole serve's request line reads
 * (web/status.py): "Read: " (the page, in the index now, or read within 30 days), "Not found: " (no artist page by that
 * name, or one gone) or "Not read: " (the site turned off, its index empty, a cooldown, a block, a spent budget or an
 * error: nothing changed). A block and an error are the envelope's to record (`CommandContext.asking`); a read that
 * got an answer records the provider's good run, as Python's does.
 */
object HarpTabsCommands {
    /** commands/lyrics.py's NOT_READ. */
    const val NOT_READ = "Not read: "

    private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC)

    /** stamps.shown: a time as the pages show it, in UTC; "?" for none. */
    private fun shown(at: Instant?): String = at?.let(WHEN::format) ?: "?"

    fun artist(c: CommandContext, path: String): String {
        val off = "${NOT_READ}harptabs.com is off ([providers.harptabs] enabled = false); nothing was asked."
        val policy = PhoneConfig.read(c.db).provider(HarpTabsFetch.PROVIDER)
        if (!policy.enabled) return off
        val paths = HarpTabsFetch.artistPaths(c.db, path)
        if (paths.isEmpty()) {
            return if (c.db.one("SELECT 1 FROM harptabs_index LIMIT 1") { true } == null) {
                "${NOT_READ}harptabs.com's index is empty: the nightly run reads its sitemap, or caracole harptabs " +
                    "--index now."
            } else {
                "Not found: harptabs.com's sitemap lists no artist named $path."
            }
        }
        val page: HarpArtistPage?
        when (val asked = c.asking.ask(HarpTabsFetch.PROVIDER) { client ->
            HarpTabsFetch.readArtist(c.db, client, paths[0], c.now)
        }) {
            is Asked.Done -> page = asked.value
            is Asked.Off -> return off
            is Asked.Cooling -> return "${NOT_READ}harptabs.com is cooling down after a block until " +
                "${shown(asked.until)}; caracole won't ask it before then."
            is Asked.Blocked -> return "${NOT_READ}harptabs.com blocked caracole (${asked.error.message}); no more " +
                "requests to it until ${shown(asked.state.cooldownUntil)}."
            is Asked.Spent -> {
                val spent = if (asked.hour) "this hour's ${policy.lookupPerHour} lookup requests to harptabs.com are spent"
                            else "the lookup's ${policy.lookupRequests} requests to harptabs.com are spent"
                return "$NOT_READ$spent; ask again later."
            }
            is Asked.Failed -> return "${NOT_READ}harptabs.com failed (${asked.error.message}); nothing changed: try " +
                "again later."
        }
        val sent = c.asking.requests[HarpTabsFetch.PROVIDER] ?: 0
        if (Health.answeredAny(c.db, Pace.lookupRunId(c.now), HarpTabsFetch.PROVIDER, sent)) {
            Health.recordOk(c.db, HarpTabsFetch.PROVIDER, c.now)
        }
        if (page == null) return "Not found: harptabs.com no longer has the page of $path."
        val listed = page.listed.size
        val lists = when {
            page.tabs > listed -> "$listed of their ${plural(page.tabs, "tab")}"
            listed > 0 -> "their ${plural(listed.toLong(), "tab")}"
            else -> "no tab"
        }
        return "Read: harptabs.com's page of ${page.name} lists $lists, in the index now."
    }

    /** report.plural: "1 tab", "98 tabs". */
    private fun plural(n: Long, word: String): String = "$n $word" + if (n == 1L) "" else "s"
}
