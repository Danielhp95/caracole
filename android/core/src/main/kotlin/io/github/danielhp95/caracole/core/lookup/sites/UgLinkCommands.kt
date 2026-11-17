package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.ug.LinkRead
import io.github.danielhp95.caracole.core.ug.UgLink
import io.github.danielhp95.caracole.core.ug.UgLinks
import java.io.File

/**
 * `caracole ug --link URL [--progress]` on the phone (commands/ug.py, its work ug/link.py's, [UgLinks]): a UG link
 * pasted into the library page's search box read now, an interactive lookup at the lookup pace within a lookup's
 * budget: a tab link's page, then its artist's page; an artist link's page alone.
 *
 * A link caracole knows already (its tab's song, or its artist's page read), one of a type caracole keeps nothing of,
 * and one UG answered 404 for are said with no request ([UgLinks.knownLine]). A cooldown, a block, a spent budget and
 * an error say so: the envelope (`CommandContext.asking`) records a block and an error, as the computer's command does;
 * a provider's error is the link's failure too, remembered for an hour (kv `ug:link-failed`), in which the page doesn't
 * send it by itself again. With the tab known, a block or an error on its artist's page is UG's still, recorded as the
 * computer records it, never the link's failure; a read that went forgets the link's failure. Its last line starts with
 * what UG answered, which caracole serve's request line shows (web/status.py): "Read: ", "Not found: " or "Not read: "
 * (nothing changed).
 *
 * With [progress], a progress line a stage (get.py's, [LookupWords.stageLine]), `tab` and `artist`, as
 * `caracole ug --link --progress` writes them: the first stage running, then the read's own, and the one running at
 * the end ended with the last line as its detail. [cacheDir] is the HTTP cache the known state reads (`cfg.cache_dir`);
 * [overrides] reads overrides.toml once the first stage runs, as `load_ovr` does (its refusal the caller's).
 */
object UgLinkCommands {
    const val NOT_READ = "Not read: "

    fun link(c: CommandContext, config: PhoneConfig, cacheDir: File, overrides: () -> Overrides, link: UgLink,
             progress: Boolean): String {
        var at = if (link.kind == UgLink.TAB) "tab" else "artist"  // the stage running: the one the last line ends
        fun stage(name: String, state: String, detail: String = "") {
            at = name
            if (progress) c.say(LookupWords.stageLine(name, state, detail))
        }
        fun end(line: String, state: String = "skipped"): String {
            stage(at, state, line)
            return line
        }

        stage(at, "running", "asking Ultimate Guitar")
        val block = overrides().block  // read once the first stage runs, as load_ovr is
        val was = UgLinks.known(config, c.db, cacheDir, link, c.now)
        if (was.state in setOf("found", "other", "gone")) return end(UgLinks.knownLine(c.db, was), "done")
        if (Health.isCooling(c.db, UgLinks.PROVIDER, c.now)) {
            return end("${NOT_READ}waiting out UG until ${UgLinks.shown(Health.state(c.db, UgLinks.PROVIDER).cooldownUntil)}.")
        }
        if (was.state == "spent") return end("$NOT_READ${was.why}. Ask again later.")
        val asked = c.asking.ask(UgLinks.PROVIDER) { client ->
            UgLinks.read(c.db, client, c.now, block, link) { name, state, detail -> stage(name, state, detail) }
        }
        val p = config.provider(UgLinks.PROVIDER)
        val done: LinkRead = when (asked) {
            is Asked.Done -> asked.value
            is Asked.Off -> return end("$NOT_READ${asked.why}.")
            is Asked.Cooling -> return end("${NOT_READ}waiting out UG until ${UgLinks.shown(asked.until)}.")
            is Asked.Blocked -> return end("${NOT_READ}UG turned us back (${asked.error.message}); no asks until " +
                                           "${UgLinks.shown(asked.state.cooldownUntil)}.")
            is Asked.Spent -> {
                val spent = if (asked.hour) "no more asks of UG this hour (${p.lookupPerHour} spent)"
                            else "this lookup's ${p.lookupRequests} asks of UG are spent"
                return end("$NOT_READ$spent. Ask again later.")
            }
            is Asked.Failed -> {
                // not sent by the page by itself for an hour
                UgLinks.recordFailure(c.db, link.url, c.now, asked.error.message.orEmpty())
                return end("${NOT_READ}UG failed (${asked.error.message}). Try again later.")
            }
        }
        // The tab known, its artist's page stopped: a block or an error is UG's still, never the link's failure.
        when (val stopped = done.stopped) {
            is ProviderBlocked -> Health.recordBlock(c.db, UgLinks.PROVIDER, c.now, stopped.message.orEmpty())
            is ProviderError -> Health.recordError(c.db, UgLinks.PROVIDER, c.now, stopped.message.orEmpty())
            is BudgetExhausted, null -> {
                val sent = c.asking.requests[UgLinks.PROVIDER] ?: 0
                if (Health.answeredAny(c.db, Pace.lookupRunId(c.now), UgLinks.PROVIDER, sent)) {
                    Health.recordOk(c.db, UgLinks.PROVIDER, c.now)
                }
            }
            else -> {}
        }
        val line = UgLinks.said(done)
        if (!line.startsWith(NOT_READ)) UgLinks.forgetFailure(c.db, link.url, c.now)
        return end(line, if (line.startsWith(NOT_READ)) "skipped" else "done")
    }
}
