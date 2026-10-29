"""The library page's Sites tab: each website caracole reads, what it has from it, and what keeps it out.

One line a site (``SITES``, icons.SOURCES' order less the audio model and the inbox, which are no site): what it is
for, robots.txt in a sentence, the closed paths worth naming with what each closes, and its terms where the owner
chose to read it all the same (AGENTS.md's two exceptions, harptabs.com and gametabs.net, and YouTube). Those words
are written here by hand; the paths are caracole's own table's (``http.ROBOTS_DISALLOW``, pinned to each live
robots.txt by tests), so the page never names a rule caracole doesn't keep. YouTube is the one site whose named paths
aren't in that table: caracole goes against them, by the owner's choice, and its sentence says so.

Everything here is read from the database, the config and caracole's tables: the tab sends no request, and building
the page asks none.
"""

from __future__ import annotations

from dataclasses import dataclass

from caracole.http import ROBOTS_DISALLOW


@dataclass(frozen=True)
class Site:
    """A website caracole reads: ``key`` as icons.SOURCES names it (its name and icon are there), what it is
    for, its home's domain, the hosts whose robots rules are its, robots.txt in words, the closed paths named with
    what each closes, its terms note, and, for a site with no index, how it is asked instead."""

    key: str
    role: str
    domain: str
    hosts: tuple[str, ...]
    robots: str
    paths: tuple[tuple[str, str], ...] = ()
    terms: str | None = None
    asked: str | None = None


SITES: tuple[Site, ...] = (
    Site("ug", "Chord sheets and text tabs", "ultimate-guitar.com",
         ("www.ultimate-guitar.com", "tabs.ultimate-guitar.com"),
         "Closes its search, downloads and print pages. caracole matches songs against its sitemap, on your machine.",
         (("/search.php", "its search"), ("/tab/download", "downloads"), ("/tab/print?", "print pages"),
          ("/download/public/", "public downloads"))),
    Site("lacuerda", "Spanish-language chord sheets", "acordes.lacuerda.net", (),
         "Its robots.txt is empty: nothing is closed. caracole keeps its own pace all the same."),
    Site("lrclib", "Lyrics, many synced to the music", "lrclib.net", (),
         "An API with no robots rules: nothing is closed to caracole.", asked="Asked song by song"),
    Site("gtptabs", "Guitar Pro files", "gtptabs.com", ("gtptabs.com",),
         "Closes its Russian half, its search and its storage (an artist's “Download all”).",
         (("/ru/", "the Russian half of the site"), ("/search/", "its search"),
          ("/storage/", "“Download all” archives"))),
    Site("musescore", "Scores, as links you open yourself", "musescore.com", ("musescore.com",),
         "Closes its API, downloads, search and embeds. caracole reads only its sitemaps.",
         (("/api/jmuse", "its API"), ("/score/*/download/*", "downloads"), ("/sheetmusic?", "its search"),
          ("/oembed/*", "embeds"))),
    Site("harptabs", "Harmonica tabs", "harptabs.com", ("www.harptabs.com", "harptabs.com"),
         "Closes its search, its API and its app's data. Artist and tab pages are open.",
         (("/search", "its search"), ("/api/", "its API"), ("/*?*_rsc=", "the app's data requests")),
         terms="Its terms forbid copying. Kept by your choice: one tab a song, privately."),
    Site("gametabs", "Video-game music tabs", "gametabs.net", ("gametabs.net", "www.gametabs.net"),
         "Closes its API, its filters and every download behind a login. Its robots.txt asks for 5 s between "
         "requests; caracole asks once a second, by your choice.",
         (("/api/", "its API"), ("/tabs?*", "filtered lists"),
          ("/preparing-tab-file-download", "downloads (a login's)")),
         terms="Its terms forbid bots. Read by your choice since 28 Oct 2026."),
    Site("youtube", "Audio for auto-chords", "youtube.com", (),
         "Closes /results and /youtubei/, which yt-dlp uses: caracole goes against them, by your choice.",
         (("/results", "search results"), ("/youtubei/", "the player's API")),
         terms="The one site caracole goes against robots.txt for: a few of your songs a night.",
         asked="Searched song by song"),
)


def more_paths(site: Site) -> int:
    """How many paths caracole's robots table closes for ``site``'s hosts beyond those it names."""
    every = {path for host in site.hosts for path in ROBOTS_DISALLOW.get(host, ())}
    return len(every - {path for path, _ in site.paths})
