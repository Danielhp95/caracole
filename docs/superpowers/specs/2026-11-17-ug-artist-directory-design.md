# An Ultimate Guitar artist directory

Status: proposed on 2026-11-17, for the owner to approve or turn down. Nothing is built. It is the other half of
docs/superpowers/plans/2026-11-17-ug-link.md (branch `feat/ug-link`), which reads a UG link the owner pastes. This
spec finds an artist when there is no link.

## Why

UG's sitemaps list about a tenth of its tabs (210,676 on 2026-10-18) by a bare `/tab/{id}`, with no artist or title.
Every tab of an artist whose name has a non-ASCII letter is listed that way (docs/spike-2026-10-18.md, "The full
sitemap set"). Only UG's artist pages name those tabs. caracole reads an artist page (ug/artist_tabs.py) only for a
song of the library whose artist page it knows, from `[artist_url]` or learned from a slugged tab, which such an
artist doesn't have. So a search for 斑马斑马 or 宋冬野 finds nothing until the owner pastes an address. On the owner's
service, 6 artist pages have been read in all.

An artist page's address needs UG's numeric id (`/artist/joaquin_sabina` is a 404, `/artist/634073` is 宋冬野's), and
no sitemap names an artist. UG's letter listings do.

## What UG has (checked 2026-11-17)

- **The sitemap index** has no artist sitemap. It holds tab sitemaps (1–41, last, ukulele1–4), news, longreads,
  reviews, wiki, courses, lessons, books and forum threads.
- **robots.txt**, `User-agent: *`, allows `/bands/` and `/artist/`. It closes `/search.php` to everyone, and `/explore`
  to Bingbot and msnbot alone.
- **The listings** are `/bands/<letter>.htm`, then `/bands/<letter><N>.htm` for page N (`s2.htm` … `s293.htm`). There
  are 27: a–z, and `0-9`. `0-9` holds names that begin with a digit or a symbol, and every name whose first letter
  isn't A–Z: Кино, Édith Piaf, Đorđe Balašević. "The Beatles" is under T.
- **A page's `div.js-store`** holds `store.page.data`:
  - `alpha`, `current_page`, `page_count`, `artists_count`, `tabs_per_page` (50);
  - `artists`, 50 a page, each `{id, name, tabscount, artist_url, tabs_last_update_timestamp, localized_name}`.
    `tabscount` counts every type, Guitar Pro and bass included. `localized_name` equalled `name` in every row seen;
  - `last_tabs`, the letter's 10 newest tabs.
- **The order is popularity**, not name, id or `tabscount`. Page 1 of S starts with Simon & Garfunkel, then Sal
  Priadi (55 tabs). Its last page holds artists of 1–5 tabs in no visible order.
- **A bare `artist_url` (`/artist/{id}`) means a name with a non-ASCII letter**: true of all 423 rows seen (Кино,
  Måneskin, Beyoncé, The Marías, Sŵnami). Those are the artists whose tabs the sitemaps list bare. They make up about
  2% of a letter's first page, and 34 of the 50 on `0-9`'s first page.
- **`artists_count` is approximate.** S's last page holds 23 artists where the count implies 25.
- **No validators.** The pages carry no `ETag` or `Last-Modified`, and Cloudflare marks them `DYNAMIC`, so a refresh
  costs a full request a page. A page is about 16 KB on the wire and as gzip in caracole's cache (86 KB of HTML).

### The probes

Eight requests, 6 s or more apart, all with caracole's user agent. Every answer was a 200 with no challenge:

| # | Page | What it said |
|---|---|---|
| 1 | `/bands/s2.htm` | page 2 of S: 50 artists, none of page 1's |
| 2 | `/bands/0-9.htm` | 5,179 artists, 104 pages; 34 of 50 named in Cyrillic or with an accent, each with a bare address |
| 3 | `/bands/s293.htm` | S's last page: 23 artists of 1–5 tabs; one with a bare address (Sŵnami) |
| 4 | `/bands/t.htm` | 15,989 artists, 320 pages, "The …" among them |
| 5 | `/bands/a.htm` | 12,354, 248 pages |
| 6 | `/bands/m.htm` | 13,097, 262 pages (Måneskin and Michael Bublé bare) |
| 7 | `/bands/j.htm` | 10,609, 213 pages |
| 8 | `/bands/b.htm` | 9,727, 195 pages (Beyoncé and bôa bare) |

With S (14,625, 293 pages, read earlier that day), seven listings hold 81,580 artists on 1,635 pages. The other 20
letters are estimated from the share of artist keys under each initial in the owner's index: **about 175,000 artists
on about 3,500 pages**. Of those, **about 6,000–10,000 have a bare address**: roughly 2–4% of the letters' artists,
and half to two thirds of `0-9`'s.

## What it buys

1. **A search finds an artist by name.** 宋冬野, Song Dongye or Joaquín Sabina gets an artist row even though their
   page was never read: "Song Dongye (宋冬野) · 42 tabs on UG · Read their page on UG · up to 2 requests". The button
   is the UG link lookup run on the artist's address (`POST /ug/link`, `caracole ug --link=<address>`). Once it has
   read the page, their songs show as any read artist's do. "Up to N" comes from the lists that read asks for (chords,
   then tabs, 100 a page): `min(lookup_requests, 2 + tabs // 100)`.
2. **The nightly match finds a wanted song's artist page** with no `[artist_url]` and no slugged tab. ug/fetch.py's
   `_known_artist_page` and `artist_is_known` take the directory as one more source, after `[artist_url]` and the
   learned kv. Where the directory names the artist, the fetch saves the `LEARN_TRIES` tab reads too.
   - Namesakes: a whole-name match beats a part match, and among equals the most tabs win. A `[artist_url]` still
     decides, and the title match on the page (`TITLE_MATCH`) guards against the wrong artist.
   - The to-do page's "Artists to find on Ultimate Guitar" goes once the directory is complete. While it is being
     read, the section lists only artists whose letter isn't read whole yet, as LaCuerda's `unread_letter` does.
     After that, an artist the directory lacks is said to be on no UG listing, and review notes stop saying "find
     the artist's page".
3. **Optionally, a title-only search finds a bare artist's songs**, through a second pass that reads their pages
   (see "The second pass").

The directory names no song. A search by title alone ("斑马斑马") gains nothing from it without the second pass or
the link.

## The table

Schema 16 (or the next free number when this is built; feat/ug-link adds none), `ug_directory`:

| Column | What |
|---|---|
| `artist_id` | UG's id, the primary key |
| `name` | as UG writes it: "Song Dongye (宋冬野)" |
| `slug` | its page's slug, `''` for a bare page; the address is `artist_page_address`'s (`/artist/{slug}_{id}` or `/artist/{id}`) |
| `letter`, `place` | its listing ("S", "0-9"), and its place there when last seen: popularity, to rank namesakes |
| `tabs`, `updated_at` | `tabscount` and `tabs_last_update_timestamp` (as a stamp) |
| `artist_key` | filed as artist_tabs.py files a page: the index's key where its slug is one (`simon-garfunkel`), else `slug_key(name)` (`song-dongye-宋冬野`), so the directory, `ug_index` and `ug_artist_tabs` meet on one key |
| `forms` | `normalize.name_forms`, hyphenated and written together, Chinese in pinyin too, for the `LIKE` prefilter |
| `seen_at` | when a listing last showed it |

- The names' words join the artist vocabulary (`ug_artist_words`, by triggers that state no conflict clause), so
  "Did you mean" suggests them.
- After a `KEY_VERSION` bump, `ensure_current_keys` rebuilds `artist_key` and `forms` from the names with no request.
  Identity keys fold Traditional characters to Simplified, as everywhere else.
- kv `ug:directory:letters` holds each letter's `page_count`, `artists_count`, the round's start, its next page and
  when its last whole round ended; the round's ids are the rows whose `seen_at` is since its start.
  kv `ug:directory:keys` holds the key version.
- Size: about 25 MB for 175,000 rows. The owner's UG index export is 176 MB today.

## How it is read

`ug/directory.py` (`directory_pass`) is modelled on `harptabs_index.artist_pass` and `gametabs_index.game_pass`, and
`ug/bands.py` reads a listing page.

- **Order**: each letter's first 10 pages first, then the letters one by one. The first 270 requests give every
  letter's 500 most popular artists. Every request is the client's, with its budget and pauses. A pass the budget
  ends goes on from the same page the next night.
- **Each page** is stored in one savepoint: its artists upserted, `seen_at` moved on. The page's own `page_count`
  marks the letter's end, so no page past the end is asked for.
- **A listing never removes an artist.** An absence is no miss: the order moves between nights, and the count is
  approximate. Only a 404 from the artist's own page removes them (`artist_tabs.forget`, and the row goes).
- **Refresh**: a letter is read again D days after its last round began (the owner's choice, below). Each page is
  cached until then, as every answer is.
- **Popularity order over many nights**: between two nights, artists move across page boundaries. A letter read
  across nights can miss one who moved up into a page already read, and see twice one who moved down. So:
  - a round counts the distinct ids it saw against `artists_count`, and `caracole index stats` says the gap;
  - the next round finds those it missed;
  - a first read made in one evening drifts least.
  How much the tail's order moves is not known yet (open question 1).
- **Commands**:
  - `caracole ug --directory [--budget N]`: bulk work. It is a `builds_index` word, refused on a machine whose service
    uses another database.
  - The nightly run's ug step makes one pass after the fetch, with the directory's own budget.
  - `caracole index stats` and the Sites tab say how far it has got ("UG's listings: 41,200 of about 175,000 artists,
    9 of 27 letters").

## The second pass (optional)

This is the owner's question: read the pages of the artists the sitemaps list only by bare ids, so that a title-only
search finds their songs.

- **Which artists**: rows with a bare address (`slug = ''`) whose page caracole hasn't read, or read before their
  `updated_at`. Most `tabs` first.
- **How**: each page is read as the link reads one (ug/fetch.py's lists, chords then tabs, 100 a page,
  `artist_tabs.store`, `keep_only` for a list read whole). Only names are read, never a tab page.
- **Upkeep**: a page is read again only when its row's `tabs` or `updated_at` moved after the read, and never within
  30 days (`ARTIST_PAGE_MAX_AGE`). Most of the tail never changes.
- **Command**: `caracole ug --bare-artists [--budget N]`, and the nightly step after the directory, with a budget of
  its own.
- **Limit**: an ASCII-named artist's accented titles stay unseen ("De Música Ligera" by Soda Stereo). The nightly
  fetch reads that artist's page for a song of yours, and a pasted link covers the rest.

The estimate, until the first read gives the exact count: about 1.5 requests an artist (one or two lists), plus one
for each further 100 tabs of a kind.

| Scope | Requests | Nights at 60 | Nights at 120 |
|---|---|---|---|
| The 1,000 bare artists with most tabs | about 3,000 | 50 | 25 |
| The 3,000 with most | about 6,500 | 110 | 55 |
| All, about 6,000–10,000 artists | about 10,000–17,000 | 170–280 | 85–140 |

Reading a single unfiltered list would halve a small artist's cost (one request in place of two). The plan may
choose that.

## The costs, as choices

The first read is about 3,500 requests: at 2.5–5 s apart, about 4 hours of pauses.

| How | Requests a night | Pauses a night | Nights to finish |
|---|---|---|---|
| By hand, once: `caracole ug --directory --budget 3600` | 3,600 once | about 4 h | 1 |
| A budget of its own, 240 | 240 | 15 min | 15 |
| A budget of its own, 120 | 120 | 7.5 min | 30 |
| What UG's 60 leaves after the fetch (it varies; say 20–40) | 20–40 | 1–2.5 min | 90–175 |

Upkeep, once read: a whole re-read every D days, since there are no validators.

| D | Requests a night |
|---|---|
| 30 days | about 117 |
| 90 days | about 40 |
| 180 days | about 20 |

A suggestion, the owner's to change:

- the first read by hand, in one evening;
- then 90 days, with a directory budget of 40;
- the second pass on the 1,000 bare artists with most tabs, at 60 a night.

That is about 160 UG requests a night (60 + 40 + 60) for 50 nights, then about 100.

## Politeness: what changes, what holds

What changes, all in AGENTS.md's Politeness:

- **Bulk work** gains the listings and, if chosen, the bare artists' pages.
- **"Budgets per run: `ug` 60"** gains the directory's own budget and the second pass's, unless the owner picks
  "what the 60 leaves".
- **"Bare-id tabs … its URL from `[artist_url]` or learned"** gains "or the directory".
- **The Sites tab and the to-do page** change their words for UG.

What holds:

- **One provider, `ug`**: one pace (2.5–5 s), one request at a time, one `http:last_request:ug`, the lock handed to
  a waiting lookup in every pause, one cooldown. A block in the directory pass cools UG for the fetch and lookups too,
  with one alert for a streak's first block.
- **robots.txt**: only `/bands/` and `/artist/`, both open to `*`; never `/search.php` or `/explore`.
- **How it asks**: caracole's own user agent, no login, nothing worked around.
- **The cache**: every 200 and 404 kept, a listing page asked for again only after D days.
- **Errors are never misses**: a page that won't parse is an error, and so is one cut short (`alpha` or
  `current_page` not the one asked for, or fewer than 50 artists before the last page). The round goes on from that
  page the next night, and no artist goes.
- **A search asks no site**: the directory is read locally. "Read their page on UG" is pressed by hand: the link's
  lookup, within `lookup_per_hour`, never sent by Enter or by itself.
- **The phone** reads no listing.

## The phone and the sync

- `index_transfer.SITES["ug"]` gains `ug_directory` and the two kv records. A merge takes a row whose `seen_at` is
  later, and a letter's record moves on, never back. So `caracole index export` and `merge`, a `.caracole` file's
  indexes, `GET /api/peer/index` and the sync's Site indexes carry the directory with UG's index, about 25 MB more.
  It is not in `index_transfer.PAGES`: a lookup never reads a listing.
- The schema bump moves the phone in lockstep (migrations.json, `Database.SCHEMA_VERSION`). core.index's merge
  follows the rule above, and core.search reads the table as search.py does, held to it by the corpus's search and
  merge vectors.
- The listing parser has no Kotlin port. The phone's "Read their page on UG" is the ug-link lane's `UgLinkRoutes`,
  and its reads are noted for the index push as artist pages already are.

## Alternatives, and why not

- **Wikidata's "Ultimate Guitar artist ID" (P5927)**: on 1,281 items (123 of them bare ids), under 1% of the
  directory.
- **Reading bare tab pages to learn their artists**: 210,676 pages, 60 times the listings. Each is a tab page for a
  song nobody asked for.
- **UG's search, `/search.php`**: robots.txt closes it to everyone.
- **A web-search API** (docs/web-search.md): it needs a key (Brave) or a SearXNG the owner doesn't run. It asks a site
  for each search, which "a search asks no site" forbids, and it answers one query, never a directory.
- **`/explore`**: open to `*`, but it lists tabs, not artists (two million of them, tens of thousands of pages), and
  UG closes it to the big crawlers.
- **`0-9` alone** (104 pages, two thirds bare): it finds Кино and Édith Piaf, never Song Dongye, Joaquín Sabina,
  Maná or Beyoncé, who are filed under their Latin first letters.
- **UG's app API**: it needs UG's key, and caracole keeps no secret.

## The owner's decisions

1. **Build it, or turn it down**, leaving the pasted link as the only way in.
2. **The first read**: by hand in one evening (about 4 h), or a nightly budget (120: 30 nights; 240: 15).
3. **The upkeep**: each letter again after 30, 90 or 180 days (about 117, 40 or 20 requests a night).
4. **The second pass**: none; the 1,000 or 3,000 bare artists with most tabs; or all. And its nightly budget.
5. **Its budgets**: their own beside UG's 60 (AGENTS.md's "ug 60" grows), or only what the 60 leaves.

## Open questions

1. How much the order moves from night to night, the tail's above all. The first read measures it: each round's ids
   seen against `artists_count`.
2. UG's terms of service (ultimate-guitar.com/about/tos.htm, read on 2026-11-17, one request) name no bots,
   scrapers, crawlers or automated access. They say content "may be accessed for your personal, non-commercial use
   only", and that you "will not duplicate or otherwise reproduce the Content … onto any … memory or device", except
   to print text tabs and lyrics for personal, non-commercial use. That bears on what caracole already keeps (a UG
   sheet in a private library) more than on the directory, which keeps artists' names and ids, never a tab. Whether
   AGENTS.md should name these terms, as it does harptabs.com's, is the owner's call.
3. Namesakes: is "whole name, then most tabs" right? Or should a song with two UG artists of one name stay on the
   to-do page until a `[artist_url]` picks one?
