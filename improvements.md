## Improvements

This file is a living document where I write down what improvements I want for caracole, and You will spawn at least one agent for each to reserach, implement and test these changes. Once something has been implemented, you will add a paragraph at the end of each subsection linking to the git commit that implemented it and any relevant short information about it

## Robustness to misspeled / or similar but not quite the same name searches

Before I trie to add a song `"caracole add "epic" "I'm not sorry for loving you"`. Turns out that the actual name was "not sorry for loving you" by "Epic the musical". I want to be robust to these discrepancies. The way that I found what was the actual tab was by leveraging available search engines on the internet, specifically I used duckduckgo and searched for the name of the song / author and "ultimate guitar". Form that I found:

`https://tabs.ultimate-guitar.com/tab/misc-musicals/epic-the-musical-not-sorry-for-loving-you-chords-4742072`

I believe this system to be powerful enough. But there may be better ways of being fault tolerant in this sense

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

## yt-dlp for downloading songs

Ignore all comments about "legally buying a song". If a song is not found, allow for a "download and extract chords" pipeline that will download the song from youtube via yt-dlp (as a build dependency)

## faster songs lookups

For UG, have the 10-20 second slow polling for when building the index, but remove it when we are searching. For la cuerda / muse score, don't wait until the end of the day to trigger a search. do it immediately. This tool will not be used simply as a library for me to have downloaded tabs. It will also be used to quickly look up tabs on the spot. As a replacement for ultimate guitar. So I need it to be fast and responsive. Design how to fasten this look-up process so that it feels as fast as looking up a tab in ultimate guitar

## Better info when downlading

When requesting a new song, having a full new page is a bit verbose when I normally just want one song downloaded. And even as a "bulk" it is a bit verbose. 

## Remove button

Have a button to remove the tab from caracole so that it's removed localy, when running `caracole run` it won't be redownloaded and essentially permantently removed from the system until it is requested again.

## what to do with chord pro files?

What do I do with those files? Should I open them with some specific program?

**Answer.** You don't need to do anything with them. `sheet.cho` is the sheet in ChordPro, a plain-text format with each chord in brackets before its syllable (`[Am]Yesterday`). caracole writes it from `sheet.txt`, in your key (`[transpose]`), and then renders `sheet.pdf` from it with the `chordpro` program. It's the step between the tab and the PDF.

It's also useful on its own: songbook apps import ChordPro directly and handle autoscroll, transposition and chord diagrams on a phone or tablet. Examples are SongbookPro (Android, iOS, Windows) and OnSong (iOS). Any text editor opens it too.

Don't edit it in place, because the next render rewrites it. Copy it under another name for your own version, and use `[transpose]` in overrides.toml to change the key.

Once the phone sheet viewer lands (`sheet.html`, in progress), it covers the same ground in the browser. This answer is also in docs/usage.md (the library folder section).
