# A web-search fallback: designed, not built

caracole matches names offline, against the index of UG's sitemaps
(`match.py`). Since the tolerant steps (`word_title`, `typo_artist`,
`catch_all`), that finds most names that aren't quite UG's: "epic" - "I'm not
sorry for loving you" reviews as
`misc-musicals/epic-the-musical-not-sorry-for-loving-you`, the tab the owner
found by searching DuckDuckGo for the name and "ultimate guitar". What the
index still can't find is a song whose UG title shares too little with yours
(a translated title, a nickname), and a bare-id tab of an artist whose page
you haven't pasted. A web search finds both. This file says how caracole would
search, and why it doesn't yet.

## The rules it must keep

- **An official API, off by default, and no secret.** No search engine's
  result pages are scraped: they are no API, and caracole works around
  nothing. DuckDuckGo has no web-search API (its Instant Answer API returns
  no result links), so it is out. caracole keeps no secret (no credentials,
  no token file: the owner's choice), so an API that needs a key is out too,
  [Brave Search API](https://brave.com/search/api/) among them (its key in the
  `X-Subscription-Token` header; besides, its results may be stored only
  "with a plan that includes storage rights", and caracole caches every
  answer forever). One fits:
  - [SearXNG](https://docs.searxng.org/), self-hosted: `GET <url>/search?q=…&format=json`,
    once `json` is added to `search.formats` in its `settings.yml` (a stock
    instance answers 403). caracole talks only to your instance, which asks
    the engines you set it up for. It is reached on a network you trust, as
    caracole serve is, with no key.
- **Politeness**, as for every provider: a budget per run, one request at a
  time with a pause, a 403 or 429 cools it down (`health.record_block`), and
  every answer is cached.
- **Errors are never misses**: a failed or skipped search leaves the song as
  it was.
- **A web result is never an accept.** It is a candidate, step `web`, in a
  review, beside the others, for `caracole review` and the to-do page.

## Configuration

Off unless `[web_search]` names an instance:

```toml
[web_search]                          # off without a url
url = "https://searx.example.org"     # your SearXNG instance, with JSON on

[providers.web_search]                # the fourth provider
budget = 10                           # searches per run
delay = [2, 4]                        # seconds between two searches
```

On NixOS: `services.caracole.settings.web_search`.

## What it would do

1. **When**: in the match step, for a song the index can't settle (not found,
   or a review made only of the steps that never accept,
   `match.REVIEW_ONLY_STEPS`), once its artist's UG page, if known, has been
   tried; at most once per song in 90 days (kv `web:searched:<song id>`, its
   prefix in `songs._PER_SONG_KV`).
2. **Query**: `"<artist> <title>" ultimate guitar`, or
   `site:tabs.ultimate-guitar.com` where the engines SearXNG asks take it.
3. **Results**: only `https://tabs.ultimate-guitar.com/tab/…` addresses that
   robots.txt allows (`http.robots_disallows`), read for their tab id. A tab in
   the index becomes its UG song's candidate; a bare-id tab is read once
   through the run's UG client, as an `[artist_url]` tab page is, for its
   artist's page.
4. **Kept**: in kv `web:candidates:<song id>`, which the matcher adds to the
   song's candidates on every match, so they survive the nightly rematch;
   `[reject]` drops them as it drops any other.
5. **Shown**: in the song's review, on the to-do page, in `caracole review`
   and under "Did you mean" in `caracole add` and `caracole search`.

## Why not now

- The offline steps find the owner's example and the common cases at no
  request and no cost.
- A fourth provider touches config.py, http.py, health.py, the pipeline and
  the to-do page's provider table, and SearXNG needs an instance to run. Worth it once the to-do
  page shows songs the index keeps missing.
