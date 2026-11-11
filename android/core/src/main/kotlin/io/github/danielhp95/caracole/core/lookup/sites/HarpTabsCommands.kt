package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.sites.HarpArtistPage
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import java.math.BigInteger
import java.time.Instant

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

    /** stamps.shown: a time as the pages show it, `strftime("%Y-%m-%d %H:%M UTC")` of stamps' own text, as
     * LookupWords.until says one; "?" for none. */
    private fun shown(at: Instant?): String {
        if (at == null) return "?"
        val stamp = Stamps.of(at)  // 2026-11-04T14:00:00Z
        return stamp.substring(0, 10) + " " + stamp.substring(11, 16) + " UTC"
    }

    fun artist(c: CommandContext, artist: String): String {
        val off = "${NOT_READ}harptabs is off (caracole.toml). Nothing asked."
        val policy = PhoneConfig.read(c.db).provider(HarpTabsFetch.PROVIDER)
        if (!policy.enabled) return off
        val paths = HarpTabsFetch.artistPaths(c.db, artist)
        if (paths.isEmpty()) {
            return if (c.db.one("SELECT 1 FROM harptabs_index LIMIT 1") { true } == null) {
                "${NOT_READ}harptabs' index is empty; tonight's run reads its sitemap (or caracole harptabs --index)."
            } else {
                "Not found: harptabs lists no artist named $artist."
            }
        }
        val page: HarpArtistPage?
        when (val asked = c.asking.ask(HarpTabsFetch.PROVIDER) { client ->
            HarpTabsFetch.readArtist(c.db, client, paths[0], c.now)
        }) {
            is Asked.Done -> page = asked.value
            is Asked.Off -> return off
            is Asked.Cooling -> return "${NOT_READ}waiting out harptabs until ${shown(asked.until)}."
            is Asked.Blocked -> return "${NOT_READ}harptabs turned us back (${asked.error.message}); no asks until " +
                "${shown(asked.state.cooldownUntil)}."
            is Asked.Spent -> {
                val spent = if (asked.hour) "no more asks of harptabs this hour (${policy.lookupPerHour} spent)"
                            else "this fetch's ${policy.lookupRequests} asks of harptabs are spent"
                return "$NOT_READ$spent. Ask again later."
            }
            is Asked.Failed -> return "${NOT_READ}harptabs failed (${asked.error.message}). Try again later."
        }
        val sent = c.asking.requests[HarpTabsFetch.PROVIDER] ?: 0
        if (Health.answeredAny(c.db, Pace.lookupRunId(c.now), HarpTabsFetch.PROVIDER, sent)) {
            Health.recordOk(c.db, HarpTabsFetch.PROVIDER, c.now)
        }
        if (page == null) return "Not found: harptabs no longer has $artist's page."
        val listed = page.listed.size
        val lists = when {
            page.tabs > listed.toBigInteger() -> "$listed of their ${plural(page.tabs, "tab")}"
            listed > 0 -> "their ${plural(listed.toBigInteger(), "tab")}"
            else -> "no tab"
        }
        return "Read: harptabs' page of ${page.name} lists $lists."
    }

    /** report.plural: "1 tab", "98 tabs". */
    private fun plural(n: BigInteger, word: String): String = "$n $word" + if (n == BigInteger.ONE) "" else "s"
}
