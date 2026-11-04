package io.github.danielhp95.caracole.core.http

/**
 * http.py's errors and each site's, one declaration each (the plan's §5.1): a provider's error is never a miss
 * (AGENTS.md, "Errors are never misses"). [message] is Python's `str(e)`: the provider, the status, the URL and the
 * words, those present, joined by ": ".
 */
open class ProviderError(val provider: String, val url: String? = null, val status: Int? = null,
                         val msg: String? = null) : Exception(said(provider, url, status, msg)) {
    private companion object {
        fun said(provider: String, url: String?, status: Int?, msg: String?): String = buildList {
            add(provider)
            if (status != null) add(status.toString())
            if (!url.isNullOrEmpty()) add(url)
            if (!msg.isNullOrEmpty()) add(msg)
        }.joinToString(": ")
    }
}

/** A 403, a 429 or a challenge page: stop using the provider and back off. */
open class ProviderBlocked(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** Too many consecutive errors this run; the provider is skipped until the next run. */
open class ProviderUnavailable(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** A URL robots.txt disallows, asked for or redirected to: nothing is requested there, and no miss. */
open class RobotsClosed(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** This run's request budget for the provider is spent. Not an error and not a miss. */
class BudgetExhausted(val provider: String) : Exception("$provider: request budget for this run is spent")

/** ug/page.py's: a UG page whose embedded data can't be read. */
open class PageParseError(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** ug/fetch.py's: a cached page that doesn't parse, fetched again and still not parsing. */
class UnreadablePage(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    PageParseError(provider, url, status, msg)

/** lyrics.py's: an answer from LRCLIB that isn't the JSON it documents. */
class LrclibParseError(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** megalobiz.py's. */
class MegalobizParseError(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** azlyrics.py's. */
class AzLyricsParseError(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)

/** lacuerda.py's: provider "lacuerda". */
class LaCuerdaParseError(message: String, url: String? = null) : ProviderError("lacuerda", url = url, msg = message)

/** gtptabs.py's: provider "gtptabs". */
class GtpTabsParseError(message: String, url: String? = null) : ProviderError("gtptabs", url = url, msg = message)

/** harptabs.py's: provider "harptabs". */
class HarpTabsParseError(message: String, url: String? = null) : ProviderError("harptabs", url = url, msg = message)

/** gametabs.py's: provider "gametabs". */
class GameTabsParseError(message: String, url: String? = null) : ProviderError("gametabs", url = url, msg = message)

/** gtptabs_fetch.py's: downloads answered, several in a row, with a page instead of a file: the pass stops. */
class PagesNotFiles(provider: String, url: String? = null, status: Int? = null, msg: String? = null) :
    ProviderError(provider, url, status, msg)
