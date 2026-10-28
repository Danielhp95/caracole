# caracole

**Your own songbook, built while you sleep.**

List the songs you want to play. Every night caracole finds their chords and lyrics and files
them in a private library on your computer, as sheets to read in the browser, on your phone
or on paper.

![The library page searching for "traditional": four songs you have and three you can get, under one artist](docs/screenshots/library.png)

![Greensleeves: chords over the lyrics, chord shapes on the left, transpose, capo and mode on the right](docs/screenshots/sheet.png)

## What you get

- **Sheets for your songs:** chords from Ultimate Guitar and LaCuerda, lyrics from LRCLIB,
  and Guitar Pro files and harmonica tabs where they exist.
- **Chords for the uncharted:** an optional add-on works them out from the audio.
- **Made for playing:** transpose, capo, chord shapes for guitar, ukulele, piano and
  harmonica, pinyin over Chinese lyrics, PDFs, and songbooks with each song in your key.
- **Yours alone:** no account, no cloud, one folder you own.

<details>
<summary>More pictures</summary>

<p>
  <img src="docs/screenshots/phone-chord.png" width="260" alt="Scarborough Fair on a phone, the card of its G chord at the foot: its shape, its notes and a scale to solo in">
  <img src="docs/screenshots/phone-pinyin.png" width="260" alt="A Chinese folk song on a phone, with the pinyin of each character between it and its chord">
</p>

![The Harmony panel: a Roman numeral beside each chord, and each section's progression](docs/screenshots/harmony.png)

![The Songbooks tab: a set list, each song with the key it is played in](docs/screenshots/songbooks.png)

<img src="docs/screenshots/songbook-pdf.png" width="440" alt="A page of a songbook's PDF: chord diagrams, then the verses with the chords over the words">

![The Guitar Pro page: a melody drawn as a score and a tab, with Play and a button for each track](docs/screenshots/guitar-pro.png)

A demo library of public-domain songs, which [docs/screenshots/make.py](docs/screenshots/make.py)
builds and photographs.

</details>

## Try it

```sh
nix shell github:Danielhp95/caracole     # Linux x86_64; other ways in docs/install.md
caracole add "Oasis - Wonderwall"        # "Artist - Title", a line of ~/Tabs/wanted.txt
caracole index build                     # once, about 10 minutes
caracole run                             # what the nightly run does, now
caracole serve                           # your library at http://127.0.0.1:8737/
```

Your library is the folder `~/Tabs`; nothing needs configuring to start. `caracole serve` has
no sign-in, so share it only on a network you trust.

## Be a good guest

caracole reads other people's websites gently: one request at a time, seconds apart, a small
budget a night, never a page a site's robots.txt closes ([how](docs/usage.md#caracole-run)).
The exception is YouTube: the optional auto-chords add-on takes the audio of a few uncharted
songs a night from it, against its robots.txt and terms. Turn that off with
`[providers.youtube] enabled = false` ([why](docs/usage.md#audio-from-youtube)). The sheets and
lyrics are other people's work, so keep your library private.

## More

[Install](docs/install.md) · [Usage](docs/usage.md) · [Run it on a server](docs/deploy.md) ·
[Android app](android/README.md)

To hack on it: `nix develop`, then `pytest -q`. [AGENTS.md](AGENTS.md) says how the code is
laid out and the rules a change keeps.

MIT licensed.
