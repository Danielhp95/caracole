## Improvements

This file is a living document where I write down what improvements I want for caracole, and You will spawn at least one agent for each to reserach, implement and test these changes. Once something has been implemented, you will add a paragraph at the end of each subsection linking to the git commit that implemented it and any relevant short information about it

## Robustness to misspeled / or similar but not quite the same name searches

Before I trie to add a song `"caracole add "epic" "I'm not sorry for loving you"`. Turns out that the actual name was "not sorry for loving you" by "Epic the musical". I want to be robust to these discrepancies. The way that I found what was the actual tab was by leveraging available search engines on the internet, specifically I used duckduckgo and searched for the name of the song / author and "ultimate guitar". Form that I found:

`https://tabs.ultimate-guitar.com/tab/misc-musicals/epic-the-musical-not-sorry-for-loving-you-chords-4742072`

I believe this system to be powerful enough. But there may be better ways of being fault tolerant in this sense

**Done in [97a2c3f](https://github.com/Danielhp95/caracole/commit/97a2c3f).** Names that aren't quite UG's are now matched offline, with no web search. When nothing matches exactly, a new matching step suggests candidates, and only ever for review, never accepted on its own. It looks for three kinds:
- **word_title:** a title of the artist's that holds yours word for word.
- **typo_artist:** an artist one or two letters off ("Coldplya" finds coldplay).
- **catch_all:** UG's catch-all artists (misc-musicals, misc-soundtrack, misc-cartoons, misc-television, misc-computer-games), whose titles hold the show's name.

`caracole add "epic" "I'm not sorry for loving you"` now prints "Did you mean: … misc-musicals/epic-the-musical-not-sorry-for-loving-you" right away. Settle it with `caracole review` or on the to-do page. `caracole search` shows a review's first candidates under the song.

A fallback through an official web-search API, using your own key (Brave Search API or your own SearXNG), is designed in docs/web-search.md but not built. No search engine's result pages are ever scraped.

## Key information

- Add key for each song. That's added, denote whether the key comes from running a model locally or extracted fro the information on the tab itself.
- Allow searching / filtering by key

**Done in [c8cc83d](https://github.com/Danielhp95/caracole/commit/c8cc83d).** Every song with a sheet now has a key, and caracole says where it came from:
- "from the tab": UG's key for the kept version, or one the sheet states (`{key: Am}`, `Key: G`, LaCuerda's `Tono: La menor`).
- "estimated from the chords": worked out offline from the human sheet's chords.
- "from the audio": what the local model heard, for an auto-chords sheet.

The key is stored in info.json as `key` and `key_source`; the song's identity moved to `identity_key`.

To filter by key:
- **index.html:** each card shows the key ("Key A minor (from the tab)"). The Key menu lists each key once, spellings merged ("F# / Gb minor · 2"). The search box takes a typed key ("a minor", "f# major", "bbm"); "minor" alone shows every minor song.
- **Command line:** `caracole search --key am` (any case or spelling) lists your songs in that key.

The code is in `src/caracole/keys.py`.

## Web server

- Instead of having a static site, allow for a lightweight server that wraps around the `caracole` CLI such that I can request songs from the website
- Improve the website, making it more visually appealing and functional. Do a subagent driven research for this

**Done in [9cd5423](https://github.com/Danielhp95/caracole/commit/9cd5423).** `caracole serve` serves the library page at http://127.0.0.1:8737/. It uses only Python's standard library. Options: `--address`, `--port`, `--allow-host`, `--token-file`.
- **Request a song:** the form writes the song to wanted.txt, as `caracole add` does. With "Fetch it now" ticked, it also runs `caracole match`, `caracole fetch --song` and `caracole render` for that song.
- **Fetch now:** each wanted card has this button. A song that needs review shows "Review first" instead.
- **Politeness:** commands run one at a time, each under caracole's lock, with the usual pauses and budgets.
- **/jobs:** shows each command's output.
- **Security:** it refuses cross-origin writes and unknown host names. `--token-file`, or a `web_token` credential, asks each browser for a token once.

The page itself was redesigned:
- one responsive grid, so a desktop shows three or four columns;
- per-artist coloured monograms;
- an A–Z letter strip;
- a "Title A–Z" sort;
- clicking an artist's name shows only their songs, with a chip that removes the filter.

On NixOS, `services.caracole.web.enable = true` runs it as `caracole-web.service`. The options `web.address`, `web.allowedHosts` and `web.openFirewall` open it to a LAN or tailnet. See docs/usage.md ("caracole serve") and docs/deploy.md (section 8).

## Sheet pdf "makeup" and phone quality.

- Is there a way to make the music sheet pdf cleaner so that it's more readable?
- I want to make this into something that I can access on my phone, a pdf is not the most friendly for this kind of thing. do a /deep-research for coming up with an elegant, functional, feature-rich yet not in-your-face design. Featurefullness includes:
- Highlighting chords on the sheet.
- Showing different chord positions (how to digitize it) in which they can be played on the guitar.
- Allowing for transpositions (i.e adding or substracting semitones to each chord)
- Chord alternatives. If we have the key of a song. we can propose different chords to change the "feel" of the song while remaining in key
- Mode changes. If we have the key (say, C minor) we can change it to C major. Allow this for all modes.

**Done in [13eb592](https://github.com/Danielhp95/caracole/commit/13eb592).**
- **The PDFs** have caracole's own look: Helvetica, bold rust-coloured chords, chord diagrams at the top, section names on a light band, and one line under the title ("Soda Stereo · Key Bm · Capo 2").
- **The phone page:** beside every PDF there is now a `sheet.html`, which opens from the synced folder with no server and loads nothing. It has:
  - chords highlighted over the lyrics, never split from their syllable;
  - tap a chord for its fingerings (from chords-db, MIT) and for chords to play instead that stay in the key;
  - the Key button: transpose by semitones, capo suggestions, and a mode change on the same tonic (major, minor, dorian…: each chord moves to the same scale degree);
  - text size, a strip with every chord shape, and autoscroll.
- **Its key** is the song's key, from the key work, so the viewer, info.json and index.html agree.
- **index.html** links each viewer first.

**Served too, in [a7e1106](https://github.com/Danielhp95/caracole/commit/a7e1106).** `caracole serve` sends each song's viewer, so a card's "Sheet viewer" link works over the server, on a phone too.
- **Only caracole's own page:** it sends a viewer only while it is still the page caracole last wrote (its SHA-256 and length are recorded at render), never through a symbolic link.
- **In a sandbox:** its Content-Security-Policy is the page's own, so it runs only its own script and style.
- **Edited copies:** a viewer edited on a synced device answers 404, and says the PDF is beside it.
- **Settings in the address:** the transposition, mode and capo live in the address (`sheet.html#t=2&mode=aeolian`), so a reload or Back keeps them.

## yt-dlp for downloading songs

Ignore all comments about "legally buying a song". If a song is not found, allow for a "download and extract chords" pipeline that will download the song from youtube via yt-dlp (as a build dependency)

**Done in [0183d3b](https://github.com/Danielhp95/caracole/commit/0183d3b).** A song with no human sheet now gets its audio from YouTube, and the auto-chords unit makes its chords.
- **The pick:** each night, after the scan, the new youtube step asks yt-dlp's search for `ytsearch8:<artist> <title>`. It takes the upload whose title and channel name the song (names in two scripts match; a Chinese, Japanese or Korean title must stand on its own in the video's title, never as the start of a longer one), whose length is within 20 s of the song's, and that isn't a cover, live, karaoke, lesson or slowed version. The artist's Topic channel and official audio come first.
- **The audio** goes, as m4a, into caracole's cache (`cache_dir/youtube/`), never into the synced library. Then caracole-autochords writes `sheet (auto).txt`, whose first line names the video; on the page its mark is YouTube's. A purchase or a human sheet found later takes its place, and the audio is deleted. Remove deletes it too.
- **The limits:** 6 yt-dlp runs a night (about three songs), 15–30 s apart, no cookies, no login, none of caracole's secrets in yt-dlp's environment. A bot check, a 429 or a 403 is a block, with the usual cooldown and one ntfy alert. A video that fails 3 times is given up, and the next run searches again.
- **Where:** only where auto-chords is on (`services.caracole.autochords.enable = true`; that package has yt-dlp with ffmpeg and deno). `[providers.youtube] enabled = false` turns it off.
- **Fixing a pick:** `"Artist - Title" = "<video URL>"` (or `"none"`) under `[youtube]` in overrides.toml, or `caracole youtube --song "Artist - Title" --url URL` (or `--none`). `caracole youtube` alone runs the step by hand.
- **The to-do page:** the buy list becomes "No human sheet found yet", each song with its state, plus "Nothing on YouTube for these" with the lines to paste.

This route goes against YouTube's robots.txt and terms. It is your choice, and AGENTS.md records it as the one scoped exception.

## faster songs lookups

For UG, have the 10-20 second slow polling for when building the index, but remove it when we are searching. For la cuerda / muse score, don't wait until the end of the day to trigger a search. do it immediately. This tool will not be used simply as a library for me to have downloaded tabs. It will also be used to quickly look up tabs on the spot. As a replacement for ultimate guitar. So I need it to be fast and responsive. Design how to fasten this look-up process so that it feels as fast as looking up a tab in ultimate guitar

## Better info when downlading

When requesting a new song, having a full new page is a bit verbose when I normally just want one song downloaded. And even as a "bulk" it is a bit verbose. 

**Done in [8975cc0](https://github.com/Danielhp95/caracole/commit/8975cc0).** A request no longer opens a page of command output: the library page stays where it is, and the song's card says how the request goes on one line, "Queued…", then "Fetching from Ultimate Guitar…", then "Ready · Open sheet". Other endings:
- "Not found", only when Ultimate Guitar was actually asked during the request and has no sheet;
- "Needs review · Pick the match", which opens the card's picker;
- "Not fetched yet · Details", after a cooldown, a block, a spent budget or an error (never a miss: the song waits for the next run).

A new song gets its own card under the form ("Just requested"), which fills in with its files. Several requests also show as one compact list in a corner, folded on a phone. `/jobs` is one line per request, with the output folded under it. On the command line, `caracole add`, `search --add` and `fetch --song` print one line for the song (`-v` for the detail). The line comes from `src/caracole/web/status.py`; only the served page asks the server about it, and `index.html` on disk asks nothing of anyone.

## Remove button

Have a button to remove the tab from caracole so that it's removed localy, when running `caracole run` it won't be redownloaded and essentially permantently removed from the system until it is requested again.

**Done in [8bf75db](https://github.com/Danielhp95/caracole/commit/8bf75db).** Remove a song with `caracole remove "Artist - Title"`, or with the **Remove…** button on its card in `caracole serve`. Both first show what goes and what stays, then ask; `--yes` skips the question on the command line.
- **What goes:** the song's lines in wanted.txt (the rest of the file, comments included, stays as it was), the files caracole wrote in its folder (sheets, tabs, Guitar Pro files, scores, .cho, PDFs, viewers, lyrics, info.json), the folder once empty, and its database record.
- **What stays:** files caracole didn't write, which the removal names, and the audio in Music/.
- **It stays out:** caracole remembers the song as removed, so `caracole run` brings it back from neither wanted.txt nor a Spotify playlist that still lists it. The to-do page, index.html and `caracole search` no longer show it.
- **Getting it back:** `caracole add`, a web request, its line typed into wanted.txt again, or adding it on Spotify after the removal all bring it back as a new song.
- `caracole remove --list` shows what you've removed.

## what to do with chord pro files?

What do I do with those files? Should I open them with some specific program?

**Answer.** You don't need to do anything with them. `sheet.cho` is the sheet in ChordPro, a plain-text format with each chord in brackets before its syllable (`[Am]Yesterday`). caracole writes it from `sheet.txt`, in your key (`[transpose]`), and then renders `sheet.pdf` from it with the `chordpro` program. It's the step between the tab and the PDF.

It's also useful on its own: songbook apps import ChordPro directly and handle autoscroll, transposition and chord diagrams on a phone or tablet. Examples are SongbookPro (Android, iOS, Windows) and OnSong (iOS). Any text editor opens it too.

Don't edit it in place, because the next render rewrites it. Copy it under another name for your own version, and use `[transpose]` in overrides.toml to change the key.

Once the phone sheet viewer lands (`sheet.html`, in progress), it covers the same ground in the browser. This answer is also in docs/usage.md (the library folder section).

## Better presentation for sources and reslts

Currently we have a "gallery view" for songs. I would also like to have a row-style view where I can see more results at once. I would like when searching for tabs to have similar outputs. Depending on which source the song comes from (la cuerda, ultimate guitar) I want a little icon to denote it, make the icon come from the webisite's own icon

**Done in [aa5ad75](https://github.com/Danielhp95/caracole/commit/aa5ad75).** The library page (the file and the served page) has a **Cards/Rows** switch beside the Key menu, kept in the address (`#view=rows`).
- **Rows:** one line per song on a laptop (about twenty to a screen), two on a phone: the title and its button, then the artist, the key and the status. Search, the status buttons, the Key menu, the sort, the A–Z letters and clicking an artist work the same in both views.
- **On `caracole serve`** a row does everything a card does: Fetch now, Pick the match, Removing…, and the request's line under it. Its ⋯ holds the other files and links.
- **Source icons:** every sheet and file shows where it came from with the site's own icon (Ultimate Guitar, LaCuerda, LRCLIB, gtptabs.com, MuseScore, YouTube), or a lettered badge (UG, LC…) until the icon is in. Auto sheets show ♪, files from `_inbox/` ↓. A new nightly `icons` step fetches each site's favicon once, politely, into the cache folder, and the page inlines them, so it still loads nothing from the network. `caracole icons` fetches the missing ones now.
- **Search results look alike:** `caracole search` tags each hit with its source (`[UG]`, `[LaCuerda]`, `[auto]`), and the page's search shares the row's layout.

## Songbooks

bundle in a songbook app too. I want the ability to "make songbook" so that i select different songs and a songbook is generated from them

## Allow for disambiguation on the browser

It's great that the cli allows for disambiguation by having differnet alternatives and then selecitng number, surface this in the browser too

**Done in [e9a260b](https://github.com/Danielhp95/caracole/commit/e9a260b).** A song that needs review shows its candidates on its card, numbered as `caracole review` numbers them. Each has the UG artist and title, why the matcher proposed it ("artist spelled differently", "title only: another artist's song, probably a cover", "under UG's catch-all misc-musicals"), its score, its tab counts and a link to its UG page.
- **On `caracole serve`:** "Pick the match" replaces "Review first". Choose a candidate or "None of these" and press Pick. With "Fetch it now" ticked (the default), the song is fetched and rendered right after, and the card shows how it goes, as a request does. If "None of these" leaves other candidates, the card offers those.
- **A song the index didn't match** gets "Look in the index", which offers what `caracole search` finds for it.
- **On index.html from disk:** the list is read-only and ends with the line to run.
- **From a terminal:** the answer is written exactly as `caracole review` writes it, through the new `caracole review --song "ARTIST - TITLE" --pick N` (or `--pick ARTIST/SONG`, or `--none`).
## Design pass

After finishing, do a /deep-research for what is the best UX design for this type of application for feature discoverability, usability, snappyness and overall user experience design. Take inspiration from ultimate guitar and other websites that already present this kind of information. Do a research too on lightweight javascript frameworks (like d3.js or other alterntaives) to come up with cool and useful designs. Find anti-patterns in the current implementation and remove them too. Essentially, do a strong design pass with /deep-research

## Searching only by artist or songname

Sometimes one does not know the artist, we need to allow for either or scenarios for searching

## Unify search and "request a song" so that we have both of them on the same bar

typing will filter from what we have in our library, and pressing enter will return whatever are the most likely matches from the different sources
