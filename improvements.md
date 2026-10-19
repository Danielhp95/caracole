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
